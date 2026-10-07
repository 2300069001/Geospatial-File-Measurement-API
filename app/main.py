import logging

from fastapi import FastAPI

from app.api.routes import files
from app.core.config import Settings, get_settings
from app.core.error_handlers import register_error_handlers
from app.repositories.file_repository import FileRepository
from app.services.crs_service import CRSService
from app.services.file_service import FileService
from app.services.geospatial_service import GeospatialService
from app.services.measurement_service import MeasurementService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Upload KML or zipped Shapefiles and get CRS-correct area and length measurements.",
    )
    app.state.settings = settings
    app.state.file_service = FileService(
        settings=settings,
        repository=FileRepository(settings.database_path),
        geospatial=GeospatialService(settings.max_features),
        measurements=MeasurementService(CRSService()),
    )

    register_error_handlers(app)
    app.include_router(files.router)

    @app.get("/health", tags=["health"], summary="Liveness probe")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
