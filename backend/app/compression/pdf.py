"""Real PDF optimization using pikepdf (qpdf bindings). Lossless and structural
only: every stream is (re)compressed with Flate, small objects are packed into
compressed object streams, and objects nothing refers to (leftovers from
earlier edits) aren't written. Images, fonts and text are never re-encoded,
and identical objects aren't merged."""
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
