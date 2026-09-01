from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.databento_gc import DATABENTO_DATASET, GC_CONTINUOUS_SYMBOL

DAY41_SHADOW_VERSION = "aidy_gc_xau_shadow_spine_v1"
DAY41_PROMOTION_POLICY_VERSION = "aidy_gc_shadow_promotion_policy_v1"
XAU_REFERENCE_SOURCE = "gold_api_public"
MAX_ACCEPTANCE_PAIR_SKEW_SECONDS = 3600
PROMOTION_MAX_P95_SKEW_SECONDS = 120
_DATABENTO_KEY_PATTERN = re.compile(r"db-[A-Za-z0-9]{29}")


class ShadowSpineError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def normalize_databento_api_key(raw: str) -> str:
    """Extract exactly one Databento API key without logging surrounding secret text."""

    if not isinstance(raw, str):
        raise ShadowSpineError("Databento API key secret must be text.")
    matches = _DATABENTO_KEY_PATTERN.findall(raw)
    unique_matches = sorted(set(matches))
    if len(unique_matches) != 1:
        raise ShadowSpineError(
            "Databento API key secret must contain exactly one 32-character key starting with db-."
        )
    return unique_matches[0]


def _decimal(value: Any, *, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ShadowSpineError(f"{name} must be a finite decimal.") from exc
    if not result.is_finite() or result <= 0:
        raise ShadowSpineError(f"{name} must be a positive finite decimal.")
    return result


def _timestamp(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ShadowSpineError(f"{name} must be an ISO-8601 timestamp.") from exc
    elif isinstance(value, int) and not isinstance(value, bool):
        parsed = datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)
    else:
        raise ShadowSpineError(f"{name} must be a timestamp.")
    if parsed.tzinfo is None:
        raise ShadowSpineError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _contract_symbol(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    symbol = value.strip().upper()
    if not symbol or symbol == GC_CONTINUOUS_SYMBOL.upper():
        return None
    if not symbol.startswith("GC"):
        return None
    return symbol


@dataclass(frozen=True, slots=True)
class GcObservation:
    observed_at: datetime
    price: Decimal
    contract_symbol: str
    provider: str = "Databento"
    dataset: str = DATABENTO_DATASET
    continuous_symbol: str = GC_CONTINUOUS_SYMBOL
    source_digest: str | None = None

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "provider": self.provider,
            "dataset": self.dataset,
            "continuous_symbol": self.continuous_symbol,
            "contract_symbol": self.contract_symbol,
            "observed_at_utc": self.observed_at.astimezone(UTC).isoformat(),
            "price": str(self.price),
            "source_digest": self.source_digest,
        }
        body["observation_digest"] = digest(body)
        return body


@dataclass(frozen=True, slots=True)
class XauObservation:
    observed_at: datetime
    price: Decimal
    source: str = XAU_REFERENCE_SOURCE
    symbol: str = "XAUUSD"
    source_digest: str | None = None

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "source": self.source,
            "symbol": self.symbol,
            "observed_at_utc": self.observed_at.astimezone(UTC).isoformat(),
            "price": str(self.price),
            "source_digest": self.source_digest,
        }
        body["observation_digest"] = digest(body)
        return body


def parse_databento_ohlcv_jsonl(payload: str) -> list[GcObservation]:
    """Parse Databento pretty JSONL and retain only mapped GC OHLCV observations.

    `map_symbols=true` may emit symbol-mapping rows separately from market-data rows,
    so the parser tracks mapped raw GC contract identities and refuses anonymous
    instrument IDs. Databento text encodings place event metadata under the `hd`
    object, while synthetic fixtures may provide `ts_event` at the top level.
    """

    mapped_contract: str | None = None
    observations: list[GcObservation] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ShadowSpineError("Databento JSONL contained malformed JSON.") from exc
        if not isinstance(row, dict):
            continue

        mapping_candidate = (
            _contract_symbol(row.get("stype_out_symbol"))
            or _contract_symbol(row.get("raw_symbol"))
            or _contract_symbol(row.get("symbol"))
        )
        if mapping_candidate:
            mapped_contract = mapping_candidate

        price_value = row.get("close")
        if price_value is None:
            continue
        timestamp_value = row.get("ts_event") or row.get("ts_recv")
        header = row.get("hd")
        if timestamp_value is None and isinstance(header, dict):
            timestamp_value = header.get("ts_event")
        if timestamp_value is None:
            continue
        contract = mapping_candidate or mapped_contract
        if contract is None:
            raise ShadowSpineError(
                "Databento GC observation is missing a mapped raw contract identity."
            )
        price = _decimal(price_value, name="GC price")
        if price < Decimal(100) or price > Decimal(100000):
            raise ShadowSpineError("GC price is outside the sanity envelope.")
        observed_at = _timestamp(timestamp_value, name="GC observation time")
        source_body = {
            "dataset": DATABENTO_DATASET,
            "continuous_symbol": GC_CONTINUOUS_SYMBOL,
            "contract_symbol": contract,
            "row": row,
        }
        observations.append(
            GcObservation(
                observed_at=observed_at,
                price=price,
                contract_symbol=contract,
                source_digest=digest(source_body),
            )
        )
    return observations


def xau_observation_from_gold_api(payload: dict[str, Any]) -> XauObservation:
    symbol = str(payload.get("symbol") or "").upper()
    if symbol not in {"XAU", "XAUUSD"}:
        raise ShadowSpineError("Gold API response is not an XAU observation.")
    observed = payload.get("updatedAt") or payload.get("timestamp")
    result = XauObservation(
        observed_at=_timestamp(observed, name="XAU observation time"),
        price=_decimal(payload.get("price"), name="XAU price"),
        source_digest=digest(payload),
    )
    if result.price < Decimal(100) or result.price > Decimal(100000):
        raise ShadowSpineError("XAU price is outside the sanity envelope.")
    return result


def pair_shadow_observations(
    gc: GcObservation,
    xau: XauObservation,
    *,
    max_skew_seconds: int = MAX_ACCEPTANCE_PAIR_SKEW_SECONDS,
) -> dict[str, Any]:
    if gc.provider != "Databento" or gc.dataset != DATABENTO_DATASET:
        raise ShadowSpineError("GC source substitution is forbidden.")
    if xau.source != XAU_REFERENCE_SOURCE or xau.symbol != "XAUUSD":
        raise ShadowSpineError("XAU reference substitution is forbidden.")
    if max_skew_seconds <= 0:
        raise ShadowSpineError("max_skew_seconds must be positive.")

    skew_seconds = abs((gc.observed_at - xau.observed_at).total_seconds())
    paired = skew_seconds <= max_skew_seconds
    basis = gc.price - xau.price if paired else None
    basis_bps = (basis / xau.price * Decimal(10000)) if basis is not None else None
    body: dict[str, Any] = {
        "shadow_version": DAY41_SHADOW_VERSION,
        "state": "paired" if paired else "unpaired_timestamp_skew",
        "paired": paired,
        "gc": gc.as_dict(),
        "xau": xau.as_dict(),
        "timestamp_skew_seconds": round(skew_seconds, 6),
        "max_pair_skew_seconds": max_skew_seconds,
        "basis_usd": str(basis) if basis is not None else None,
        "basis_bps": str(basis_bps) if basis_bps is not None else None,
        "gc_shadow_only": True,
        "xau_reference_retained": True,
        "silent_source_substitution_allowed": False,
        "broker_market_data_dependency": False,
        "paid_subscription_activated": False,
        "live_gc_promoted": False,
    }
    body["pair_digest"] = digest(body)
    return body


def gc_shadow_promotion_policy() -> dict[str, Any]:
    """Pre-specified promotion evidence requirements; never auto-promotes GC."""

    body: dict[str, Any] = {
        "policy_version": DAY41_PROMOTION_POLICY_VERSION,
        "frozen_before_shadow_results": True,
        "minimum_paired_observations": 1000,
        "minimum_named_session_windows": 4,
        "minimum_distinct_trading_days": 10,
        "maximum_missing_pair_rate": "0.01",
        "maximum_contract_identity_missing_rate": "0",
        "maximum_p95_timestamp_skew_seconds": PROMOTION_MAX_P95_SKEW_SECONDS,
        "require_roll_window_annotation": True,
        "require_basis_distribution_by_session": True,
        "require_outage_isolation_test": True,
        "require_no_silent_source_substitution": True,
        "require_xau_reference_parallel_run": True,
        "require_owner_approval_for_any_paid_or_live_promotion": True,
        "automatic_promotion_allowed": False,
        "performance_improvement_alone_can_promote": False,
    }
    body["policy_digest"] = digest(body)
    return body


def day41_architecture_manifest() -> dict[str, Any]:
    policy = gc_shadow_promotion_policy()
    body: dict[str, Any] = {
        "manifest_version": "aidy_day41_gc_shadow_manifest_v1",
        "provider": "Databento",
        "dataset": DATABENTO_DATASET,
        "continuous_symbol": GC_CONTINUOUS_SYMBOL,
        "xau_reference_source": XAU_REFERENCE_SOURCE,
        "vendor_separable_adapter": True,
        "gc_shadow_only": True,
        "xau_reference_retained": True,
        "outage_substitution_allowed": False,
        "broker_market_data_dependency": False,
        "paid_subscription_activated": False,
        "live_gc_promoted": False,
        "promotion_policy": policy,
    }
    body["manifest_digest"] = digest(body)
    return body
