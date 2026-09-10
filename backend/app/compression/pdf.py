"""Real PDF optimization using pikepdf (qpdf bindings). Content is preserved;
only stream compression / duplicate-object dedup is applied."""
import io

import pikepdf


def compress_pdf(data: bytes) -> bytes:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        out = io.BytesIO()
        pdf.save(
            out,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
        return out.getvalue()
