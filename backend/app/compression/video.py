"""Video re-encoding with ffmpeg + ffprobe, run as subprocesses on files on
disk — videos are gigabytes, so nothing here ever holds one in memory.

Output: H.264 (libx264, CRF ~27, preset medium), AAC 128 kbps audio, same
resolution, written in the input's own container (so the Drive file's name
and type stay truthful) with +faststart for MP4/MOV so it streams in a browser.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.analyzers.compression_potential import AUDIO_KBPS
from app.core.config import settings

MUXERS = {".mp4": "mp4", ".m4v": "mp4", ".mov": "mov", ".mkv": "matroska"}
_HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ (HDR10/Dolby Vision) and HLG
MAX_DURATION_DRIFT_S = 1.0


class VideoError(Exception):
    pass


def find_tool(name: str) -> str | None:
    """Path to ffmpeg/ffprobe: FFMPEG_PATH/FFPROBE_PATH if set, else PATH.
    On Windows also winget's package folder — `winget install ffmpeg` only
    puts it on PATH for terminals opened afterwards."""
    configured = getattr(settings, f"{name}_path", "")
    if configured:
        return configured if Path(configured).is_file() else shutil.which(configured)
    found = shutil.which(name)
    if found or sys.platform != "win32":
        return found
    pattern = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages",
                           "*FFmpeg*", "*", "bin", f"{name}.exe")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def ffmpeg_available() -> bool:
    return bool(find_tool("ffmpeg") and find_tool("ffprobe"))


def _require(name: str) -> str:
    path = find_tool(name)
    if not path:
        raise VideoError(f"{name} isn't installed on the worker (see README: Video compression).")
    return path


@dataclass
class VideoInfo:
    duration_s: float
    video_index: int | None  # stream index of the real video (not embedded cover art)
    video_codec: str
    pix_fmt: str
    color_transfer: str
    width: int
    height: int
    audio_streams: int
    subtitle_streams: int

    @property
    def has_video(self) -> bool:
        return self.video_index is not None

    @property
    def has_audio(self) -> bool:
        return self.audio_streams > 0


def probe(path) -> VideoInfo:
    proc = subprocess.run(
        [_require("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise VideoError(f"ffprobe couldn't read the video: {_tail(proc.stderr)}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    videos = [s for s in streams
              if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    main = videos[0] if videos else {}
    return VideoInfo(
        duration_s=float((data.get("format") or {}).get("duration") or main.get("duration") or 0),
        video_index=main.get("index"),
        video_codec=main.get("codec_name", ""),
        pix_fmt=main.get("pix_fmt", ""),
        color_transfer=main.get("color_transfer", ""),
        width=int(main.get("width") or 0),
        height=int(main.get("height") or 0),
        audio_streams=sum(1 for s in streams if s.get("codec_type") == "audio"),
        subtitle_streams=sum(1 for s in streams if s.get("codec_type") == "subtitle"),
    )


def unsupported_reason(info: VideoInfo) -> str | None:
    """Why re-encoding this video could visibly lose something, or None if it's safe."""
    if not info.has_video:
        return "No video stream found."
    if info.duration_s <= 0:
        return "Couldn't determine the video's duration."
    if info.color_transfer in _HDR_TRANSFERS:
        return "HDR video: re-encoding it to standard H.264 would wash out its colors, so it was left as is."
    if re.search(r"1[0-6](le|be)$", info.pix_fmt):  # yuv420p10le, p010le, ...
        return f"{info.pix_fmt} is a high-bit-depth format; 8-bit H.264 would lose color depth, so it was left as is."
    if info.subtitle_streams:
        return "Has subtitle tracks that re-encoding could drop, so it was left as is."
    return None


def transcode(src, dst, info: VideoInfo, extension: str, on_progress=None) -> None:
    """Re-encode src into dst. on_progress gets a 0-1 fraction, parsed from
    ffmpeg's -progress output against the known duration."""
    muxer = MUXERS.get(extension.lower())
    if not muxer:
        raise VideoError(f"{extension} videos aren't re-encoded.")
    cmd = [
        _require("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(src),
        "-map", f"0:{info.video_index}", "-map", "0:a?", "-map_metadata", "0",
        "-c:v", "libx264", "-preset", settings.video_preset, "-crf", str(settings.video_crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k",
        "-threads", str(settings.video_threads),
    ]
    if muxer in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]
    cmd += ["-f", muxer, "-progress", "pipe:1", "-nostats", str(dst)]

    log_path = Path(dst).with_suffix(".ffmpeg.log")
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        # stderr goes to a file: a pipe nobody reads could fill up and stall ffmpeg.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True, **_below_normal_priority())
        _lower_priority(proc)
        try:
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if on_progress and key in ("out_time_us", "out_time_ms") and value.isdigit():
                    # Both keys are microseconds (out_time_ms is misnamed in ffmpeg).
                    on_progress(min(1.0, int(value) / 1_000_000 / info.duration_s))
            returncode = proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            raise
    if returncode != 0:
        raise VideoError(f"ffmpeg failed: {_tail(log_path.read_text(encoding='utf-8', errors='replace'))}")


def verify(original: VideoInfo, encoded: VideoInfo) -> None:
    """The re-encoded file must still be the same video: a video stream, the
    same audio tracks, and the same duration (within a second)."""
    if not encoded.has_video:
        raise VideoError("The re-encoded file has no video stream.")
    if encoded.audio_streams < original.audio_streams:
        raise VideoError("The re-encoded file lost an audio track.")
    if abs(encoded.duration_s - original.duration_s) > MAX_DURATION_DRIFT_S:
        raise VideoError(f"The re-encoded file is {encoded.duration_s:.1f}s long instead of {original.duration_s:.1f}s.")


def _below_normal_priority() -> dict:
    # Keep the API responsive on a small shared VM while ffmpeg runs.
    if sys.platform == "win32":
        return {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS}
    return {}


def _lower_priority(proc) -> None:
    if hasattr(os, "setpriority"):
        try:
            os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
        except OSError:
            pass


def _tail(text: str, lines: int = 5) -> str:
    return " ".join((text or "").strip().splitlines()[-lines:])[:500] or "no details"
