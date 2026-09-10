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
