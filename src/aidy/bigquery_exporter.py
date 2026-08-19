from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    field_type: str
    mode: str = "NULLABLE"


@dataclass(frozen=True, slots=True)
class TableSpec:
    name: str
    fields: tuple[FieldSpec, ...]
    partition_field: str
    clustering_fields: tuple[str, ...]


_COMMON_FIELDS = (
    FieldSpec("load_identity", "STRING", "REQUIRED"),
    FieldSpec("schema_version", "INTEGER", "REQUIRED"),
    FieldSpec("record_type", "STRING", "REQUIRED"),
    FieldSpec("evidence_id", "STRING", "REQUIRED"),
    FieldSpec("archive_key", "STRING", "REQUIRED"),
    FieldSpec("payload_digest", "STRING", "REQUIRED"),
)

MARKET_CANDLES = TableSpec(
    name="market_candles",
    partition_field="open_time_utc",
    clustering_fields=("symbol", "timeframe", "source"),
    fields=_COMMON_FIELDS
    + (
        FieldSpec("revision_index", "INTEGER", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("timeframe", "STRING", "REQUIRED"),
        FieldSpec("open_time_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("broker_open_time", "TIMESTAMP"),
        FieldSpec("open", "STRING", "REQUIRED"),
        FieldSpec("high", "STRING", "REQUIRED"),
        FieldSpec("low", "STRING", "REQUIRED"),
        FieldSpec("close", "STRING", "REQUIRED"),
        FieldSpec("tick_volume", "STRING"),
        FieldSpec("spread", "STRING"),
        FieldSpec("volume", "STRING"),
        FieldSpec("source", "STRING", "REQUIRED"),
        FieldSpec("first_observed_at", "TIMESTAMP", "REQUIRED"),
    ),
)

MARKET_SNAPSHOTS = TableSpec(
    name="market_snapshots",
    partition_field="captured_at",
    clustering_fields=("symbol", "capture_status", "session_code"),
    fields=_COMMON_FIELDS
    + (
        FieldSpec("captured_at", "TIMESTAMP", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("capture_status", "STRING", "REQUIRED"),
        FieldSpec("bid", "STRING"),
        FieldSpec("ask", "STRING"),
        FieldSpec("mid", "STRING"),
        FieldSpec("spread", "STRING"),
        FieldSpec("quote_time", "TIMESTAMP"),
        FieldSpec("quote_age_seconds", "FLOAT"),
        FieldSpec("session_code", "STRING", "REQUIRED"),
        FieldSpec("market_data_source", "STRING"),
        FieldSpec("data_availability", "JSON", "REQUIRED"),
        FieldSpec("event_observation_ids", "STRING", "REPEATED"),
        FieldSpec("latest_m1_id", "STRING"),
        FieldSpec("latest_m5_id", "STRING"),
        FieldSpec("latest_m15_id", "STRING"),
        FieldSpec("latest_h1_id", "STRING"),
        FieldSpec("latest_h4_id", "STRING"),
        FieldSpec("latest_d1_id", "STRING"),
    ),
)

MARKET_EVENT_OBSERVATIONS = TableSpec(
    name="market_event_observations",
    partition_field="first_observed_at",
    clustering_fields=("source", "event_type"),
    fields=_COMMON_FIELDS
    + (
        FieldSpec("revision_index", "INTEGER", "REQUIRED"),
        FieldSpec("source", "STRING", "REQUIRED"),
        FieldSpec("external_id", "STRING", "REQUIRED"),
        FieldSpec("event_type", "STRING", "REQUIRED"),
        FieldSpec("published_at", "TIMESTAMP"),
        FieldSpec("first_observed_at", "TIMESTAMP", "REQUIRED"),
        FieldSpec("headline", "STRING"),
        FieldSpec("structured_data", "JSON", "REQUIRED"),
    ),
)

EXPORT_MANIFEST = TableSpec(
    name="export_manifest",
    partition_field="exported_at",
    clustering_fields=("record_type", "status", "destination_table"),
    fields=(
        FieldSpec("load_identity", "STRING", "REQUIRED"),
        FieldSpec("archive_key", "STRING", "REQUIRED"),
        FieldSpec("payload_digest", "STRING", "REQUIRED"),
        FieldSpec("record_type", "STRING", "REQUIRED"),
        FieldSpec("schema_version", "INTEGER", "REQUIRED"),
        FieldSpec("evidence_id", "STRING", "REQUIRED"),
        FieldSpec("exported_at", "TIMESTAMP", "REQUIRED"),
        FieldSpec("destination_table", "STRING", "REQUIRED"),
        FieldSpec("load_job_id", "STRING", "REQUIRED"),
        FieldSpec("run_id", "STRING", "REQUIRED"),
        FieldSpec("status", "STRING", "REQUIRED"),
    ),
)

TABLE_SPECS = {
    "candle": MARKET_CANDLES,
    "snapshot": MARKET_SNAPSHOTS,
    "event": MARKET_EVENT_OBSERVATIONS,
}


@dataclass(frozen=True, slots=True)
class ArchivedEvidence:
    schema_version: int
    record_type: str
    evidence_id: str
    archive_key: str
    payload_digest: str
    revision_index: int | None
    payload: dict[str, Any]

    @property
    def load_identity(self) -> str:
        return load_identity(self.archive_key, self.payload_digest)

    @property
    def destination(self) -> TableSpec:
        try:
            return TABLE_SPECS[self.record_type]
        except KeyError as exc:
            raise ValueError(f"Unsupported analytical record type: {self.record_type}") from exc

    @classmethod
    def from_json(cls, raw: str | bytes) -> ArchivedEvidence:
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("R2 evidence object is not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("R2 evidence object must be a JSON object.")
        required = ("schema_version", "record_type", "evidence_id", "archive_key", "payload_digest")
        missing = [name for name in required if parsed.get(name) in (None, "")]
        if missing:
            raise ValueError("R2 evidence object is missing: " + ", ".join(missing))
        payload = parsed.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("R2 evidence object requires an object payload.")
        try:
            schema_version = int(parsed["schema_version"])
        except (TypeError, ValueError) as exc:
            raise ValueError("R2 evidence schema_version must be an integer.") from exc
        record_type = str(parsed["record_type"])
        if record_type not in TABLE_SPECS:
            raise ValueError(f"Unsupported analytical record type: {record_type}")
        expected_schema = 2 if record_type == "snapshot" else 1
        if schema_version != expected_schema:
            raise ValueError(
                f"Unsupported {record_type} schema version {schema_version}; expected {expected_schema}."
            )
        revision_raw = parsed.get("revision_index")
        revision_index = None if revision_raw is None else int(revision_raw)
        if record_type in {"candle", "event"} and revision_index is None:
            raise ValueError(f"{record_type} evidence requires revision_index.")
        return cls(
            schema_version=schema_version,
            record_type=record_type,
            evidence_id=str(parsed["evidence_id"]),
            archive_key=str(parsed["archive_key"]),
            payload_digest=str(parsed["payload_digest"]),
            revision_index=revision_index,
            payload=payload,
        )


def load_identity(archive_key: str, payload_digest: str) -> str:
    if not archive_key.strip() or not payload_digest.strip():
        raise ValueError("Export identity requires archive_key and payload_digest.")
    return sha256(f"{archive_key}\x00{payload_digest}".encode()).hexdigest()


def _required(payload: dict[str, Any], name: str) -> Any:
    value = payload.get(name)
    if value is None or value == "":
        raise ValueError(f"Archived payload is missing required field: {name}")
    return value


def _string(value: Any) -> str | None:
    return None if value is None else str(value)


def _timestamp(value: Any, *, required: bool = False) -> str | None:
    if value in (None, ""):
        if required:
            raise ValueError("Archived payload is missing a required timestamp.")
        return None
    if not isinstance(value, str):
        raise ValueError("Archived timestamp must be an ISO-8601 string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid archived timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError("Archived timestamps must be timezone-aware.")
    return parsed.astimezone(UTC).isoformat()


def _json_object(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object.")
    return value


def _common(evidence: ArchivedEvidence) -> dict[str, Any]:
    return {
        "load_identity": evidence.load_identity,
        "schema_version": evidence.schema_version,
        "record_type": evidence.record_type,
        "evidence_id": evidence.evidence_id,
        "archive_key": evidence.archive_key,
        "payload_digest": evidence.payload_digest,
    }


def analytical_row(evidence: ArchivedEvidence) -> dict[str, Any]:
    payload = evidence.payload
    row = _common(evidence)
    if evidence.record_type == "candle":
        row.update(
            {
                "revision_index": evidence.revision_index,
                "symbol": str(_required(payload, "symbol")),
                "timeframe": str(_required(payload, "timeframe")),
                "open_time_utc": _timestamp(_required(payload, "open_time_utc"), required=True),
                "broker_open_time": _timestamp(payload.get("broker_open_time")),
                "open": str(_required(payload, "open")),
                "high": str(_required(payload, "high")),
                "low": str(_required(payload, "low")),
                "close": str(_required(payload, "close")),
                "tick_volume": _string(payload.get("tick_volume")),
                "spread": _string(payload.get("spread")),
                "volume": _string(payload.get("volume")),
                "source": str(_required(payload, "source")),
                "first_observed_at": _timestamp(
                    _required(payload, "first_observed_at"), required=True
                ),
            }
        )
    elif evidence.record_type == "snapshot":
        availability = _json_object(_required(payload, "data_availability"), name="data_availability")
        event_ids = payload.get("event_observation_ids")
        if not isinstance(event_ids, list):
            raise ValueError("event_observation_ids must be an array.")
        row.update(
            {
                "captured_at": _timestamp(_required(payload, "captured_at"), required=True),
                "symbol": str(_required(payload, "symbol")),
                "capture_status": str(_required(payload, "capture_status")),
                "bid": _string(payload.get("bid")),
                "ask": _string(payload.get("ask")),
                "mid": _string(payload.get("mid")),
                "spread": _string(payload.get("spread")),
                "quote_time": _timestamp(payload.get("quote_time")),
                "quote_age_seconds": (
                    None
                    if payload.get("quote_age_seconds") is None
                    else float(payload["quote_age_seconds"])
                ),
                "session_code": str(_required(payload, "session_code")),
                "market_data_source": _string(availability.get("market_data_source")),
                "data_availability": availability,
                "event_observation_ids": [str(value) for value in event_ids],
                "latest_m1_id": _string(payload.get("latest_m1_id")),
                "latest_m5_id": _string(payload.get("latest_m5_id")),
                "latest_m15_id": _string(payload.get("latest_m15_id")),
                "latest_h1_id": _string(payload.get("latest_h1_id")),
                "latest_h4_id": _string(payload.get("latest_h4_id")),
                "latest_d1_id": _string(payload.get("latest_d1_id")),
            }
        )
    elif evidence.record_type == "event":
        row.update(
            {
                "revision_index": evidence.revision_index,
                "source": str(_required(payload, "source")),
                "external_id": str(_required(payload, "external_id")),
                "event_type": str(_required(payload, "event_type")),
                "published_at": _timestamp(payload.get("published_at")),
                "first_observed_at": _timestamp(
                    _required(payload, "first_observed_at"), required=True
                ),
                "headline": _string(payload.get("headline")),
                "structured_data": _json_object(
                    _required(payload, "structured_data"), name="structured_data"
                ),
            }
        )
    else:  # guarded in ArchivedEvidence
        raise ValueError(f"Unsupported analytical record type: {evidence.record_type}")
    return row


def manifest_row(
    evidence: ArchivedEvidence,
    *,
    exported_at: datetime,
    run_id: str,
    load_job_id: str,
    status: str = "success",
) -> dict[str, Any]:
    if exported_at.tzinfo is None:
        raise ValueError("Manifest export timestamp must be timezone-aware.")
    if not run_id.strip() or not load_job_id.strip():
        raise ValueError("Manifest requires run_id and load_job_id.")
    return {
        "load_identity": evidence.load_identity,
        "archive_key": evidence.archive_key,
        "payload_digest": evidence.payload_digest,
        "record_type": evidence.record_type,
        "schema_version": evidence.schema_version,
        "evidence_id": evidence.evidence_id,
        "exported_at": exported_at.astimezone(UTC).isoformat(),
        "destination_table": evidence.destination.name,
        "load_job_id": load_job_id,
        "run_id": run_id,
        "status": status,
    }


def merge_sql(*, project: str, dataset: str, destination: TableSpec) -> str:
    if not project.strip() or not dataset.strip():
        raise ValueError("BigQuery merge requires project and dataset names.")
    columns = [field.name for field in destination.fields]
    column_sql = ", ".join(f"`{name}`" for name in columns)
    values_sql = ", ".join(f"S.`{name}`" for name in columns)
    staging = f"_stage_{destination.name}"
    return f"""
MERGE `{project}.{dataset}.{destination.name}` AS T
USING (
  SELECT {column_sql}
  FROM `{project}.{dataset}.{staging}`
  WHERE run_id = @run_id
  QUALIFY ROW_NUMBER() OVER (PARTITION BY load_identity ORDER BY run_id) = 1
) AS S
ON T.load_identity = S.load_identity
WHEN NOT MATCHED THEN
  INSERT ({column_sql}) VALUES ({values_sql})
""".strip()


def staging_fields(spec: TableSpec) -> tuple[FieldSpec, ...]:
    return (FieldSpec("run_id", "STRING", "REQUIRED"),) + spec.fields
