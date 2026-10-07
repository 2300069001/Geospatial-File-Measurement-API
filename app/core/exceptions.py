"""Domain exceptions mapped to clean JSON error responses."""

from typing import Any


class AppError(Exception):
    """Base class for all errors that are safe to show to API clients."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)


class EmptyFileError(AppError):
    status_code = 400
    code = "EMPTY_FILE"
    default_message = "The uploaded file is empty."


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "UNSUPPORTED_FILE_TYPE"
    default_message = "Unsupported file type. Upload a .kml file or a .zip containing a Shapefile."


class FileTooLargeError(AppError):
    status_code = 413
    code = "FILE_TOO_LARGE"
    default_message = "The uploaded file exceeds the maximum allowed size."


class InvalidKMLError(AppError):
    status_code = 422
    code = "INVALID_KML"
    default_message = "The uploaded file is not a valid KML document."


class InvalidZipError(AppError):
    status_code = 422
    code = "INVALID_ZIP"
    default_message = "The uploaded file is not a valid ZIP archive."


class UnsafeArchiveError(AppError):
    status_code = 422
    code = "UNSAFE_ARCHIVE"
    default_message = "The ZIP archive was rejected because it is unsafe."


class ShapefileNotFoundError(AppError):
    status_code = 422
    code = "SHAPEFILE_NOT_FOUND"
    default_message = "The ZIP archive does not contain a Shapefile (.shp, .shx and .dbf)."


class InvalidShapefileError(AppError):
    status_code = 422
    code = "INVALID_SHAPEFILE"
    default_message = "The Shapefile could not be read."


class MissingCRSError(AppError):
    status_code = 422
    code = "MISSING_CRS"
    default_message = (
        "The dataset has no coordinate reference system (CRS). "
        "Measurements cannot be computed safely without one."
    )


class UnsupportedCRSError(AppError):
    status_code = 422
    code = "UNSUPPORTED_CRS"
    default_message = "The dataset CRS is not supported for measurements."


class EmptyDatasetError(AppError):
    status_code = 422
    code = "EMPTY_DATASET"
    default_message = "The file does not contain any features."


class TooManyFeaturesError(AppError):
    status_code = 413
    code = "TOO_MANY_FEATURES"
    default_message = "The file contains more features than the allowed maximum."


class FileRecordNotFoundError(AppError):
    status_code = 404
    code = "FILE_NOT_FOUND"
    default_message = "No file exists with the given id."


class ProcessingError(AppError):
    status_code = 500
    code = "PROCESSING_FAILED"
    default_message = "The file could not be processed."
