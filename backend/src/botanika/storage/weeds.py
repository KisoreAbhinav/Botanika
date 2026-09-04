"""Non-image persistence for the independent weed beta."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import time
import uuid
from typing import Any, Iterable

from .database import SQLiteDatabase


NO_POSITION_MESSAGE = "Exact location could not be found. Coordinate collection was skipped."


@dataclass(frozen=True, slots=True)
class WeedRunRecord:
    run_id: str
    observed_at: float
    detector_version: str
    crop_context: str
    position_available: bool
    position_message: str
    detections: tuple[dict[str, Any], ...]
    model_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "observed_at": self.observed_at,
            "detector_version": self.detector_version,
            "crop_context": self.crop_context,
            "position_available": self.position_available,
            "position_message": self.position_message,
            "detections": [dict(item) for item in self.detections],
            "model_metadata": dict(self.model_metadata),
            "image_persisted": False,
        }


class WeedObservationStore:
    """Store only coordinate observations and detector metadata, never pixels."""

    def __init__(self, database: SQLiteDatabase | None = None, *, database_path=None, clock=time.time, max_accuracy_m: float = 100.0) -> None:
        if database is None and database_path is None:
            raise ValueError("database or database_path is required")
        self.database = database or SQLiteDatabase(database_path)
        self._owns_database = database is None
        self._clock = clock
        self.max_accuracy_m = float(max_accuracy_m)
        if not math.isfinite(self.max_accuracy_m) or self.max_accuracy_m <= 0:
            raise ValueError("max_accuracy_m must be a positive number")

    def save_run(
        self,
        detections: Iterable[Any],
        *,
        detector_version: str,
        crop_context: str,
        model_metadata: dict[str, Any] | None = None,
        position: dict[str, Any] | None = None,
        observed_at: float | None = None,
    ) -> WeedRunRecord:
        observed = self._clock() if observed_at is None else float(observed_at)
        if not math.isfinite(observed) or observed < 0:
            raise ValueError("observed_at must be a finite non-negative timestamp")
        normalized_position = _normalize_position(position, maximum_accuracy=self.max_accuracy_m)
        detection_values = tuple(detections)
        # Validate before any write. A no-position or empty-detection call is
        # still a successful inference result, but it is not a persistent weed
        # run. The empty ID makes that boundary explicit to direct callers.
        if normalized_position is None or not detection_values:
            return WeedRunRecord(
                run_id="",
                observed_at=observed,
                detector_version=str(detector_version),
                crop_context=str(crop_context),
                position_available=False,
                position_message=NO_POSITION_MESSAGE,
                detections=tuple(_detection_dict(item) for item in detection_values),
                model_metadata=dict(model_metadata or {}),
            )
        position_available = True
        message = "Coordinate recorded with the weed observation."
        run_id = uuid.uuid4().hex
        metadata = json.dumps(model_metadata or {}, sort_keys=True)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO weed_runs(
                    run_id, observed_at, detector_version, crop_context,
                    position_available, position_message, detections_json, model_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    observed,
                    str(detector_version),
                    str(crop_context),
                    int(position_available),
                    message,
                    json.dumps([_detection_metadata(item) for item in detection_values], sort_keys=True),
                    metadata,
                ),
            )
            for detection in detection_values:
                weed_class = str(getattr(detection, "weed_class", getattr(detection, "label", ""))).strip()
                confidence = float(getattr(detection, "confidence", 0.0))
                if not weed_class or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                    raise ValueError("weed detections require a class and confidence between 0 and 1")
                if normalized_position is None:
                    # No coordinate means no persistent beta observation.
                    continue
                connection.execute(
                    """
                    INSERT INTO weed_observations(
                        observation_id, latitude, longitude, accuracy_m, position_source,
                        observed_at, detector_version, weed_class, confidence,
                        run_id, model_metadata, position_timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        normalized_position["latitude"],
                        normalized_position["longitude"],
                        normalized_position["accuracy_m"],
                        normalized_position["source"],
                        observed,
                        str(detector_version),
                        weed_class,
                        confidence,
                        run_id,
                        metadata,
                        normalized_position["timestamp"],
                    ),
                )
        return WeedRunRecord(
            run_id=run_id,
            observed_at=observed,
            detector_version=str(detector_version),
            crop_context=str(crop_context),
            position_available=position_available,
            position_message=message,
            detections=tuple(_detection_dict(item) for item in detection_values),
            model_metadata=dict(model_metadata or {}),
        )

    def list_runs(self, *, limit: int = 50) -> list[WeedRunRecord]:
        if limit <= 0:
            return []
        with self.database.transaction(immediate=False) as connection:
            runs = connection.execute(
                "SELECT * FROM weed_runs ORDER BY observed_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
            result: list[WeedRunRecord] = []
            for row in runs:
                detections = connection.execute(
                    "SELECT weed_class, confidence, detector_version, latitude, longitude, "
                    "accuracy_m, position_source, model_metadata FROM weed_observations "
                    "WHERE run_id = ? ORDER BY confidence DESC",
                    (row["run_id"],),
                ).fetchall()
                try:
                    stored_detections = json.loads(str(row["detections_json"]))
                    if not isinstance(stored_detections, list):
                        stored_detections = []
                except (TypeError, json.JSONDecodeError):
                    stored_detections = [dict(item) for item in detections]
                try:
                    stored_metadata = json.loads(str(row["model_metadata"]))
                    if not isinstance(stored_metadata, dict):
                        stored_metadata = {}
                except (TypeError, json.JSONDecodeError):
                    stored_metadata = {}
                result.append(
                    WeedRunRecord(
                        run_id=str(row["run_id"]),
                        observed_at=float(row["observed_at"]),
                        detector_version=str(row["detector_version"]),
                        crop_context=str(row["crop_context"]),
                        position_available=bool(int(row["position_available"])),
                        position_message=str(row["position_message"]),
                        detections=tuple(dict(item) for item in stored_detections),
                        model_metadata=stored_metadata,
                    )
                )
        return result

    def count(self) -> int:
        with self.database.transaction(immediate=False) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM weed_observations").fetchone()
        return int(row["count"])

    def run_count(self) -> int:
        with self.database.transaction(immediate=False) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM weed_runs").fetchone()
        return int(row["count"])

    def close(self) -> None:
        if self._owns_database:
            self.database.close()


def _normalize_position(position: dict[str, Any] | None, *, maximum_accuracy: float = 100.0) -> dict[str, float | str] | None:
    if position is None:
        return None
    try:
        latitude = float(position["latitude"])
        longitude = float(position["longitude"])
        accuracy = float(position["accuracy_m"])
        source = str(position["source"]).strip()
        timestamp_value = position.get("timestamp", time.time())
        timestamp = float(time.time() if timestamp_value is None else timestamp_value)
    except (KeyError, TypeError, ValueError):
        # Position is optional. Invalid browser data is treated the same as a
        # denied/unavailable fix so detection remains uninterrupted.
        return None
    if (
        not math.isfinite(latitude)
        or not -90 <= latitude <= 90
        or not math.isfinite(longitude)
        or not -180 <= longitude <= 180
        or not math.isfinite(accuracy)
        or accuracy < 0
        or not source
        or not math.isfinite(timestamp)
        or timestamp < 0
    ):
        return None
    if accuracy > maximum_accuracy:
        return None
    return {
        "latitude": latitude,
        "longitude": longitude,
        "accuracy_m": accuracy,
        "source": source,
        "timestamp": timestamp,
    }


def _detection_dict(detection: Any) -> dict[str, Any]:
    box = getattr(detection, "box", None)
    if box is None:
        return {
            "weed_class": str(getattr(detection, "weed_class", getattr(detection, "label", ""))),
            "confidence": float(getattr(detection, "confidence", 0.0)),
        }
    return {
        "weed_class": str(getattr(detection, "weed_class", getattr(detection, "label", ""))),
        "confidence": float(getattr(detection, "confidence", 0.0)),
        "box": {
            "x1": float(box.x1),
            "y1": float(box.y1),
            "x2": float(box.x2),
            "y2": float(box.y2),
        },
    }


def _detection_metadata(detection: Any) -> dict[str, Any]:
    """Return only non-image-space metadata for an accurate weed run."""

    return {
        "weed_class": str(getattr(detection, "weed_class", getattr(detection, "label", ""))),
        "confidence": float(getattr(detection, "confidence", 0.0)),
    }


__all__ = ["NO_POSITION_MESSAGE", "WeedObservationStore", "WeedRunRecord"]
