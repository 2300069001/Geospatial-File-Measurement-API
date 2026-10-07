"""SQLite persistence for uploaded files and their processed features."""

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.domain.models import (
    FeatureRecord,
    FileRecord,
    FileStatus,
    FileType,
    MeasurementResult,
    MeasurementStatus,
    MeasurementType,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    feature_count INTEGER NOT NULL,
    crs TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    geometry_summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS features (
    file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    feature_id INTEGER NOT NULL,
    geometry_type TEXT NOT NULL,
    geometry TEXT,
    properties TEXT NOT NULL,
    measurement_type TEXT NOT NULL,
    value REAL,
    unit TEXT,
    supported INTEGER NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    calculation_crs TEXT,
    PRIMARY KEY (file_id, feature_id)
);
"""


class FileRepository:
    def __init__(self, database_path: Path) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._path, timeout=30)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:  # commit / rollback
                yield conn

    def add(self, record: FileRecord, features: list[FeatureRecord]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.filename,
                    record.file_type.value,
                    record.size_bytes,
                    record.feature_count,
                    record.crs,
                    record.status.value,
                    record.created_at.isoformat(),
                    json.dumps(record.geometry_summary),
                ),
            )
            conn.executemany(
                "INSERT INTO features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        record.id,
                        f.feature_id,
                        f.geometry_type,
                        json.dumps(f.geometry) if f.geometry is not None else None,
                        json.dumps(f.properties),
                        f.measurement.measurement_type.value,
                        f.measurement.value,
                        f.measurement.unit,
                        int(f.measurement.supported),
                        f.measurement.status.value,
                        f.measurement.message,
                        f.measurement.calculation_crs,
                    )
                    for f in features
                ],
            )

    def get(self, file_id: str) -> FileRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            return None
        return FileRecord(
            id=row[0],
            filename=row[1],
            file_type=FileType(row[2]),
            size_bytes=row[3],
            feature_count=row[4],
            crs=row[5],
            status=FileStatus(row[6]),
            created_at=datetime.fromisoformat(row[7]),
            geometry_summary=json.loads(row[8]),
        )

    def list_features(self, file_id: str, limit: int, offset: int) -> list[FeatureRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT feature_id, geometry_type, geometry, properties, measurement_type, value, "
                "unit, supported, status, message, calculation_crs FROM features "
                "WHERE file_id = ? ORDER BY feature_id LIMIT ? OFFSET ?",
                (file_id, limit, offset),
            ).fetchall()
        return [
            FeatureRecord(
                feature_id=r[0],
                geometry_type=r[1],
                geometry=json.loads(r[2]) if r[2] else None,
                properties=json.loads(r[3]),
                measurement=MeasurementResult(
                    geometry_type=r[1],
                    measurement_type=MeasurementType(r[4]),
                    value=r[5],
                    unit=r[6],
                    supported=bool(r[7]),
                    status=MeasurementStatus(r[8]),
                    message=r[9],
                    calculation_crs=r[10],
                ),
            )
            for r in rows
        ]
