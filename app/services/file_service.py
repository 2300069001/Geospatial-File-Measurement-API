"""Orchestrates upload -> parse -> measure -> persist."""

import logging
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from shapely.geometry import mapping

from app.core.config import Settings
from app.core.exceptions import (
    AppError,
    FileRecordNotFoundError,
    ProcessingError,
    UnsupportedFileTypeError,
)
from app.domain.models import FeatureRecord, FileRecord, FileStatus, FileType
from app.repositories.file_repository import FileRepository
from app.services.crs_service import describe_crs
from app.services.geospatial_service import Dataset, GeospatialService
from app.services.measurement_service import MeasurementService
from app.utils.file_utils import (
    get_extension,
    safe_extract_shapefile,
    sanitize_filename,
    stream_to_file,
)

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".kml": FileType.KML, ".zip": FileType.SHAPEFILE}


class FileService:
    def __init__(
        self,
        settings: Settings,
        repository: FileRepository,
        geospatial: GeospatialService,
        measurements: MeasurementService,
    ) -> None:
        self._settings = settings
        self._repo = repository
        self._geo = geospatial
        self._measure = measurements

    async def create_from_upload(self, upload: UploadFile) -> FileRecord:
        filename = sanitize_filename(upload.filename)
        file_type = ALLOWED_EXTENSIONS.get(get_extension(filename))
        if file_type is None:
            raise UnsupportedFileTypeError()

        with tempfile.TemporaryDirectory(prefix="geoapi_") as tmp:
            work_dir = Path(tmp)
            saved = work_dir / f"upload{get_extension(filename)}"
            size = await stream_to_file(upload, saved, self._settings.max_upload_bytes)
            try:
                return await run_in_threadpool(self._process, saved, work_dir, filename, file_type, size)
            except AppError:
                raise
            except Exception as exc:
                logger.error("Processing failed", exc_info=exc)
                raise ProcessingError() from None

    def get_file(self, file_id: str) -> FileRecord:
        record = self._repo.get(file_id)
        if record is None:
            raise FileRecordNotFoundError()
        return record

    def get_measurements(
        self, file_id: str, limit: int, offset: int
    ) -> tuple[FileRecord, list[FeatureRecord]]:
        record = self.get_file(file_id)
        return record, self._repo.list_features(file_id, limit, offset)

    # -- internals ---------------------------------------------------------------------------

    def _process(
        self, saved: Path, work_dir: Path, filename: str, file_type: FileType, size: int
    ) -> FileRecord:
        if file_type is FileType.KML:
            dataset = self._geo.read_kml(saved)
        else:
            extract_dir = work_dir / "extracted"
            extract_dir.mkdir()
            shp = safe_extract_shapefile(
                saved,
                extract_dir,
                max_entries=self._settings.max_zip_entries,
                max_total_bytes=self._settings.max_zip_uncompressed_bytes,
            )
            dataset = self._geo.read_shapefile(shp)

        features = self._measure_all(dataset)
        record = FileRecord(
            id=uuid.uuid4().hex,
            filename=filename,
            file_type=file_type,
            size_bytes=size,
            feature_count=len(features),
            crs=describe_crs(dataset.crs),
            status=FileStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
            geometry_summary=dict(Counter(f.geometry_type for f in features)),
        )
        self._repo.add(record, features)
        return record

    def _measure_all(self, dataset: Dataset) -> list[FeatureRecord]:
        records = []
        for feature in dataset.features:
            result = self._measure.measure(feature.geometry, dataset.crs, feature.geometry_error)
            geometry = (
                mapping(feature.geometry)
                if feature.geometry is not None and not feature.geometry.is_empty
                else None
            )
            records.append(
                FeatureRecord(
                    feature_id=feature.index,
                    geometry_type=result.geometry_type,
                    geometry=geometry,
                    properties=feature.properties,
                    measurement=result,
                )
            )
        return records
