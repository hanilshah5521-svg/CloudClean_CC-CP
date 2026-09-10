"""Large-file classification against configurable thresholds."""


def size_tier(size_bytes: int, large_mb: int, very_large_mb: int, huge_mb: int) -> str | None:
    mb = size_bytes / (1024 * 1024)
    if mb >= huge_mb:
        return "huge"
    if mb >= very_large_mb:
        return "very_large"
    if mb >= large_mb:
        return "large"
    return None
