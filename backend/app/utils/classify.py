"""MIME-type-first file classification. Extension is only a fallback."""

MIME_CATEGORY_PREFIXES = {
    "image/": "images",
    "video/": "video",
    "audio/": "audio",
}

MIME_CATEGORY_EXACT = {
    "application/pdf": "pdf",
    "application/zip": "archives",
    "application/x-7z-compressed": "archives",
    "application/x-rar-compressed": "archives",
    "application/x-tar": "archives",
    "application/gzip": "archives",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "documents",
    "application/msword": "documents",
    "application/vnd.google-apps.document": "documents",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "spreadsheets",
    "application/vnd.ms-excel": "spreadsheets",
    "application/vnd.google-apps.spreadsheet": "spreadsheets",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "presentations",
    "application/vnd.ms-powerpoint": "presentations",
    "application/vnd.google-apps.presentation": "presentations",
    "application/vnd.google-apps.folder": "folder",
    "text/plain": "documents",
}

CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".go", ".rs", ".rb", ".php", ".html", ".css", ".json", ".yml", ".yaml", ".sh"}

ALREADY_COMPRESSED_EXT = {
    ".zip", ".rar", ".7z", ".gz", ".tar", ".mp4", ".mkv", ".mov", ".avi",
    ".mp3", ".aac", ".m4a", ".jpg", ".jpeg", ".webp", ".webm",
}

GOOGLE_WORKSPACE_PREFIX = "application/vnd.google-apps."


def classify(mime_type: str, extension: str) -> str:
    if mime_type in MIME_CATEGORY_EXACT:
        return MIME_CATEGORY_EXACT[mime_type]
    for prefix, category in MIME_CATEGORY_PREFIXES.items():
        if mime_type.startswith(prefix):
            return "images" if prefix == "image/" else category
    if extension.lower() in CODE_EXTENSIONS:
        return "code"
    return "other"


def is_google_workspace(mime_type: str) -> bool:
    return mime_type.startswith(GOOGLE_WORKSPACE_PREFIX)


def is_already_compressed(extension: str) -> bool:
    return extension.lower() in ALREADY_COMPRESSED_EXT


def extension_of(name: str) -> str:
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()
