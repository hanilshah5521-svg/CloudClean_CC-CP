"""ZIP archival for files/groups that can't be meaningfully compressed
directly. Only ever creates archives (never extracts untrusted zips), so
zip-slip protection is not a concern here — but filenames are still
sanitized before being used as archive entry names."""
import io
import re
import zipfile


def safe_entry_name(name: str) -> str:
    name = name.replace("\\", "_").replace("/", "_")
    name = re.sub(r"[\x00-\x1f]", "", name)
    return name.lstrip("./") or "file"


def create_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """entries: list of (filename, content_bytes)."""
    out = io.BytesIO()
    seen: dict[str, int] = {}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, content in entries:
            safe = safe_entry_name(name)
            if safe in seen:
                seen[safe] += 1
                stem, _, ext = safe.rpartition(".")
                safe = f"{stem or safe}_{seen[safe]}" + (f".{ext}" if ext else "")
            else:
                seen[safe] = 0
            zf.writestr(safe, content)
    return out.getvalue()
