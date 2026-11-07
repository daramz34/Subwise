"""Saves uploaded files to disk. Files are named from IDs WE generate, never from the
client's filename, so a name like '../../x' can never choose where a file lands."""
import uuid
from pathlib import Path

from app.core.config import settings

ALLOWED_EXTENSIONS = {"csv", "pdf", "png", "jpg"}


def _root() -> Path:
    return Path(settings.UPLOAD_DIR).resolve()


def _inside_root(path: Path) -> Path:
    resolved = path.resolve()
    if _root() not in resolved.parents:
        raise ValueError("Path escapes the upload directory")
    return resolved


def save_upload(user_id: uuid.UUID, job_id: uuid.UUID, extension: str, content: bytes) -> str:
    extension = extension.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported extension")
    relative = Path(str(user_id)) / f"{job_id}.{extension}"
    target = _inside_root(_root() / relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return relative.as_posix()


def read_upload(storage_path: str) -> bytes:
    return _inside_root(_root() / storage_path).read_bytes()


def delete_upload(storage_path: str) -> None:
    _inside_root(_root() / storage_path).unlink(missing_ok=True)