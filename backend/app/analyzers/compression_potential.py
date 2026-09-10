"""Estimate compression potential from metadata alone (no download).

These are *estimates* used to rank recommendations — the compression engine
(app/compression/*) computes the real, actual saving once a user triggers
an optimization. Estimated and actual are never conflated (spec #39).
"""
from dataclasses import dataclass

from app.utils.classify import is_already_compressed

MB = 1024 * 1024


@dataclass
class CompressionEstimate:
    compressible: bool
    method: str
    estimated_ratio: float  # fraction of size expected to be saved, e.g. 0.45
    confidence: float
    reason: str


def estimate(category: str, extension: str, size_bytes: int) -> CompressionEstimate:
    ext = extension.lower()

    if is_already_compressed(ext) and ext not in (".jpg", ".jpeg"):
        return CompressionEstimate(False, "none", 0.0, 0.0, "Already a compressed format; additional compression may provide little or no storage benefit.")

    if category == "images":
        if ext in (".jpg", ".jpeg"):
            ratio = 0.5 if size_bytes > 3 * MB else 0.25 if size_bytes > 1 * MB else 0.1
            confidence = 0.9 if size_bytes > 3 * MB else 0.6
            return CompressionEstimate(size_bytes > 200 * 1024, "jpeg_recompress", ratio, confidence, "JPEG re-encoding at a tuned quality level typically recovers significant size with minimal visible loss.")
        if ext == ".png":
            ratio = 0.25 if size_bytes > 1 * MB else 0.1
            return CompressionEstimate(size_bytes > 200 * 1024, "png_optimize", ratio, 0.6, "Lossless PNG re-compression (no format change) can shrink poorly-optimized PNGs.")
        if ext == ".webp":
            return CompressionEstimate(size_bytes > 500 * 1024, "webp_optimize", 0.1, 0.4, "WebP is already efficient; only marginal savings are expected.")
        return CompressionEstimate(False, "none", 0.0, 0.0, "Unsupported image format for safe re-encoding.")

    if category == "pdf":
        ratio = 0.3 if size_bytes > 5 * MB else 0.1
        confidence = 0.7 if size_bytes > 5 * MB else 0.4
        return CompressionEstimate(size_bytes > 500 * 1024, "pdf_optimize", ratio, confidence, "PDF structural optimization (stream compression, duplicate object removal) without altering content.")

    if category in ("documents", "spreadsheets", "presentations"):
        # .docx/.xlsx/.pptx are already zip containers — re-zipping rarely helps.
        return CompressionEstimate(False, "archive_candidate", 0.15, 0.3, "Office Open XML files are already compressed internally; bundling several into a ZIP archive is usually more effective than per-file compression.")

    if category in ("video", "audio"):
        return CompressionEstimate(False, "none", 0.0, 0.0, "Already a compressed media format; re-encoding risks quality loss for little guaranteed saving.")

    return CompressionEstimate(False, "archive_candidate", 0.1, 0.2, "Generic file type; archiving alongside similar inactive files may recover some space.")
