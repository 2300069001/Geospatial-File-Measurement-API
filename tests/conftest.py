import os
import tempfile
import zipfile
from pathlib import Path

# Keep the import-time default app away from the real data directory.
os.environ.setdefault("GEO_DATABASE_PATH", str(Path(tempfile.gettempdir()) / "geoapi_import_default.db"))

import geopandas as gpd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

KML_NS = '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>{body}</Document></kml>'


def make_kml(*placemarks: str) -> bytes:
    return KML_NS.format(body="".join(placemarks)).encode()


def placemark(name: str, geometry: str, extra: str = "") -> str:
    return f"<Placemark><name>{name}</name>{extra}{geometry}</Placemark>"


def polygon_kml(coords: str) -> str:
    return f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs></Polygon>"


# 0.01 x 0.01 degree square near Bangalore (~1.2 km x 1.1 km)
SQUARE_COORDS = "77.00,12.00,0 77.01,12.00,0 77.01,12.01,0 77.00,12.01,0 77.00,12.00,0"
LINE_COORDS = "77.0,12.0,0 77.0,13.0,0"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(database_path=tmp_path / "test.db", max_upload_bytes=1024 * 1024)


@pytest.fixture
def client(settings) -> TestClient:
    with TestClient(create_app(settings)) as c:
        yield c


def write_shapefile_zip(
    tmp_path: Path, geometries, crs="EPSG:4326", name="layer", drop_prj=False
) -> Path:
    gdf = gpd.GeoDataFrame({"name": [f"f{i}" for i in range(len(geometries))]}, geometry=list(geometries), crs=crs)
    shp_dir = tmp_path / f"shp_{name}"
    shp_dir.mkdir(exist_ok=True)
    gdf.to_file(shp_dir / f"{name}.shp")
    if drop_prj:
        (shp_dir / f"{name}.prj").unlink()
    zip_path = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in shp_dir.iterdir():
            zf.write(f, f.name)
    return zip_path


@pytest.fixture
def shapefile_zip(tmp_path):
    """Factory for a single-geometry-type Shapefile ZIP (Shapefiles cannot mix geometry types)."""

    def _make(geometries=None, **kwargs):
        geometries = geometries or [
            Polygon([(77, 12), (77.01, 12), (77.01, 12.01), (77, 12.01)]),
            Polygon([(78, 12), (78.01, 12), (78.01, 12.01), (78, 12.01)]),
        ]
        return write_shapefile_zip(tmp_path, geometries, **kwargs)

    return _make


def upload(client, filename: str, content: bytes, content_type="application/octet-stream"):
    return client.post("/api/files/", files={"file": (filename, content, content_type)})
