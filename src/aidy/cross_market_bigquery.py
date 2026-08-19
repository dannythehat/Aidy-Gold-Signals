from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .bigquery_exporter import EXPORT_MANIFEST, FieldSpec, TableSpec, load_identity

CROSS_MARKET_TABLE = TableSpec(
    name="market_cross_market_observations",
    partition_field="first_observed_at",
    clustering_fields=("source", "series_id"),
    fields=(
        FieldSpec("load_identity", "STRING", "REQUIRED"),
        FieldSpec("schema_version", "INTEGER", "REQUIRED"),
        FieldSpec("record_type", "STRING", "REQUIRED"),
        FieldSpec("evidence_id", "STRING", "REQUIRED"),
        FieldSpec("archive_key", "STRING", "REQUIRED"),
        FieldSpec("payload_digest", "STRING", "REQUIRED"),
        FieldSpec("revision_index", "INTEGER", "REQUIRED"),
        FieldSpec("source", "STRING", "REQUIRED"),
        FieldSpec("series_id", "STRING", "REQUIRED"),
        FieldSpec("observation_date", "DATE", "REQUIRED"),
        FieldSpec("value", "STRING", "REQUIRED"),
        FieldSpec("unit", "STRING", "REQUIRED"),
        FieldSpec("source_url", "STRING", "REQUIRED"),
        FieldSpec("source_document_digest", "STRING", "REQUIRED"),
        FieldSpec("first_observed_at", "TIMESTAMP", "REQUIRED"),
    ),
)


@dataclass(frozen=True, slots=True)
class ArchivedCrossMarketEvidence:
    schema_version: int
    evidence_id: str
    archive_key: str
    payload_digest: str
    revision_index: int
    payload: dict[str, Any]

    @property
    def load_identity(self) -> str:
        return load_identity(self.archive_key, self.payload_digest)

    @classmethod
    def from_json(cls, raw: str | bytes) -> ArchivedCrossMarketEvidence:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or parsed.get("record_type") != "cross_market":
            raise ValueError("Expected cross_market R2 evidence.")
        if int(parsed.get("schema_version") or 0) != 1:
            raise ValueError("Unsupported cross-market schema version.")
        payload = parsed.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("Cross-market R2 payload must be an object.")
        required = ("evidence_id", "archive_key", "payload_digest", "revision_index")
        if any(parsed.get(name) in (None, "") for name in required):
            raise ValueError("Cross-market R2 envelope is incomplete.")
        return cls(
            schema_version=1,
            evidence_id=str(parsed["evidence_id"]),
            archive_key=str(parsed["archive_key"]),
            payload_digest=str(parsed["payload_digest"]),
            revision_index=int(parsed["revision_index"]),
            payload=payload,
        )

    def analytical_row(self) -> dict[str, Any]:
        required = (
            "source",
            "series_id",
            "observation_date",
            "value",
            "unit",
            "source_url",
            "source_document_digest",
            "first_observed_at",
        )
        if any(self.payload.get(name) in (None, "") for name in required):
            raise ValueError("Cross-market analytical payload is incomplete.")
        first_seen = datetime.fromisoformat(str(self.payload["first_observed_at"]))
        if first_seen.tzinfo is None:
            raise ValueError("Cross-market first_observed_at must be timezone-aware.")
        observation_date = str(self.payload["observation_date"])
        datetime.strptime(observation_date, "%Y-%m-%d")
        return {
            "load_identity": self.load_identity,
            "schema_version": self.schema_version,
            "record_type": "cross_market",
            "evidence_id": self.evidence_id,
            "archive_key": self.archive_key,
            "payload_digest": self.payload_digest,
            "revision_index": self.revision_index,
            "source": str(self.payload["source"]),
            "series_id": str(self.payload["series_id"]),
            "observation_date": observation_date,
            "value": str(self.payload["value"]),
            "unit": str(self.payload["unit"]),
            "source_url": str(self.payload["source_url"]),
            "source_document_digest": str(self.payload["source_document_digest"]),
            "first_observed_at": first_seen.astimezone(UTC).isoformat(),
        }

    def manifest_row(
        self,
        *,
        exported_at: datetime,
        run_id: str,
        load_job_id: str,
    ) -> dict[str, Any]:
        if exported_at.tzinfo is None:
            raise ValueError("Cross-market export timestamp must be timezone-aware.")
        return {
            "load_identity": self.load_identity,
            "archive_key": self.archive_key,
            "payload_digest": self.payload_digest,
            "record_type": "cross_market",
            "schema_version": 1,
            "evidence_id": self.evidence_id,
            "exported_at": exported_at.astimezone(UTC).isoformat(),
            "destination_table": CROSS_MARKET_TABLE.name,
            "load_job_id": load_job_id,
            "run_id": run_id,
            "status": "success",
        }


ANALYTICAL_SPECS = (CROSS_MARKET_TABLE, EXPORT_MANIFEST)
