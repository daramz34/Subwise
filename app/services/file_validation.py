"""Upload validation by CONTENT, not just by filename or the browser's claimed type.
Pure Python, no dependencies."""
import codecs
import os
from dataclasses import dataclass


class FileRejected(Exception):
    def __init__(self, message: str, status_code: int = 415):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedFile:
    file_type: str   # csv | pdf | image
    extension: str   # the extension WE choose to store under: csv, pdf, png, jpg
    media_type: str


# (starting bytes, file_type, extension, media_type)
SIGNATURES = [
    (b"%PDF-", "pdf", "pdf", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image", "png", "image/png"),
    (b"\xff\xd8\xff", "image", "jpg", "image/jpeg"),
]
ALLOWED_EXTENSIONS = {".csv": "csv", ".pdf": "pdf", ".png": "png", ".jpg": "jpg", ".jpeg": "jpg"}
UNSUPPORTED = "Unsupported file. Upload a CSV, PDF, PNG or JPG file."


def _human(n: int) -> str:
    return f"{n // (1024 * 1024)} MB" if n >= 1024 * 1024 else f"{n} bytes"


def _looks_like_text(content: bytes) -> bool:
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return True  # UTF-16 text legitimately contains NUL bytes
    sample = content[:8192]
    if b"\x00" in sample:
        return False
    control = sum(1 for b in sample if b < 32 and b not in (9, 10, 13))
    return control <= len(sample) * 0.05


def validate_upload(filename: str | None, content: bytes, max_bytes: int) -> ValidatedFile:
    if not content:
        raise FileRejected("The file is empty.", 400)
    if len(content) > max_bytes:
        raise FileRejected(f"The file is too large (limit {_human(max_bytes)}).", 413)

    extension = os.path.splitext(filename or "")[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise FileRejected(UNSUPPORTED)
    expected = ALLOWED_EXTENSIONS[extension]

    matched = next((s for s in SIGNATURES if content.startswith(s[0])), None)

    if expected == "csv":
        if matched is not None or not _looks_like_text(content):
            raise FileRejected("This doesn't look like a CSV text file.")
        return ValidatedFile("csv", "csv", "text/csv")

    if matched is None or matched[2] != expected:
        raise FileRejected("The file's contents don't match its extension.")
    _, file_type, ext, media_type = matched
    return ValidatedFile(file_type, ext, media_type)