import io
import zipfile

from fastapi.testclient import TestClient
from shapely.geometry import Point

from app.core.config import Settings
from app.main import create_app
from tests.conftest import (
    LINE_COORDS,
    SQUARE_COORDS,
    make_kml,
    placemark,
    polygon_kml,
    upload,
    write_shapefile_zip,
)


def kml_sample() -> bytes:
    return make_kml(
        placemark("Plot A", polygon_kml(SQUARE_COORDS)),
        placemark("Road", f"<LineString><coordinates>{LINE_COORDS}</coordinates></LineString>"),
        placemark("Well", "<Point><coordinates>77.0,12.0,0</coordinates></Point>"),
    )


def zip_bytes(members: dict[str, bytes | str], compression=zipfile.ZIP_STORED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_upload_kml(client):
    r = upload(client, "survey.kml", kml_sample())
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "survey.kml"
    assert body["file_type"] == "KML"
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["status"] == "COMPLETED"
    assert body["geometry_summary"] == {"Polygon": 1, "LineString": 1, "Point": 1}
    assert len(body["id"]) == 32


def test_upload_shapefile_zip(client, shapefile_zip):
    r = upload(client, "layer.zip", shapefile_zip().read_bytes())
    assert r.status_code == 201
    body = r.json()
    assert body["file_type"] == "SHAPEFILE"
    assert body["feature_count"] == 2
    assert body["crs"] == "EPSG:4326"
    assert body["geometry_summary"] == {"Polygon": 2}


def test_get_file_roundtrip(client):
    file_id = upload(client, "survey.kml", kml_sample()).json()["id"]
    r = client.get(f"/api/files/{file_id}/")
    assert r.status_code == 200
    assert r.json()["id"] == file_id
    assert r.json()["feature_count"] == 3


def test_filename_is_sanitized(client):
    r = upload(client, "../../etc/pass wd<>.kml", kml_sample())
    assert r.status_code == 201
    name = r.json()["filename"]
    assert "/" not in name and ".." not in name and "<" not in name


def test_unsupported_extension(client):
    r = upload(client, "notes.txt", b"hello")
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_empty_file(client):
    r = upload(client, "empty.kml", b"")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "EMPTY_FILE"


def test_file_too_large(client):
    r = upload(client, "big.kml", b"x" * (1024 * 1024 + 1))
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_missing_file_field(client):
    r = client.post("/api/files/")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_kml(client):
    r = upload(client, "bad.kml", b"<kml><Document><Placemark></Document>")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_KML"


def test_non_kml_xml(client):
    r = upload(client, "other.kml", b"<html><body/></html>")
    assert r.json()["error"]["code"] == "INVALID_KML"


def test_kml_with_doctype_rejected(client):
    evil = b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY x "boom">]><kml><Document/></kml>'
    r = upload(client, "evil.kml", evil)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_KML"


def test_kml_without_features(client):
    r = upload(client, "none.kml", make_kml())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "EMPTY_DATASET"


def test_invalid_zip(client):
    r = upload(client, "bad.zip", b"this is not a zip")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_ZIP"


def test_zip_without_shapefile(client):
    r = upload(client, "nothing.zip", zip_bytes({"readme.txt": "no data here"}))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SHAPEFILE_NOT_FOUND"


def test_zip_with_incomplete_shapefile(client):
    r = upload(client, "partial.zip", zip_bytes({"a.shp": b"\x00" * 100}))
    assert r.json()["error"]["code"] == "SHAPEFILE_NOT_FOUND"


def test_corrupt_shapefile(client):
    members = {f"a.{ext}": b"garbage-garbage-garbage" for ext in ("shp", "shx", "dbf", "prj")}
    r = upload(client, "corrupt.zip", zip_bytes(members))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_SHAPEFILE"
    assert "Traceback" not in r.text


def test_zip_path_traversal_rejected(client):
    r = upload(client, "evil.zip", zip_bytes({"../../evil.shp": b"x"}))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSAFE_ARCHIVE"


def test_zip_absolute_path_rejected(client):
    r = upload(client, "abs.zip", zip_bytes({"/etc/evil.shp": b"x"}))
    assert r.json()["error"]["code"] == "UNSAFE_ARCHIVE"


def test_zip_bomb_rejected(tmp_path):
    settings = Settings(database_path=tmp_path / "t.db", max_zip_uncompressed_bytes=10_000)
    payload = zip_bytes({"a.shp": b"\x00" * 1_000_000}, zipfile.ZIP_DEFLATED)
    with TestClient(create_app(settings)) as c:
        r = upload(c, "bomb.zip", payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSAFE_ARCHIVE"


def test_zip_too_many_entries(tmp_path):
    settings = Settings(database_path=tmp_path / "t.db", max_zip_entries=3)
    payload = zip_bytes({f"f{i}.txt": "x" for i in range(5)})
    with TestClient(create_app(settings)) as c:
        assert upload(c, "many.zip", payload).json()["error"]["code"] == "UNSAFE_ARCHIVE"


def test_multiple_shapefiles_rejected(client, tmp_path):
    first = write_shapefile_zip(tmp_path, [Point(77, 12)], name="one")
    members = {}
    with zipfile.ZipFile(first) as src:
        for n in src.namelist():
            members[n] = src.read(n)
            members[n.replace("one", "two")] = src.read(n)
    r = upload(client, "two.zip", zip_bytes(members))
    assert r.json()["error"]["code"] == "SHAPEFILE_NOT_FOUND"


def test_shapefile_missing_crs(client, tmp_path):
    z = write_shapefile_zip(tmp_path, [Point(77, 12)], drop_prj=True)
    r = upload(client, "nocrs.zip", z.read_bytes())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "MISSING_CRS"


def test_shapefile_in_subdirectory_with_macosx_junk(client, tmp_path):
    z = write_shapefile_zip(tmp_path, [Point(77, 12)])
    members = {}
    with zipfile.ZipFile(z) as src:
        for n in src.namelist():
            members[f"data/{n}"] = src.read(n)
    members["__MACOSX/data/._layer.shp"] = b"junk"
    assert upload(client, "nested.zip", zip_bytes(members)).status_code == 201
