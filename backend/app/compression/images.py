"""Real image compression using Pillow. Actually re-encodes bytes — no fakery.

Pillow drops all metadata on save unless it's passed back explicitly, so every
function here carries it over: EXIF (camera, date taken, GPS and — crucially —
the orientation tag; without it portrait phone photos display sideways), the
ICC color profile (without it wide-gamut photos, e.g. iPhone Display P3, shift
color), and XMP. The pixels' orientation is never changed, so the original
orientation tag stays correct.

Pillow also saves only the first frame of a multi-frame image, so animations
and JPEGs carrying a second image (an HDR gain map, a depth map) are refused
with UnsafeToCompress instead of being flattened.
"""
import io
import struct

from PIL import Image, ImageCms
from PIL.JpegImagePlugin import get_sampling

# Color space an ICC profile must describe to be valid for a Pillow mode.
_PROFILE_SPACE = {"RGB": "RGB", "RGBA": "RGB", "L": "GRAY", "LA": "GRAY", "CMYK": "CMYK"}


class UnsafeToCompress(Exception):
    """Re-encoding would lose part of the image; the file is left as it is."""


def _open_single_frame(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    if getattr(img, "n_frames", 1) > 1:
        if img.format == "MPO":
            raise UnsafeToCompress("This JPEG holds more than one image (such as an HDR gain map or a depth map). "
                                   "Re-encoding would keep only the first, so it was left as is.")
        raise UnsafeToCompress("Animated image: re-encoding would keep only its first frame, so it was left as is.")
    return img


def _webp_is_lossless(data: bytes) -> bool:
    """True if the WebP's image data is a VP8L (lossless) bitstream. The RIFF
    container lists its chunks: "VP8 " is lossy, "VP8L" lossless; extended
    files ("VP8X") add metadata chunks around one of the two."""
    pos = 12  # after "RIFF", the size and "WEBP"
    while pos + 8 <= len(data):
        fourcc = data[pos:pos + 4]
        if fourcc in (b"VP8L", b"VP8 "):
            return fourcc == b"VP8L"
        (size,) = struct.unpack("<I", data[pos + 4:pos + 8])
        pos += 8 + size + (size & 1)  # chunks are padded to an even length
    return False


def _icc_for(img: Image.Image, icc: bytes | None) -> bytes | None:
    """The source's ICC profile if it still matches the image's (possibly
    converted) mode — a CMYK or gray profile attached to RGB pixels would
    render wrong colors, so in that case none is better."""
    if not icc:
        return None
    try:
        space = ImageCms.ImageCmsProfile(io.BytesIO(icc)).profile.xcolor_space.strip()
    except (OSError, ImageCms.PyCMSError):
        return None
    return icc if _PROFILE_SPACE.get(img.mode) == space else None


def _metadata(source: Image.Image, output: Image.Image, *, xmp: bool = False) -> dict:
    """Save kwargs that carry the source's metadata over to the output."""
    kwargs = {}
    exif = source.info.get("exif") or (source.getexif().tobytes() if source.getexif() else None)
    if exif:
        kwargs["exif"] = exif
    icc = _icc_for(output, source.info.get("icc_profile"))
    if icc:
        kwargs["icc_profile"] = icc
    if "dpi" in source.info:
        kwargs["dpi"] = source.info["dpi"]
    if xmp and source.info.get("xmp"):
        kwargs["xmp"] = source.info["xmp"]
    return kwargs


def _to_rgb(img: Image.Image) -> Image.Image:
    """CMYK (print) images are converted through their own ICC profile when
    they have one, so colors stay right; a plain convert() is the fallback."""
    icc = img.info.get("icc_profile")
    if img.mode == "CMYK" and icc:
        try:
            return ImageCms.profileToProfile(img, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                             ImageCms.createProfile("sRGB"), outputMode="RGB")
        except (OSError, ImageCms.PyCMSError):
            pass
    return img.convert("RGB")


def compress_jpeg(data: bytes, quality: int = 75) -> bytes:
    img = _open_single_frame(data)
    out_img = img if img.mode in ("RGB", "L") else _to_rgb(img)
    kwargs = _metadata(img, out_img, xmp=True)
    # Keep the source's chroma subsampling: Pillow would otherwise use 4:2:0,
    # which softens sharp colored edges (text in screenshots and exports saved
    # at 4:4:4). -1 means unknown (e.g. grayscale or CMYK): Pillow's default.
    sampling = get_sampling(img)
    if sampling != -1:
        kwargs["subsampling"] = sampling
    out = io.BytesIO()
    out_img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True, **kwargs)
    return out.getvalue()


def compress_png(data: bytes) -> bytes:
    img = _open_single_frame(data)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True, compress_level=9, **_metadata(img, img))
    return out.getvalue()


def compress_webp(data: bytes, quality: int = 80) -> bytes:
    img = _open_single_frame(data)
    out = io.BytesIO()
    if _webp_is_lossless(data):
        # Stays lossless: for lossless WebP, quality is effort (100 = smallest
        # file), and exact keeps the color under fully transparent pixels.
        img.save(out, format="WEBP", lossless=True, quality=100, method=6, exact=True,
                 **_metadata(img, img, xmp=True))
    else:
        img.save(out, format="WEBP", quality=quality, method=6, **_metadata(img, img, xmp=True))
    return out.getvalue()


def convert_to_webp(data: bytes, quality: int = 80) -> bytes:
    img = _open_single_frame(data)
    out_img = img if img.mode in ("RGB", "RGBA") else img.convert("RGBA" if "A" in img.mode else "RGB")
    out = io.BytesIO()
    out_img.save(out, format="WEBP", quality=quality, method=6, **_metadata(img, out_img, xmp=True))
    return out.getvalue()
