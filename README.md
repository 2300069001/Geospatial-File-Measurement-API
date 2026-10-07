# Geospatial File Measurement API

A FastAPI backend that accepts **KML** files and **ZIP archives containing a Shapefile**, extracts every feature, and returns CRS-correct **area** (polygons) and **length** (lines) measurements through a small REST API.

## 1. Project overview

Upload a file, the service parses it, validates every geometry, picks a suitable *projected* CRS for each feature, measures it, and stores the result in SQLite. Two read endpoints then expose the file metadata and the per-feature measurements.

The critical rule of the project: **area and length are never computed on latitude/longitude degrees.** Geometries are always projected into a metric (or linear-unit-normalised) CRS first.

## 2. Features

- `POST /api/files/` – upload `.kml` or `.zip` (Shapefile), synchronous processing
- `GET /api/files/{id}/` – file info (feature count, CRS, status, geometry-type summary)
- `GET /api/files/{id}/measurements/` – per-feature measurements, paginated, optional GeoJSON geometry
- Automatic projected-CRS selection (UTM / UPS / equal-area / equidistant fallbacks)
- Per-feature fault isolation: one bad geometry never fails the whole file
- Hardened uploads: size limit, extension + content validation, safe ZIP extraction, XML DTD/entity rejection
- Uniform JSON error envelope; no stack traces or filesystem paths leak to clients
- Swagger UI and ReDoc, Docker image, 69 automated tests

## 3. Technology stack

Python 3.11+, FastAPI, Uvicorn, GeoPandas (+ pyogrio/GDAL for Shapefiles), Shapely 2, PyProj, Pydantic v2 / pydantic-settings, SQLite (stdlib `sqlite3`), Pytest + httpx.

## 4. Architecture

```text
geospatial-file-api/
├── app/
│   ├── main.py                   # app factory, wiring (composition root)
│   ├── api/
│   │   ├── deps.py               # FastAPI dependencies
│   │   └── routes/files.py       # HTTP layer only: validation + response mapping
│   ├── core/
│   │   ├── config.py             # Settings (env vars, GEO_ prefix)
│   │   ├── exceptions.py         # AppError hierarchy (status code + stable error code)
│   │   └── error_handlers.py     # uniform JSON error envelope
│   ├── domain/models.py          # framework-free dataclasses and enums
│   ├── schemas/file.py           # Pydantic request/response models
│   ├── repositories/file_repository.py   # SQLite persistence
│   ├── services/
│   │   ├── file_service.py       # use-case orchestration: upload → parse → measure → store
│   │   ├── geospatial_service.py # reads KML / Shapefile into a uniform Dataset
│   │   ├── kml_parser.py         # safe stdlib KML parser
│   │   ├── crs_service.py        # projected-CRS selection and reprojection
│   │   └── measurement_service.py# area / length + feature-level status
│   └── utils/file_utils.py       # filename sanitising, size-limited streaming, safe ZIP extraction
├── tests/                        # test_upload.py, test_measurements.py, test_crs.py, conftest.py
├── sample_data/                  # survey.kml, plots_shapefile.zip
├── scripts/generate_sample_data.py
├── requirements.txt / requirements-dev.txt
├── Dockerfile, .dockerignore, .gitignore, pytest.ini, .env.example
```

Dependencies point inward: routes → `FileService` → (`GeospatialService`, `MeasurementService`, `FileRepository`) → domain models. Services contain no FastAPI types except the upload handle in `FileService`; `MeasurementService` and `CRSService` are pure and unit-tested in isolation.

## 5. Installation

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt     # or requirements.txt for runtime only
```

GeoPandas, Shapely, PyProj and pyogrio ship binary wheels, so no system GDAL is needed.

## 6. Environment setup

All settings are optional and read from environment variables (or a `.env` file – see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `GEO_DATABASE_PATH` | `data/geospatial.db` | SQLite file (directory auto-created) |
| `GEO_MAX_UPLOAD_BYTES` | 52428800 (50 MB) | Max upload size |
| `GEO_MAX_ZIP_ENTRIES` | 200 | Max entries in a ZIP |
| `GEO_MAX_ZIP_UNCOMPRESSED_BYTES` | 209715200 (200 MB) | Max total extracted size (ZIP-bomb guard) |
| `GEO_MAX_FEATURES` | 100000 | Max features per file |
| `GEO_DEFAULT_PAGE_SIZE` / `GEO_MAX_PAGE_SIZE` | 1000 / 10000 | Measurement pagination |

## 7. Running locally

```bash
uvicorn app.main:app --reload
```

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- OpenAPI JSON: <http://localhost:8000/openapi.json>
- Health probe: <http://localhost:8000/health>

## 8. API documentation

| Method | Path | Success | Description |
|---|---|---|---|
| POST | `/api/files/` | 201 | multipart field `file` (`.kml` or `.zip`) |
| GET | `/api/files/{id}/` | 200 | file information |
| GET | `/api/files/{id}/measurements/` | 200 | query: `limit` (≥1), `offset` (≥0), `include_geometry` (bool) |

`feature_id` is the zero-based index of the feature in the source file. Every feature reports: `geometry_type`, `crs` (source CRS), `measurement_type` (`AREA`/`LENGTH`/`NONE`), `value`, `unit` (`square_meters`/`meters`), `supported`, `status`, `message`, `calculation_crs`, `properties`, and (on request) the GeoJSON `geometry`.

Feature `status` values:

| Status | Meaning | `supported` |
|---|---|---|
| `MEASURED` | area/length computed | true |
| `NOT_APPLICABLE` | Point / MultiPoint – nothing to measure | true |
| `UNSUPPORTED_GEOMETRY` | e.g. GeometryCollection, LinearRing | false |
| `INVALID_GEOMETRY` | empty, missing, malformed, self-intersecting, out-of-range coordinates | false |
| `MEASUREMENT_FAILED` | projection/calculation error (details only in server logs) | true |

## 9. Example requests

```bash
# Upload a KML
curl -F "file=@sample_data/survey.kml" http://localhost:8000/api/files/

# Upload a zipped Shapefile
curl -F "file=@sample_data/plots_shapefile.zip" http://localhost:8000/api/files/

# File info
curl http://localhost:8000/api/files/<id>/

# Measurements (page 1, with geometry)
curl "http://localhost:8000/api/files/<id>/measurements/?limit=100&offset=0&include_geometry=true"
```

## 10. Example responses

`POST /api/files/` → `201 Created`

```json
{
  "id": "d9534be8665e447595354b274dcc49d7",
  "filename": "survey.kml",
  "file_type": "KML",
  "size_bytes": 1048,
  "feature_count": 4,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "created_at": "2026-10-07T16:09:52.957265Z",
  "geometry_summary": {"Polygon": 2, "LineString": 1, "Point": 1}
}
```

`GET /api/files/{id}/measurements/` → `200 OK` (abridged; output from `sample_data/survey.kml`)

```json
{
  "file_id": "d9534be8665e447595354b274dcc49d7",
  "crs": "EPSG:4326",
  "total": 4, "limit": 1000, "offset": 0,
  "measurements": [
    {
      "feature_id": 0, "geometry_type": "Polygon", "crs": "EPSG:4326",
      "measurement_type": "AREA", "value": 1205141.191, "unit": "square_meters",
      "supported": true, "status": "MEASURED", "message": null,
      "calculation_crs": "EPSG:32643",
      "properties": {"name": "Plot A", "owner": "Asha"}, "geometry": null
    },
    {
      "feature_id": 1, "geometry_type": "LineString", "crs": "EPSG:4326",
      "measurement_type": "LENGTH", "value": 110646.7404, "unit": "meters",
      "supported": true, "status": "MEASURED", "calculation_crs": "EPSG:32643",
      "properties": {"name": "Access road"}, "geometry": null
    },
    {
      "feature_id": 2, "geometry_type": "Point", "crs": "EPSG:4326",
      "measurement_type": "NONE", "value": null, "unit": null,
      "supported": true, "status": "NOT_APPLICABLE",
      "message": "No measurement is defined for point geometries."
    },
    {
      "feature_id": 3, "geometry_type": "Polygon", "crs": "EPSG:4326",
      "measurement_type": "NONE", "value": null, "unit": null,
      "supported": false, "status": "INVALID_GEOMETRY",
      "message": "Invalid geometry: Self-intersection[77.005 12.005]"
    }
  ]
}
```

Error → e.g. `422 Unprocessable Entity`

```json
{ "error": { "code": "MISSING_CRS", "message": "The dataset has no coordinate reference system (CRS). Measurements cannot be computed safely without one." } }
```

## 11. CRS strategy

The source CRS is taken from the file: KML is always WGS84 (`EPSG:4326`) per the KML spec; Shapefiles use their `.prj`. For **each feature**, `CRSService.plan()` decides where to measure:

1. **Source is projected** (UTM, State Plane, national grids…) → measure in the source CRS, converting its linear unit to metres (e.g. US survey feet → m, area × factor²).
   - Exception: **Mercator-family CRSs (incl. EPSG:3857 Web Mercator)** inflate area by ≈1/cos²(lat), so they are treated like geographic data and reprojected as below.
2. **Source is geographic** (or Mercator) → compute the feature's lon/lat bounding box, then:
   - centre latitude ≥ 84°N / ≤ 80°S → **UPS** (EPSG:5041 / 5042)
   - whole feature inside a single 6° zone → **UTM zone of the feature** (EPSG:326xx north / 327xx south)
   - feature spans several zones → a custom projection centred on the feature: **Lambert Azimuthal Equal-Area** for area, **Azimuthal Equidistant** for length. Features crossing the antimeridian are centred on the shorter arc.
3. Z values are dropped before measuring (2D measurements).

Selection is per feature, so a file covering several UTM zones still gets a good projection for each feature. The chosen CRS is returned as `calculation_crs`. Unsupported setups (no CRS, non-degree geographic units, engineering/local CRS) fail cleanly: a missing CRS rejects the upload (`MISSING_CRS`); other CRS problems mark the affected features `MEASUREMENT_FAILED`.

## 12. Measurement methodology

- Polygon / MultiPolygon → projected planar area, holes subtracted → `square_meters`
- LineString / MultiLineString → projected length (sum of parts) → `meters`
- Point / MultiPoint → no measurement (`NOT_APPLICABLE`)
- Everything else → `UNSUPPORTED_GEOMETRY`
- Before measuring, geometries must be non-empty, finite, inside valid lon/lat range (if geographic) and pass Shapely validity. **Invalid geometries are reported, not silently repaired**, because repair (`make_valid`) changes areas.
- Values are rounded to 4 decimals.

Accuracy: UTM scale error is ≤ 0.1 % within a zone (≤ 0.04 % near the central meridian). Tests compare results against PROJ's ellipsoidal geodesic calculations (`pyproj.Geod`) with 0.5 % tolerance. Edges are straight lines in the projected plane (the usual GIS convention), which differs slightly from geodesic edges for very large (≈1000 km+) polygons.

## 13. Error handling

All errors share one shape: `{"error": {"code", "message", "details?"}}`. Unexpected exceptions are logged server-side and returned as a generic `500 INTERNAL_ERROR`/`PROCESSING_FAILED`.

| Situation | HTTP | `code` |
|---|---|---|
| Empty file | 400 | `EMPTY_FILE` |
| File too large | 413 | `FILE_TOO_LARGE` |
| Too many features | 413 | `TOO_MANY_FEATURES` |
| Unsupported extension | 415 | `UNSUPPORTED_FILE_TYPE` |
| Invalid / non-KML XML, DTD present | 422 | `INVALID_KML` |
| Not a ZIP | 422 | `INVALID_ZIP` |
| Unsafe ZIP (traversal, symlink, bomb, encrypted, too many entries) | 422 | `UNSAFE_ARCHIVE` |
| ZIP without (or with several / incomplete) Shapefile | 422 | `SHAPEFILE_NOT_FOUND` |
| Unreadable Shapefile | 422 | `INVALID_SHAPEFILE` |
| Missing CRS | 422 | `MISSING_CRS` |
| No features | 422 | `EMPTY_DATASET` |
| Missing `file` field / bad query params | 422 | `VALIDATION_ERROR` |
| Unknown file id | 404 | `FILE_NOT_FOUND` |
| Processing failure | 500 | `PROCESSING_FAILED` |

Feature-level problems (invalid / unsupported geometry, measurement failure) do **not** fail the request; they appear in the measurements list.

## 14. Security considerations

- Upload streamed in 1 MB chunks and aborted at `GEO_MAX_UPLOAD_BYTES`
- Filename sanitised (no directories, control or special characters); user filenames are never used on disk – files are saved as `upload.kml|zip` in a private temp directory removed after every request (also on failure)
- Extension whitelist (`.kml`, `.zip`) plus content validation (real ZIP, real KML)
- ZIP extraction: rejects absolute paths, `..`, drive letters, NUL bytes, symlinks, encrypted entries, too many entries; extracts only Shapefile component types, flattened to sanitised names; the uncompressed-size limit is enforced **while streaming**, so forged headers can't bypass it
- KML parsed with a non-executing XML parser; any DTD/entity declaration is rejected (XXE / billion-laughs)
- Uploaded content is never executed or imported; error messages never include filesystem paths or tracebacks
- Container runs as a non-root user

Not included (out of scope for this assessment): authentication, rate limiting, antivirus scanning, upload quotas per client. Put the service behind an API gateway for those.

## 15. Testing

```bash
pytest
```

69 tests cover KML and Shapefile upload, invalid/empty/oversized/unsupported files, ZIP attacks (traversal, absolute path, bomb, entry count), missing CRS, polygon area and line length against geodesic references, point handling, holes and multipolygons, invalid/unsupported geometry, measurement-failure containment, CRS selection (UTM zones, polar, multi-zone, antimeridian, feet units, Web Mercator), 404s, pagination, and OpenAPI/Swagger/ReDoc availability.

## 16. Docker usage

```bash
docker build -t geospatial-file-api .
docker run --rm -p 8000:8000 -v geo-data:/data geospatial-file-api
```

The SQLite database lives in the `/data` volume. Override limits with `-e GEO_MAX_UPLOAD_BYTES=...`. A `HEALTHCHECK` calls `/health`.

## 17. Design decisions

- **Own KML parser** instead of GDAL's KML driver: GDAL's driver availability varies per wheel, and a small parser gives full control over XXE protection and `ExtendedData`.
- **Per-feature CRS plan**, not per-file: correct for files spanning multiple UTM zones.
- **Mercator is never used for measuring**, even when the file says so.
- **Invalid geometries are flagged, not repaired**, to avoid silently changing results.
- **Missing CRS rejects the upload** (422) rather than guessing WGS84 – a wrong guess produces plausible but wrong numbers.
- **One Shapefile per ZIP**; several layers would have different CRS/schemas and an ambiguous `feature_id`.
- **Synchronous processing** (CPU work runs in the thread pool so the event loop stays free). Status is therefore always `COMPLETED` for stored files; failed uploads are rejected, not stored. Switching to background jobs would only need a `PROCESSING` state and a worker.
- **SQLite with a repository class** keeps the stack simple and is replaceable; features are stored with their measurements so reads are cheap and repeatable.
- **App factory** (`create_app(settings)`) makes tests hermetic.

## 18. Learning outcomes

- Why degrees can't be used for area/length and how UTM, equal-area and equidistant projections trade off distortion
- Mercator's area inflation and why "projected" does not automatically mean "safe to measure in"
- Handling linear units other than metres
- Defensive file handling: ZIP slip, ZIP bombs, XXE, streaming size limits
- Fault-isolating batch processing so one bad record doesn't fail a job
- Layered FastAPI design with a uniform error contract and testable services

## 19. Future improvements

- Background processing with job status and progress for large files
- KMZ and GeoJSON support; multi-layer Shapefiles/GeoPackage
- Optional geodesic (ellipsoidal) measurement mode and perimeter output
- Opt-in geometry repair with a `REPAIRED` status
- Authentication, per-client quotas, rate limiting, object storage for originals
- PostgreSQL/PostGIS backend, DB migrations, file deletion/retention endpoints
- Structured logging and metrics
