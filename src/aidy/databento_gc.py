from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import httpx

DATABENTO_DATASET = "GLBX.MDP3"
GC_PARENT_SYMBOL = "GC.FUT"
GC_CONTINUOUS_SYMBOL = "GC.n.0"
DATABENTO_BASE_URL = "https://hist.databento.com/v0"

FREE_CREDIT_USD = Decimal("125.00")
DAY40_CREDIT_SPEND_CAP_USD = Decimal("75.00")
DAY40_CREDIT_RESERVE_USD = Decimal("50.00")
MAX_SINGLE_REQUEST_USD = Decimal("5.00")

ALLOWED_RESEARCH_SCHEMAS = frozenset(
    {
        "definition",
        "statistics",
        "ohlcv-1m",
        "ohlcv-1h",
        "ohlcv-1d",
        "trades",
        "tbbo",
        "bbo-1m",
    }
)
PROHIBITED_EXPENSIVE_SCHEMAS = frozenset({"mbo", "mbp-10"})


class DatabentoPolicyError(ValueError):
    """Raised when a request would violate AIDY's free-first Databento policy."""


class DatabentoAuthenticationError(RuntimeError):
    """Raised when Databento rejects the configured API key."""


class DatabentoTransportError(RuntimeError):
    """Raised when Databento cannot be reached or returns an unusable response."""


def _decimal(value: Any, *, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DatabentoPolicyError(f"{name} must be a finite decimal value.") from exc
    if not parsed.is_finite():
        raise DatabentoPolicyError(f"{name} must be a finite decimal value.")
    return parsed


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class HistoricalRequest:
    schema: str
    start: str
    end: str
    symbols: str = GC_CONTINUOUS_SYMBOL
    stype_in: str = "continuous"

    def validate(self) -> None:
        schema = self.schema.strip()
        if schema in PROHIBITED_EXPENSIVE_SCHEMAS:
            raise DatabentoPolicyError(
                f"Schema {schema!r} is deliberately prohibited during the free-credit phase."
            )
        if schema not in ALLOWED_RESEARCH_SCHEMAS:
            raise DatabentoPolicyError(f"Schema {schema!r} is not approved for Day 40/41 research.")
        if not self.start.strip() or not self.end.strip() or self.start >= self.end:
            raise DatabentoPolicyError("Historical request requires a non-empty start before end.")
        if schema == "definition":
            if self.symbols != GC_PARENT_SYMBOL or self.stype_in != "parent":
                raise DatabentoPolicyError(
                    "Definition requests must use GC.FUT parent symbology for roll provenance."
                )
        elif self.symbols != GC_CONTINUOUS_SYMBOL or self.stype_in != "continuous":
            raise DatabentoPolicyError(
                "GC research requests must use the OI-ranked continuous contract GC.n.0."
            )

    def payload(self) -> dict[str, str]:
        self.validate()
        return {
            "dataset": DATABENTO_DATASET,
            "symbols": self.symbols,
            "schema": self.schema,
            "start": self.start,
            "end": self.end,
            "stype_in": self.stype_in,
        }

    @property
    def request_digest(self) -> str:
        return digest(self.payload())


@dataclass(frozen=True)
class CostQuote:
    request_digest: str
    quoted_cost_usd: Decimal
    prior_committed_usd: Decimal
    spend_cap_usd: Decimal = DAY40_CREDIT_SPEND_CAP_USD
    single_request_cap_usd: Decimal = MAX_SINGLE_REQUEST_USD

    @property
    def approved(self) -> bool:
        return (
            self.quoted_cost_usd >= 0
            and self.quoted_cost_usd <= self.single_request_cap_usd
            and self.prior_committed_usd + self.quoted_cost_usd <= self.spend_cap_usd
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_digest": self.request_digest,
            "quoted_cost_usd": str(self.quoted_cost_usd),
            "prior_committed_usd": str(self.prior_committed_usd),
            "spend_cap_usd": str(self.spend_cap_usd),
            "single_request_cap_usd": str(self.single_request_cap_usd),
            "approved": self.approved,
            "paid_subscription_enabled": False,
            "live_data_enabled": False,
            "free_credit_reserve_usd": str(DAY40_CREDIT_RESERVE_USD),
        }


class DatabentoHistoricalClient:
    """Minimal Databento Historical HTTP client for bounded GC research.

    The client deliberately supports historical metadata/cost estimation and
    bounded JSONL downloads only. It contains no live subscription code.
    """

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise DatabentoAuthenticationError("DATABENTO_API_KEY is missing.")
        if not key.startswith("db-") or len(key) != 32:
            raise DatabentoAuthenticationError(
                "DATABENTO_API_KEY does not match Databento's documented key format."
            )
        self._client = httpx.Client(
            base_url=DATABENTO_BASE_URL,
            auth=httpx.BasicAuth(key, ""),
            timeout=timeout_seconds,
            transport=transport,
            headers={"User-Agent": "aidy-gold-signals/day40-free-first"},
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> "DatabentoHistoricalClient":
        return cls(os.environ.get("DATABENTO_API_KEY", ""), **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DatabentoHistoricalClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise DatabentoAuthenticationError(
                "Databento rejected the configured API key or entitlement."
            )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DatabentoTransportError(
                f"Databento request failed with HTTP {response.status_code}."
            ) from exc

    def _get_json(self, endpoint: str, params: Mapping[str, str] | None = None) -> Any:
        try:
            response = self._client.get(endpoint, params=params)
        except httpx.HTTPError as exc:
            raise DatabentoTransportError("Databento historical API is unreachable.") from exc
        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise DatabentoTransportError("Databento returned invalid JSON metadata.") from exc

    def list_datasets(self) -> list[str]:
        result = self._get_json("/metadata.list_datasets")
        if not isinstance(result, list):
            raise DatabentoTransportError("Unexpected Databento dataset response.")
        return [str(item) for item in result]

    def list_schemas(self) -> list[str]:
        result = self._get_json(
            "/metadata.list_schemas",
            params={"dataset": DATABENTO_DATASET},
        )
        if not isinstance(result, list):
            raise DatabentoTransportError("Unexpected Databento schema response.")
        return [str(item) for item in result]

    def dataset_range(self) -> dict[str, Any]:
        result = self._get_json(
            "/metadata.get_dataset_range",
            params={"dataset": DATABENTO_DATASET},
        )
        if not isinstance(result, dict):
            raise DatabentoTransportError("Unexpected Databento range response.")
        return dict(result)

    def estimate_cost(
        self,
        request: HistoricalRequest,
        *,
        prior_committed_usd: Decimal | str | float = Decimal("0"),
    ) -> CostQuote:
        payload = request.payload()
        result = self._get_json("/metadata.get_cost", params=payload)
        cost = _decimal(result, name="Databento quoted cost")
        prior = _decimal(prior_committed_usd, name="prior_committed_usd")
        if prior < 0:
            raise DatabentoPolicyError("prior_committed_usd cannot be negative.")
        return CostQuote(
            request_digest=request.request_digest,
            quoted_cost_usd=cost,
            prior_committed_usd=prior,
        )

    def assert_gc_entitlement(self) -> dict[str, Any]:
        datasets = self.list_datasets()
        if DATABENTO_DATASET not in datasets:
            raise DatabentoAuthenticationError(
                "Authenticated account cannot see the GLBX.MDP3 dataset."
            )
        schemas = self.list_schemas()
        missing = sorted(ALLOWED_RESEARCH_SCHEMAS - set(schemas))
        if missing:
            raise DatabentoAuthenticationError(
                f"GLBX.MDP3 entitlement is missing required schemas: {missing}"
            )
        return {
            "authenticated": True,
            "dataset": DATABENTO_DATASET,
            "required_schemas_available": True,
            "live_subscription_required": False,
            "paid_subscription_enabled": False,
        }

    def download_jsonl(
        self,
        request: HistoricalRequest,
        *,
        quote: CostQuote,
        output_path: str | Path,
    ) -> dict[str, Any]:
        request.validate()
        if quote.request_digest != request.request_digest:
            raise DatabentoPolicyError("Cost quote does not belong to this request.")
        if not quote.approved:
            raise DatabentoPolicyError(
                "Request exceeds the Day 40 free-credit spending policy."
            )

        fresh_quote = self.estimate_cost(
            request,
            prior_committed_usd=quote.prior_committed_usd,
        )
        if not fresh_quote.approved or fresh_quote.quoted_cost_usd > quote.quoted_cost_usd:
            raise DatabentoPolicyError(
                "Databento cost increased after approval; refusing download."
            )

        form = {
            **request.payload(),
            "encoding": "json",
            "compression": "none",
            "pretty_px": "true",
            "pretty_ts": "true",
            "map_symbols": "true",
        }
        try:
            with self._client.stream("POST", "/timeseries.get_range", data=form) as response:
                self._raise_for_status(response)
                path = Path(output_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                hasher = sha256()
                byte_count = 0
                with path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        handle.write(chunk)
                        hasher.update(chunk)
                        byte_count += len(chunk)
        except httpx.HTTPError as exc:
            raise DatabentoTransportError("Databento historical download failed.") from exc

        return {
            "request_digest": request.request_digest,
            "quoted_cost_usd": str(fresh_quote.quoted_cost_usd),
            "path": str(path),
            "byte_count": byte_count,
            "sha256": hasher.hexdigest(),
            "dataset": DATABENTO_DATASET,
            "historical_only": True,
            "live_subscription_enabled": False,
            "paid_subscription_enabled": False,
        }


def day40_free_first_procurement_record() -> dict[str, Any]:
    record: dict[str, Any] = {
        "decision_version": "aidy_day40_market_data_procurement_v1",
        "decision": "go_gc_research_no_go_paid_live",
        "preferred_historical_provider": "Databento",
        "dataset": DATABENTO_DATASET,
        "gc_parent_symbol": GC_PARENT_SYMBOL,
        "gc_continuous_symbol": GC_CONTINUOUS_SYMBOL,
        "free_credit_usd": str(FREE_CREDIT_USD),
        "day40_credit_spend_cap_usd": str(DAY40_CREDIT_SPEND_CAP_USD),
        "reserved_credit_usd": str(DAY40_CREDIT_RESERVE_USD),
        "max_single_request_usd": str(MAX_SINGLE_REQUEST_USD),
        "allowed_schemas": sorted(ALLOWED_RESEARCH_SCHEMAS),
        "prohibited_schemas": sorted(PROHIBITED_EXPENSIVE_SCHEMAS),
        "live_gc_required_now": False,
        "paid_subscription_enabled": False,
        "owner_approval_required_before_paid_activation": True,
        "owner_approved_paid_activation": False,
        "day41_mode": "historical_delayed_shadow_research",
        "formal_live_gc_promotion_allowed": False,
        "rationale": (
            "Use licensed historical GC data and public CME evidence to test incremental "
            "value before any recurring market-data spend."
        ),
    }
    record["decision_digest"] = digest(record)
    return record
