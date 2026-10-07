"""Secure upload helpers: filename sanitization, size-limited streaming, safe ZIP extraction."""

import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.core.exceptions import (
    EmptyFileError,
    FileTooLargeError,
    InvalidZipError,
    ShapefileNotFoundError,
    UnsafeArchiveError,
)

CHUNK_SIZE = 1024 * 1024
SHAPEFILE_COMPONENT_EXTENSIONS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}
REQUIRED_SHAPEFILE_EXTENSIONS = {".shp", ".shx", ".dbf"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


class _AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


def sanitize_filename(name: str | None, default: str = "upload") -> str:
    """Return a safe base name: no directories, no control or special characters."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].replace("\x00", "")
    base = _SAFE_NAME.sub("_", base).lstrip(".")
    return base[:100] or default


def get_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


async def stream_to_file(source: _AsyncReadable, dest: Path, max_bytes: int) -> int:
    """Copy an upload to `dest`, aborting as soon as `max_bytes` is exceeded."""
    total = 0
    with dest.open("wb") as out:
        while chunk := await source.read(CHUNK_SIZE):
            total += len(chunk)
            if total > max_bytes:
                raise FileTooLargeError(
                    f"The uploaded file exceeds the {max_bytes // (1024 * 1024)} MB limit."
                )
            out.write(chunk)
    if total == 0:
        raise EmptyFileError()
    return total


def _validate_member_name(raw_name: str) -> PurePosixPath:
    if "\x00" in raw_name:
        raise UnsafeArchiveError()
    name = raw_name.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", name) or ".." in path.parts:
        raise UnsafeArchiveError("The ZIP archive contains an unsafe path.")
    return path


def safe_extract_shapefile(
    zip_path: Path, dest_dir: Path, *, max_entries: int, max_total_bytes: int
) -> Path:
    """Extract only Shapefile components, flattened into `dest_dir`; return the `.shp` path.

    Protects against path traversal, absolute paths, symlinks, encrypted members, ZIP bombs
    (enforced while streaming, not just from declared sizes) and filename collisions.
    """
    if not zipfile.is_zipfile(zip_path):
        raise InvalidZipError()

    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()
            if len(members) > max_entries:
                raise UnsafeArchiveError("The ZIP archive contains too many entries.")

            extracted: dict[str, Path] = {}
            total = 0
            for info in members:
                path = _validate_member_name(info.filename)
                if info.is_dir() or path.parts[0] == "__MACOSX" or path.name.startswith("._"):
                    continue
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise UnsafeArchiveError("The ZIP archive contains symbolic links.")
                if info.flag_bits & 0x1:
                    raise UnsafeArchiveError("Encrypted ZIP archives are not supported.")
                suffix = path.suffix.lower()
                if suffix not in SHAPEFILE_COMPONENT_EXTENSIONS:
                    continue

                target_name = sanitize_filename(path.stem) + suffix
                if target_name in extracted:
                    raise UnsafeArchiveError("The ZIP archive contains duplicate file names.")
                target = dest_dir / target_name
                with archive.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(CHUNK_SIZE):
                        total += len(chunk)
                        if total > max_total_bytes:
                            raise UnsafeArchiveError("The ZIP archive expands beyond the size limit.")
                        out.write(chunk)
                extracted[target_name] = target
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, EOFError):
        raise InvalidZipError() from None

    shapefiles = sorted(p for name, p in extracted.items() if name.endswith(".shp"))
    if not shapefiles:
        raise ShapefileNotFoundError()
    if len(shapefiles) > 1:
        raise ShapefileNotFoundError("The ZIP archive contains more than one Shapefile; upload one per archive.")

    shp = shapefiles[0]
    missing = [ext for ext in REQUIRED_SHAPEFILE_EXTENSIONS if shp.with_suffix(ext).name not in extracted]
    if missing:
        raise ShapefileNotFoundError(
            f"The Shapefile is incomplete; missing component(s): {', '.join(sorted(missing))}."
        )
    return shp
