"""Reads geospatial source files into a uniform dataset (CRS + features)."""

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS

from app.core.exceptions import (
    EmptyDatasetError,
    InvalidShapefileError,
    MissingCRSError,
    TooManyFeaturesError,
)
from app.domain.models import ParsedFeature
from app.services.kml_parser import parse_kml

logger = logging.getLogger(__name__)

WGS84 = CRS.from_epsg(4326)


@dataclass(frozen=True)
class Dataset:
    crs: CRS
    features: list[ParsedFeature]


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)


class GeospatialService:
    def __init__(self, max_features: int) -> None:
        self._max_features = max_features

    def read_kml(self, path: Path) -> Dataset:
        features = parse_kml(path)
        self._check_count(len(features))
        return Dataset(crs=WGS84, features=features)

    def read_shapefile(self, shp_path: Path) -> Dataset:
        if not shp_path.with_suffix(".prj").exists():
            raise MissingCRSError()
        try:
            gdf = gpd.read_file(shp_path, engine="pyogrio")
        except Exception as exc:  # noqa: BLE001 - GDAL raises assorted types
            logger.warning("Shapefile read failed: %s", exc)
            raise InvalidShapefileError() from None

        if gdf.crs is None:
            raise MissingCRSError()
        self._check_count(len(gdf))

        geom_col = gdf.geometry.name
        attributes = gdf.drop(columns=geom_col).to_dict(orient="records")
        features = [
            ParsedFeature(
                index=i,
                geometry=geom if geom is not None else None,
                properties={k: _json_safe(v) for k, v in attributes[i].items()},
            )
            for i, geom in enumerate(gdf.geometry)
        ]
        return Dataset(crs=CRS.from_user_input(gdf.crs), features=features)

    def _check_count(self, count: int) -> None:
        if count == 0:
            raise EmptyDatasetError()
        if count > self._max_features:
            raise TooManyFeaturesError(f"The file contains {count} features; the limit is {self._max_features}.")
