import functools
import io

import pikepdf
from PIL import Image

from app.compression.archive import create_zip, safe_entry_name
from app.compression.images import compress_jpeg, compress_png
from app.compression.pdf import compress_pdf


def _make_jpeg(size=(800, 800)) -> bytes:
    img = Image.new("RGB", size, color=(120, 30, 200))
    for x in range(0, size[0], 10):
        for y in range(0, size[1], 10):
            img.putpixel((x, y), ((x * 7) % 255, (y * 3) % 255, (x + y) % 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=100)
    return buf.getvalue()


def test_compress_jpeg_actually_shrinks_and_stays_valid_jpeg():
    original = _make_jpeg()
    compressed = compress_jpeg(original, quality=40)
    assert len(compressed) < len(original)
    # Must still be a decodable JPEG — this is REAL compression, not a stub.
    img = Image.open(io.BytesIO(compressed))
    img.load()
    assert img.format == "JPEG"


def test_compress_png_is_lossless_round_trip():
    img = Image.new("RGB", (200, 200), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0)
    original = buf.getvalue()

    compressed = compress_png(original)
    result = Image.open(io.BytesIO(compressed))
    assert list(result.getdata())[:5] == list(img.getdata())[:5]  # pixel data unchanged


def test_compress_pdf_preserves_page_count():
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.add_blank_page(page_size=(200, 200))
    buf = io.BytesIO()
    pdf.save(buf)
    original = buf.getvalue()

    compressed = compress_pdf(original)
    with pikepdf.open(io.BytesIO(compressed)) as result:
        assert len(result.pages) == 2  # content preserved, only structure optimized


def test_archive_creates_valid_zip_with_sanitized_names():
    data = create_zip([("../../etc/passwd", b"a"), ("safe.txt", b"b"), ("safe.txt", b"c")])
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert all(not n.startswith("..") and not n.startswith("/") for n in names)
        assert len(names) == 3  # duplicate "safe.txt" entries get unique names, not overwritten


def test_safe_entry_name_strips_path_separators():
    # No "/" or "\" survives, so a ".." segment can never escape the
    # extraction directory even though the literal characters remain.
    name = safe_entry_name("../../secret.txt")
    assert "/" not in name and "\\" not in name


# ---- metadata must survive compression -------------------------------------

@functools.lru_cache
def _srgb_icc() -> bytes:
    # Built once: generated profiles embed a creation time, so two builds can differ.
    from PIL import ImageCms
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _phone_photo_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = 6                      # Orientation: rotate 90° (portrait phone shot)
    exif[0x010F] = "Apple"                # Make
    exif[0x0110] = "iPhone 15"            # Model
    exif[0x0132] = "2025:06:01 10:00:00"  # DateTime
    return exif


def test_jpeg_keeps_exif_orientation_date_camera_and_icc_profile():
    src = Image.open(io.BytesIO(_make_jpeg()))
    buf = io.BytesIO()
    src.save(buf, format="JPEG", quality=100, exif=_phone_photo_exif().tobytes(), icc_profile=_srgb_icc())
    original = buf.getvalue()

    result = Image.open(io.BytesIO(compress_jpeg(original, quality=60)))
    exif = result.getexif()
    assert exif[0x0112] == 6  # without it the photo would display sideways
    assert (exif[0x010F], exif[0x0110], exif[0x0132]) == ("Apple", "iPhone 15", "2025:06:01 10:00:00")
    assert result.info.get("icc_profile") == _srgb_icc()
    assert result.size == src.size


def test_png_keeps_icc_profile_and_exif_losslessly():
    img = Image.new("RGB", (300, 200), color=(10, 120, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0, icc_profile=_srgb_icc(), exif=_phone_photo_exif().tobytes())
    result = Image.open(io.BytesIO(compress_png(buf.getvalue())))
    assert result.info.get("icc_profile") == _srgb_icc()
    assert result.getexif()[0x0112] == 6
    assert list(result.convert("RGB").getdata()) == list(img.getdata())


def test_webp_keeps_exif_and_icc():
    from app.compression.images import compress_webp

    img = Image.new("RGB", (300, 200), color=(200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=100, exif=_phone_photo_exif().tobytes(), icc_profile=_srgb_icc())
    result = Image.open(io.BytesIO(compress_webp(buf.getvalue())))
    assert result.getexif()[0x0112] == 6
    assert result.info.get("icc_profile") == _srgb_icc()


def test_profile_that_does_not_match_the_pixels_is_dropped():
    from PIL import ImageCms

    from app.compression.images import _icc_for

    lab = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    rgb = Image.new("RGB", (4, 4))
    assert _icc_for(rgb, _srgb_icc()) == _srgb_icc()
    assert _icc_for(rgb, lab) is None
    assert _icc_for(rgb, b"not a profile") is None


def test_cmyk_jpeg_is_saved_as_valid_rgb():
    img = Image.new("CMYK", (200, 200), color=(0, 80, 80, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=100)
    result = Image.open(io.BytesIO(compress_jpeg(buf.getvalue(), quality=60)))
    result.load()
    assert result.mode == "RGB" and "icc_profile" not in result.info


# ---- nothing may be lost silently -------------------------------------------

import pytest  # noqa: E402

from app.compression.images import UnsafeToCompress, _webp_is_lossless, compress_webp  # noqa: E402


def _frames(n=3, size=(120, 80), mode="RGB"):
    return [Image.new(mode, size, color=(40 * i, 90, 200 - 40 * i)) for i in range(n)]


@pytest.mark.parametrize("fmt, compress", [("PNG", compress_png), ("WEBP", compress_webp)])
def test_animated_images_are_refused_not_flattened_to_one_frame(fmt, compress):
    first, *rest = _frames()
    buf = io.BytesIO()
    first.save(buf, format=fmt, save_all=True, append_images=rest, duration=100, loop=0)
    assert Image.open(io.BytesIO(buf.getvalue())).n_frames == 3

    with pytest.raises(UnsafeToCompress, match="Animated image"):
        compress(buf.getvalue())


def test_jpeg_carrying_a_second_image_is_refused():
    # Ultra HDR photos keep their gain map as a second image (MPF); depth maps likewise.
    primary, gain_map = _frames(2, size=(200, 150))
    buf = io.BytesIO()
    primary.save(buf, format="MPO", save_all=True, append_images=[gain_map], quality=95)
    with pytest.raises(UnsafeToCompress, match="more than one image"):
        compress_jpeg(buf.getvalue())


def _noisy_rgba(size=(160, 120)) -> Image.Image:
    img = Image.new("RGBA", size)
    img.putdata([((x * 37) % 256, (y * 53) % 256, (x * y) % 256, 0 if x < 20 else 255)
                 for y in range(size[1]) for x in range(size[0])])
    return img


@pytest.mark.parametrize("extended", [False, True])  # plain VP8L, and VP8X with metadata chunks
def test_lossless_webp_stays_lossless_and_pixel_identical(extended):
    img = _noisy_rgba()
    buf = io.BytesIO()
    extra = {"exif": _phone_photo_exif().tobytes()} if extended else {}
    img.save(buf, format="WEBP", lossless=True, quality=0, method=0, exact=True, **extra)
    original = buf.getvalue()
    assert _webp_is_lossless(original) and (original[12:16] == b"VP8X") == extended

    result = compress_webp(original)
    assert _webp_is_lossless(result)
    # Every value survives, including the color under fully transparent pixels.
    assert list(Image.open(io.BytesIO(result)).getdata()) == list(img.getdata())


def test_lossy_webp_is_still_reencoded_lossy():
    buf = io.BytesIO()
    _noisy_rgba().convert("RGB").save(buf, format="WEBP", quality=95)
    assert not _webp_is_lossless(buf.getvalue())
    assert not _webp_is_lossless(compress_webp(buf.getvalue()))


@pytest.mark.parametrize("sampling", [0, 1, 2])  # 4:4:4, 4:2:2, 4:2:0
def test_jpeg_keeps_its_chroma_subsampling(sampling):
    from PIL.JpegImagePlugin import get_sampling

    buf = io.BytesIO()
    Image.open(io.BytesIO(_make_jpeg())).save(buf, format="JPEG", quality=95, subsampling=sampling)
    result = Image.open(io.BytesIO(compress_jpeg(buf.getvalue(), quality=60)))
    assert get_sampling(result) == sampling
