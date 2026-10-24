"""Estimate compression potential from metadata alone (no download).

These are *estimates* used to rank recommendations — the compression engine
(app/compression/*) computes the real, actual saving once a user triggers
an optimization. Estimated and actual are never conflated (spec #39).
"""
from dataclasses import dataclass, field

from app.core.config import settings
from app.utils.classify import is_already_compressed

MB = 1024 * 1024


@dataclass
class CompressionEstimate:
    compressible: bool
    method: str
    estimated_ratio: float  # fraction of size expected to be saved, e.g. 0.45
    confidence: float
    reason: str
    details: dict = field(default_factory=dict)


def estimate(category: str, extension: str, size_bytes: int, *, duration_ms: int = 0,
             width: int = 0, height: int = 0) -> CompressionEstimate:
    """duration_ms/width/height come from Drive's videoMediaMetadata and are
    only used for videos."""
    ext = extension.lower()

    if category == "video":
        return estimate_video(ext, size_bytes, duration_ms, width, height)

    if is_already_compressed(ext) and ext not in (".jpg", ".jpeg"):
        return CompressionEstimate(False, "none", 0.0, 0.0, "Already a compressed format; additional compression may provide little or no storage benefit.")

    if category == "images":
        if ext in (".jpg", ".jpeg"):
            ratio = 0.5 if size_bytes > 3 * MB else 0.25 if size_bytes > 1 * MB else 0.1
            confidence = 0.9 if size_bytes > 3 * MB else 0.6
            return CompressionEstimate(size_bytes > 200 * 1024, "jpeg_recompress", ratio, confidence, "JPEG re-encoding at a tuned quality level typically recovers significant size with minimal visible loss.")
        if ext == ".png":
            # Measured on 60 real PNGs (app assets, screenshots): median 6%
            # saving, max 13%, only 1 in 20 reached 10%. Only badly exported
            # PNGs shrink a lot — which can't be told from metadata — so
            # under the default 10% minimum PNGs aren't suggested.
            return CompressionEstimate(size_bytes > 200 * 1024, "png_optimize", 0.06, 0.3,
                                       "Lossless PNG re-compression (no format change, pixels identical). Most PNGs are already well compressed and save around 5-10%; badly exported ones can save much more.")
        if ext == ".webp":
            return CompressionEstimate(size_bytes > 500 * 1024, "webp_optimize", 0.1, 0.4, "WebP is already efficient; only marginal savings are expected.")
        return CompressionEstimate(False, "none", 0.0, 0.0, "Unsupported image format for safe re-encoding.")

    if category == "pdf":
        # Structural optimization only (re-compressing streams, packing
        # object streams, dropping unused objects) — images inside are never
        # re-encoded. PDFs from modern apps are already compressed, and big
        # PDFs are usually big because of scanned/embedded images, so size is
        # no sign of a larger saving. Old or badly generated PDFs can shrink a
        # lot; the real saving is measured before anything is uploaded.
        return CompressionEstimate(size_bytes > 500 * 1024, "pdf_optimize", 0.1, 0.3,
                                   "Lossless PDF optimization (re-compressing its internal data and dropping unused leftovers); images, fonts and text are untouched. Typical saving is around 10%; scanned PDFs barely shrink, while old or badly generated PDFs can shrink a lot.")

    if category in ("documents", "spreadsheets", "presentations"):
        # .docx/.xlsx/.pptx are already zip containers — re-zipping rarely helps.
        return CompressionEstimate(False, "archive_candidate", 0.15, 0.3, "Office Open XML files are already compressed internally; bundling several into a ZIP archive is usually more effective than per-file compression.")

    if category == "audio":
        return CompressionEstimate(False, "none", 0.0, 0.0, "Already a compressed media format; re-encoding risks quality loss for little guaranteed saving.")

    return CompressionEstimate(False, "archive_candidate", 0.1, 0.2, "Generic file type; archiving alongside similar inactive files may recover some space.")


# Containers the video job writes back in the same format (so the file's name
# and type stay truthful). WebM can't hold H.264; AVI is left alone.
REENCODABLE_VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv"}
VIDEO_MIN_BYTES = 50 * MB  # below this, minutes of CPU for a few MB isn't worth it
AUDIO_KBPS = 128
# Typical H.264 video bitrate at CRF ~27, preset medium, for ordinary camera
# footage, by the frame's short side (so portrait phone video counts too).
_H264_KBPS_BY_LINES = [(480, 1200), (720, 2500), (1080, 4500), (1440, 8000), (2160, 16000)]


def target_video_kbps(width: int, height: int) -> int:
    lines = min(width, height) if width and height else 1080
    for max_lines, kbps in _H264_KBPS_BY_LINES:
        if lines <= max_lines:
            return kbps
    return int(_H264_KBPS_BY_LINES[-1][1] * (lines / 2160) ** 2)


def estimate_video(ext: str, size_bytes: int, duration_ms: int, width: int, height: int) -> CompressionEstimate:
    """Bitrate-based: a video's saving is how far its current bitrate
    (size / duration) is above what H.264 at CRF ~27 needs for its
    resolution. Phone footage (often 15-50 Mbps) shrinks a lot; screen
    recordings and already-efficient (e.g. HEVC) files barely or not at all —
    the job measures the real result and skips the upload if it isn't worth it."""
    if ext not in REENCODABLE_VIDEO_EXT:
        return CompressionEstimate(False, "none", 0.0, 0.0, "Only MP4, MOV and MKV videos are re-encoded; this container is left as is.")
    if size_bytes < VIDEO_MIN_BYTES:
        return CompressionEstimate(False, "none", 0.0, 0.0, f"Under {VIDEO_MIN_BYTES // MB} MB; re-encoding would take minutes of processing for little saving.")
    if size_bytes > settings.video_max_mb * MB:
        # Suggesting it would be a dead end: the worker refuses it (video_service).
        return CompressionEstimate(False, "none", 0.0, 0.0,
                                   f"Larger than this server's {settings.video_max_mb / 1024:g} GB video limit. To include it, raise "
                                   f"VIDEO_MAX_MB in .env and restart the worker — it needs about twice the video's size in free disk space.")
    if not duration_ms:
        return CompressionEstimate(False, "none", 0.0, 0.0,
                                   "Google Drive hasn't reported this video's length yet — usually because it's still "
                                   "processing a recent upload (minutes, longer for big videos). Without the length the "
                                   "saving can't be estimated; run Re-analyze later.")

    seconds = duration_ms / 1000
    current_kbps = size_bytes * 8 / seconds / 1000
    target_kbps = target_video_kbps(width, height) + AUDIO_KBPS
    ratio = round(max(0.0, min(0.8, 1 - target_kbps / current_kbps)), 3)
    details = {"current_kbps": round(current_kbps), "target_kbps": target_kbps, "duration_s": round(seconds, 1),
               "width": width, "height": height}
    if ratio < 0.1:
        return CompressionEstimate(False, "none", 0.0, 0.0,
                                   f"Already efficiently encoded ({current_kbps / 1000:.1f} Mbps); re-encoding would save little.",
                                   details)
    confidence = 0.7 if current_kbps > 2 * target_kbps else 0.5
    reason = (f"Re-encoding with H.264 (CRF ~27, same resolution, AAC audio) typically brings it from "
              f"{current_kbps / 1000:.1f} Mbps to about {target_kbps / 1000:.1f} Mbps. The real result depends on "
              f"the content and is measured before anything is uploaded.")
    return CompressionEstimate(True, "video_reencode", ratio, confidence, reason, details)


_TEXT_LIKE_EXT = {".txt", ".csv", ".tsv", ".log", ".json", ".xml", ".md", ".html", ".sql", ".svg"}
_UNCOMPRESSED_IMAGE_EXT = {".bmp", ".tif", ".tiff"}
_OOXML_EXT = {".docx", ".xlsx", ".pptx"}


def archive_ratio(category: str, extension: str) -> float:
    """Fraction of a file's size a ZIP (DEFLATE) archive is expected to save.

    Conservative per-type figures, so the "recoverable" number never assumes
    savings a format can't give: already-compressed formats (JPEG, MP4, ZIP…)
    get 0 and are left out of archive suggestions entirely.
    """
    ext = extension.lower()
    if is_already_compressed(ext) or category in ("video", "audio", "archives"):
        return 0.0
    if ext in _TEXT_LIKE_EXT or category == "code":
        return 0.6
    if ext in _UNCOMPRESSED_IMAGE_EXT:
        return 0.5
    if ext in _OOXML_EXT or ext == ".png" or category == "pdf":
        return 0.05  # already DEFLATE-compressed internally
    return 0.2
