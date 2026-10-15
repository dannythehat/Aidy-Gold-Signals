"""Day27: point-in-time XAUUSD regime labels on Day26 walk-forward predictions.

All labels use CLOSED bid-M5 information observable by their own decision time.
Only Day26 DEVELOPMENT-FOLD validation decisions are scored; the sealed OOS
holdout is never reopened. Unknown economic-news calendar is NEVER called quiet.
Retrospective BID change-sign diagnostics are NOT executable trade P&L.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

from aidy.strategy_lab_history_reader import ClosedBar, ReadResult
from aidy.strategy_lab_oos_protocol import MODEL_SHA256, SealedOOS

STEP = timedelta(minutes=5)
CENT = Decimal("0.01")
TREND_BUCKETS = ("trend_up", "trend_down", "range", "transitional")
VOL_BUCKETS = ("low", "normal", "high")
SESSION_BUCKETS = ("london_new_york_overlap", "london", "new_york", "outside")
NEWS_BUCKETS = ("unknown_unqualified_calendar",)
SCHEMA = "aidy.market_regime_asof.v1"


def _sha(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fraction(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")


def _pct(successes: int, sample_size: int) -> str:
    return format((Decimal(100) * successes / sample_size).quantize(
        CENT, rounding=ROUND_HALF_UP
    ), "f")


@dataclass(frozen=True)
class RegimePolicy:
    lookback_closed_m5_returns: int = 12
    trend_efficiency_min: Decimal = Decimal("0.60")
    range_efficiency_max: Decimal = Decimal("0.35")
    low_vol_mean_abs_return_bps: Decimal = Decimal(3)
    high_vol_mean_abs_return_bps: Decimal = Decimal(10)
    min_validation_signals_per_bucket: int = 12
    # These are policy scenarios, not fitted historical quantile thresholds.

    def validate(self) -> None:
        if (type(self.lookback_closed_m5_returns) is not int
                or not 6 <= self.lookback_closed_m5_returns <= 24
                or type(self.min_validation_signals_per_bucket) is not int
                or not 10 <= self.min_validation_signals_per_bucket <= 100):
            raise ValueError("fixed causal window and support threshold required")
        decimals = (
            self.trend_efficiency_min, self.range_efficiency_max,
            self.low_vol_mean_abs_return_bps, self.high_vol_mean_abs_return_bps,
        )
        if any(not isinstance(x, Decimal) or not x.is_finite() for x in decimals):
            raise ValueError("fixed finite exact Decimal thresholds required")
        if not (Decimal(0) <= self.range_efficiency_max
                < self.trend_efficiency_min <= Decimal(1)
                and Decimal(0) < self.low_vol_mean_abs_return_bps
                < self.high_vol_mean_abs_return_bps):
            raise ValueError("non-overlapping ex-ante regime boundaries required")


@dataclass(frozen=True)
class DecisionRegime:
    decision_utc: str
    last_closed_bar_available_utc: str
    first_window_close_available_utc: str
    trend: str
    volatility: str
    utc_session: str
    news: str
    directional_efficiency: str
    mean_absolute_five_minute_return_bps: str
    model_prediction_direction: int
    two_bar_future_bid_change: str
    model_correct_sign: bool
    always_positive_correct_sign: bool

    def wire(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RegimeBucket:
    dimension: str
    label: str
    validation_signals: int
    state: str
    direction_correct: int | None
    naive_always_positive_correct: int | None
    model_direction_hit_rate_percent: str | None
    naive_direction_hit_rate_percent: str | None
    source_quality: str = "retrospective_bid_close_sign_only_no_trading_pnl"

    def wire(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MarketRegimeAudit:
    schema: str
    source_input_sha256: str
    source_archive_sha256: tuple[str, ...]
    development_sha256: str
    day26_fold_evidence_sha256: str
    day26_model_sha256: str
    day26_holdout_commit_sha256: str
    regime_policy_sha256: str
    decisions_sha256: str
    fully_closed_m5_available: int
    development_labeled_samples: int
    evaluated_walkforward_predictions: int
    excluded_initial_unwarmed_decisions: int
    sealed_holdout_decisions_consumed: int
    evaluated: tuple[DecisionRegime, ...]
    breakdowns: tuple[RegimeBucket, ...]
    news_source_qualified: bool = False
    actual_bid_ask_execution_costs_verified: bool = False
    strategy_alpha_qualified: bool = False
    initial_source_type: str = "retrospective_histdata_bid_closed_m5"
    validation_type: str = "day26_expanding_chronological_development_folds"

    def to_wire(self) -> dict:
        value = asdict(self)
        value["evaluated"] = [x.wire() for x in self.evaluated]
        value["breakdowns"] = [x.wire() for x in self.breakdowns]
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"))


def _session(instant: datetime) -> str:
    london = instant.astimezone(ZoneInfo("Europe/London"))
    ny = instant.astimezone(ZoneInfo("America/New_York"))
    london_open = 8 <= london.hour < 17
    ny_open = 8 <= ny.hour < 17
    if london_open and ny_open:
        return "london_new_york_overlap"
    if london_open:
        return "london"
    if ny_open:
        return "new_york"
    return "outside"


def _classify(bars: tuple[ClosedBar, ...], index: int,
              policy: RegimePolicy) -> tuple[str, str, str, str, str, str]:
    """Pure as-of regime function: cannot observe bars after `index`."""
    n = policy.lookback_closed_m5_returns
    if index < n:
        raise ValueError("insufficient past closed bars for regime label")
    window = bars[index - n:index + 1]
    closes = [x.close for x in window]
    if len(window) != n + 1 or any(
        x.available_at_utc > bars[index].available_at_utc for x in window
    ):
        raise ValueError("future quote used by regime")
    total_movement = sum(
        (abs(cur - prev) for prev, cur in zip(closes[:-1], closes[1:], strict=False)),
        Decimal(0),
    )
    efficiency = (
        abs(closes[-1] - closes[0]) / total_movement
        if total_movement else Decimal(0)
    )
    if efficiency >= policy.trend_efficiency_min and closes[-1] != closes[0]:
        trend = "trend_up" if closes[-1] > closes[0] else "trend_down"
    elif efficiency <= policy.range_efficiency_max:
        trend = "range"
    else:
        trend = "transitional"
    bps = sum((
        abs(cur - prev) / prev * Decimal(10000)
        for prev, cur in zip(closes[:-1], closes[1:], strict=False)
    ), Decimal(0)) / Decimal(n)
    vol = (
        "low" if bps < policy.low_vol_mean_abs_return_bps
        else "high" if bps >= policy.high_vol_mean_abs_return_bps
        else "normal"
    )
    return (
        trend, vol, _session(bars[index].available_at_utc),
        "unknown_unqualified_calendar",
        _fraction(efficiency), _fraction(bps),
    )


def analyze_day26_development_regimes(
    history: ReadResult, *,
    study: SealedOOS,
    policy: RegimePolicy | None = None,
) -> MarketRegimeAudit:
    """Report label strata ONLY for the already-predeclared Day26 dev folds.

    The as-of feature uses no holdout outcomes. This means zero final holdout
    retesting, avoiding inflation of the one-time Day26 held-out evidence.
    """
    p = policy if policy is not None else RegimePolicy()
    p.validate()
    if not isinstance(study, SealedOOS):
        raise ValueError("Day26 qualified study required")  # noqa: TRY004
    review = study.review_development()
    if (history.input_digest != study.source_sha256
            or history.source_archive_hashes != review_source_archives(history)):
        raise ValueError("source/provenance mismatch between Day26 study and regimes")
    bars = history.bars
    all_dev = study.development()
    if (len(bars) < 110
            or not all_dev
            or any(b.price_basis != "bid" for b in bars)):
        raise ValueError("source not qualified for bid-only M5 regimes")

    lookup = {s.decision_at_utc: i for i, s in enumerate(all_dev)}
    if len(lookup) != len(all_dev):
        raise ValueError("duplicate Day26 decision timestamps")
    decisions: list[DecisionRegime] = []
    seen: set[str] = set()
    skipped = 0
    for fold in review.folds:
        for i in range(len(all_dev)):
            s = all_dev[i]
            if not (fold.validation_first_decision_utc <= s.decision_at_utc
                    <= fold.validation_last_decision_utc):
                continue
            if s.decision_at_utc in seen:
                raise ValueError("fold validation overlap")
            seen.add(s.decision_at_utc)
            pos = lookup[s.decision_at_utc]
            if pos < p.lookback_closed_m5_returns:
                skipped += 1
                continue
            bar = bars[pos]
            utc = bar.available_at_utc.isoformat().replace("+00:00", "Z")
            if utc != s.decision_at_utc or s.feature_available_at_utc != utc:
                raise ValueError("regime time does not match fully closed signal bar")
            if s.outcome_available_at_utc <= utc:
                raise ValueError("future label is not outcome-matured")
            trend, vol, session, news, er, bps = _classify(bars, pos, p)
            correct = (
                (s.two_bar_future_change > 0) == (fold.train_only_direction == 1)
            )
            decisions.append(DecisionRegime(
                utc, utc,
                bars[pos - p.lookback_closed_m5_returns].available_at_utc.isoformat().replace("+00:00", "Z"),
                trend, vol, session, news, er, bps,
                fold.train_only_direction,
                format(s.two_bar_future_change, "f"),
                correct, s.two_bar_future_change > 0,
            ))
    expected_evaluated = sum(f.validation_count for f in review.folds)
    if len(seen) != expected_evaluated or not decisions:
        raise ValueError("not every Day26 validation decision was joined uniquely")
    breakdowns: list[RegimeBucket] = []
    for dim, labels, attr in (
        ("trend", TREND_BUCKETS, "trend"),
        ("volatility", VOL_BUCKETS, "volatility"),
        ("session", SESSION_BUCKETS, "utc_session"),
        ("news", NEWS_BUCKETS, "news"),
    ):
        count = 0
        for label in labels:
            members = [x for x in decisions if getattr(x, attr) == label]
            n = len(members)
            count += n
            if dim == "news":
                state = "SOURCE_UNAVAILABLE_NO_NEWS_CONCLUSIONS"
            elif n < p.min_validation_signals_per_bucket:
                state = "INSUFFICIENT_SAMPLE"
            else:
                state = "MEASURED_RETROSPECTIVE_DIRECTION_ONLY"
            eligible = state == "MEASURED_RETROSPECTIVE_DIRECTION_ONLY"
            correct = sum(x.model_correct_sign for x in members) if eligible else None
            naive = sum(x.always_positive_correct_sign for x in members) if eligible else None
            breakdowns.append(RegimeBucket(
                dim, label, n, state, correct, naive,
                _pct(correct, n) if correct is not None else None,
                _pct(naive, n) if naive is not None else None,
            ))
        if count != len(decisions):
            raise ValueError("regime strata do not partition matched validation decisions")
    raw_rows = [r.wire() for r in decisions]
    return MarketRegimeAudit(
        SCHEMA, history.input_digest, history.source_archive_hashes,
        review.development_sha256, review.fold_evidence_sha256,
        MODEL_SHA256, review.holdout_sha256, _sha({
            k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(p).items()
        }), _sha(raw_rows), len(bars), len(all_dev), len(decisions),
        skipped, 0, tuple(decisions), tuple(breakdowns),
    )


def review_source_archives(history: ReadResult) -> tuple[str, ...]:
    if (not history.source_archive_hashes
            or any(len(h) != 64 or any(c not in "0123456789abcdef" for c in h)
                   for h in history.source_archive_hashes)):
        raise ValueError("missing original source SHA provenance")
    return tuple(sorted(set(history.source_archive_hashes)))
