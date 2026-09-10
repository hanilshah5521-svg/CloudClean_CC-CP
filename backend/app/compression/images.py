"""Real image compression using Pillow. Actually re-encodes bytes — no fakery."""
import io

from PIL import Image


def compress_jpeg(data: bytes, quality: int = 75) -> bytes:
    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def compress_png(data: bytes) -> bytes:
    img = Image.open(io.BytesIO(data))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True, compress_level=9)
    return out.getvalue()


def compress_webp(data: bytes, quality: int = 80) -> bytes:
    img = Image.open(io.BytesIO(data))
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


def convert_to_webp(data: bytes, quality: int = 80) -> bytes:
    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()
