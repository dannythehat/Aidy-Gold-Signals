from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_rates_usd_cross_asset_expert import (
    DEPENDENCY_GROUPS,
    RELATIONSHIP_MINIMUM_N,
    RATES_CROSS_ASSET_EXPERT_VERSION,
    RATES_CROSS_ASSET_GATE_ID,
    build_rates_usd_cross_asset_expert,
)
from aidy.macro_vintages import (
    AlfredSnapshot,
    SERIES_DFII10,
    SERIES_DGS10,
    SERIES_DGS2,
    SERIES_T10YIE,
    build_version_history,
)
from aidy.policy_cross_asset import (
    SERIES_BROAD_USD,
    SERIES_ES,
    SERIES_EURUSD,
    SERIES_GC,
    SERIES_SI,
    SERIES_SR3,
    SERIES_USDJPY,
    SERIES_VIX,
    SERIES_ZN,
    SERIES_ZQ,
    build_observation,
)

AS_OF = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
SHA = "a" * 64


def _environment(regime: str = "trend|normal") -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=AS_OF + timedelta(minutes=15),
        session_code="london_new_york_overlap",
        observed_state="neutral",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": "up", "state": "known"},
                    "M15": {"net_close_direction": "up", "state": "known"},
                    "H1": {"net_close_direction": "up", "state": "known"},
                    "H4": {"net_close_direction": "up", "state": "known"},
                    "D1": {"net_close_direction": "up", "state": "known"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "within_recent_distribution",
                "five_minute_range_state": "normal_range",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "2"},
                    "15m": {"direction": "up", "return_bps": "4"},
                    "60m": {"direction": "up", "return_bps": "6"},
                },
            },
            "volatility": {
                "state": "normal",
                "jump_continuous": {"state": "continuous_dominant"},
            },
            "scheduled_event_risk": {
                "state": "known",
                "timing_state": "outside_near_event_window",
            },
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "fresh",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": regime},
    )


def _rate_records() -> list[dict]:
    snapshots: list[AlfredSnapshot] = []
    starts = {
        SERIES_DGS2: Decimal("3.80"),
        SERIES_DGS10: Decimal("4.10"),
        SERIES_DFII10: Decimal("1.70"),
        SERIES_T10YIE: Decimal("2.40"),
    }
    start_day = date(2026, 8, 15)
    for series_id, base in starts.items():
        for index in range(25):
            day = start_day + timedelta(days=index)
            snapshots.append(
                AlfredSnapshot(
                    series_id=series_id,
                    vintage_date=day,
                    observation_start=day,
                    observation_end=day,
                    values=((day, str(base + Decimal(index) * Decimal("0.01"))),),
                    source_url=f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={series_id}",
                    source_sha256=SHA,
                )
            )
    return build_version_history(snapshots)


def _obs(
    series_id: str,
    value: str,
    *,
    delta: timedelta,
    first_capture: bool = True,
    stale: bool = False,
) -> dict:
    observed = AS_OF - delta
    return build_observation(
        series_id=series_id,
        value=value,
        observed_at=observed,
        first_observed_at=observed + timedelta(seconds=2),
        source_snapshot_digest=SHA,
        provenance_class="first_observed_capture" if first_capture else "retrospective_history",
        pit_reconstructable=True,
        staleness_state="stale" if stale else "fresh_for_declared_horizon",
    )


def _cross_observations() -> list[dict]:
    values = {
        SERIES_ZQ: Decimal("95.5"),
        SERIES_SR3: Decimal("96.0"),
        SERIES_ZN: Decimal("112"),
        SERIES_GC: Decimal("3650"),
        SERIES_SI: Decimal("42"),
        SERIES_ES: Decimal("6500"),
        SERIES_BROAD_USD: Decimal("119"),
        SERIES_EURUSD: Decimal("1.18"),
        SERIES_USDJPY: Decimal("146"),
        SERIES_VIX: Decimal("18"),
    }
    rows: list[dict] = []
    for series_id, current in values.items():
        rows.extend(
            [
                _obs(series_id, str(current - Decimal("1.5")), delta=timedelta(days=2)),
                _obs(series_id, str(current - Decimal("0.8")), delta=timedelta(days=1)),
                _obs(series_id, str(current - Decimal("0.3")), delta=timedelta(minutes=60)),
                _obs(series_id, str(current - Decimal("0.1")), delta=timedelta(minutes=15)),
                _obs(series_id, str(current), delta=timedelta(minutes=1)),
            ]
        )
    return rows


def _relationship_history(
    *,
    regime: str = "trend|normal",
    flip_usd: bool = False,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(RELATIONSHIP_MINIMUM_N + 12):
        x = Decimal(index % 7 + 1)
        usd_change = x
        real_change = x * Decimal("0.8")
        if flip_usd and index >= (RELATIONSHIP_MINIMUM_N + 12) // 2:
            gold = -usd_change * Decimal("2")
        else:
            gold = usd_change * Decimal("2") + Decimal(index % 2) * Decimal("0.1")
        rows.append(
            {
                "independent_episode_id": f"episode-{index}",
                "first_observed_at": (
                    AS_OF - timedelta(days=(RELATIONSHIP_MINIMUM_N + 20 - index))
                ).isoformat(),
                "pit_reconstructable": True,
                "regime": regime,
                "gold_return_bps": str(gold),
                "series_changes_bps": {
                    SERIES_BROAD_USD: str(usd_change),
                    SERIES_DFII10: str(real_change),
                    SERIES_DGS10: str(x * Decimal("0.6")),
                    SERIES_DGS2: str(x * Decimal("0.5")),
                    SERIES_T10YIE: str(x * Decimal("0.1")),
                    SERIES_EURUSD: str(-usd_change),
                    SERIES_USDJPY: str(usd_change * Decimal("0.7")),
                    SERIES_ZN: str(-real_change),
                    SERIES_ZQ: str(x * Decimal("0.2")),
                    SERIES_SR3: str(x * Decimal("0.25")),
                    SERIES_SI: str(gold * Decimal("0.6")),
                    SERIES_ES: str(x * Decimal("0.4")),
                    SERIES_VIX: str(-x * Decimal("0.3")),
                },
            }
        )
    return rows


def _build(
    *,
    relationship_rows: list[dict[str, object]] | None = None,
    cross_rows: list[dict] | None = None,
    current_gold_return_bps: str = "5",
) -> dict:
    return build_rates_usd_cross_asset_expert(
        global_environment=_environment(),
        rates_version_records=_rate_records(),
        cross_asset_observations=cross_rows or _cross_observations(),
        relationship_history_rows=relationship_rows or _relationship_history(),
        current_gold_return_bps=current_gold_return_bps,
    )


def test_build16_context_only_and_no_forever_signs() -> None:
    result = _build()
    packet = result["expert_packet"]

    assert result["expert_version"] == RATES_CROSS_ASSET_EXPERT_VERSION
    assert packet["gate_id"] == RATES_CROSS_ASSET_GATE_ID
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False
    assert packet["internal_conviction"] is None
    assert verify_expert_gate_packet(packet)

    policy = result["sign_policy"]
    assert policy["hardcoded_forever_signs"] is False
    assert policy["gold_usd_fixed_inverse"] is False
    assert policy["gold_real_yield_fixed_inverse"] is False
    assert policy["regime_specific_signs_allowed"] is True
    assert policy["sign_flip_state_allowed"] is True


def test_build16_positive_gold_usd_and_real_yield_regime_is_representable() -> None:
    result = _build()
    rel = result["relationships"]["relationships"]

    assert rel[SERIES_BROAD_USD]["state"] == "known"
    assert rel[SERIES_BROAD_USD]["relationship_sign"] == "positive"
    assert Decimal(rel[SERIES_BROAD_USD]["correlation"]) > Decimal("0.9")
    assert Decimal(rel[SERIES_BROAD_USD]["beta"]) > 0

    assert rel[SERIES_DFII10]["state"] == "known"
    assert rel[SERIES_DFII10]["relationship_sign"] == "positive"
    assert Decimal(rel[SERIES_DFII10]["correlation"]) > Decimal("0.9")
    assert Decimal(rel[SERIES_DFII10]["beta"]) > 0


def test_build16_sign_flip_is_representable_not_overwritten_by_fixed_rule() -> None:
    result = _build(relationship_rows=_relationship_history(flip_usd=True))
    usd = result["relationships"]["relationships"][SERIES_BROAD_USD]

    assert usd["state"] == "known"
    assert usd["stability_state"] == "sign_flip"
    assert usd["hardcoded_sign_used"] is False


def test_build16_daily_cash_rates_never_masquerade_as_intraday_reaction() -> None:
    result = _build()
    rates = result["daily_rates"]

    assert rates["stale_daily_cannot_be_intraday_reaction"] is True
    assert rates["dependency_policy"]["same_mechanism_components_not_independent"] is True
    assert rates["dependency_policy"]["independent_confirmation_units"] == 1

    for series_id in (SERIES_DGS2, SERIES_DGS10, SERIES_DFII10, SERIES_T10YIE):
        item = rates["series"][series_id]
        assert item["state"] == "known"
        assert item["source_frequency"] == "daily"
        assert item["intraday_reaction_allowed"] is False
        assert item["intraday_change_15m"] is None
        assert item["intraday_change_60m"] is None
        assert item["change_1obs_bps"] is not None
        assert item["change_5obs_bps"] is not None
        assert item["change_20obs_bps"] is not None


def test_build16_daily_usd_fx_vix_context_is_not_intraday() -> None:
    result = _build()
    series = result["cross_asset_current"]["series"]

    for series_id in (SERIES_BROAD_USD, SERIES_EURUSD, SERIES_USDJPY, SERIES_VIX):
        item = series[series_id]
        assert item["state"] == "known"
        assert item["source_frequency"] == "daily_or_official_fix"
        assert item["intraday_reaction_allowed"] is False
        assert item["change_15m_bps"] is None
        assert item["change_60m_bps"] is None
        assert item["intraday_unavailable_reason"] == "official_daily_context_not_intraday"


def test_build16_fresh_exchange_timestamped_futures_can_have_intraday_changes() -> None:
    result = _build()
    series = result["cross_asset_current"]["series"]

    for series_id in (SERIES_ZQ, SERIES_SR3, SERIES_ZN, SERIES_GC, SERIES_SI, SERIES_ES):
        item = series[series_id]
        assert item["state"] == "known"
        assert item["source_frequency"] == "intraday"
        assert item["intraday_reaction_allowed"] is True
        assert item["change_15m_bps"] is not None
        assert item["change_60m_bps"] is not None


def test_build16_stale_intraday_future_cannot_claim_intraday_reaction() -> None:
    rows = _cross_observations()
    rows = [
        row
        for row in rows
        if not (
            row["series_id"] == SERIES_ZN
            and row["observed_at_utc"].startswith((AS_OF - timedelta(minutes=1)).date().isoformat())
        )
    ]
    rows.append(_obs(SERIES_ZN, "112", delta=timedelta(minutes=1), stale=True))
    result = _build(cross_rows=rows)
    zn = result["cross_asset_current"]["series"][SERIES_ZN]

    assert zn["state"] == "known"
    assert zn["intraday_reaction_allowed"] is False
    assert zn["change_15m_bps"] is None
    assert zn["change_60m_bps"] is None
    assert zn["intraday_unavailable_reason"] == "stale_or_unqualified_intraday_observation"


def test_build16_retrospective_current_cross_asset_is_not_decision_input() -> None:
    rows = _cross_observations()
    rows.append(
        _obs(
            SERIES_SI,
            "100",
            delta=timedelta(seconds=30),
            first_capture=False,
        )
    )
    result = _build(cross_rows=rows)
    si = result["cross_asset_current"]["series"][SERIES_SI]

    assert si["decision_input_allowed"] is False


def test_build16_same_mechanism_series_are_dependency_tagged() -> None:
    result = _build()
    groups = result["cross_asset_current"]["dependency_groups"]

    assert DEPENDENCY_GROUPS[SERIES_DGS2] == "rates_curve"
    assert DEPENDENCY_GROUPS[SERIES_DGS10] == "rates_curve"
    assert DEPENDENCY_GROUPS[SERIES_DFII10] == "rates_curve"
    assert DEPENDENCY_GROUPS[SERIES_T10YIE] == "rates_curve"

    assert set(groups["usd_mechanism"]) == {
        SERIES_BROAD_USD,
        SERIES_EURUSD,
        SERIES_USDJPY,
    }
    assert set(groups["policy_path"]) == {SERIES_SR3, SERIES_ZQ}
    assert result["cross_asset_current"]["same_mechanism_series_not_independent_votes"] is True
    assert result["divergence_breadth"]["same_group_components_count_once"] is True


def test_build16_breadth_counts_dependency_groups_not_raw_series_count() -> None:
    result = _build()
    breadth = result["divergence_breadth"]

    raw_candidates = sum(
        1
        for item in result["relationships"]["relationships"].values()
        if item["state"] == "known"
    )
    assert breadth["independent_dependency_group_count"] < raw_candidates
    groups = [row["dependency_group"] for row in breadth["group_representatives"]]
    assert len(groups) == len(set(groups))


def test_build16_divergence_uses_learned_relationship_not_fixed_sign() -> None:
    result = _build(current_gold_return_bps="-5")
    divergences = result["divergence_breadth"]["divergences"]

    assert result["divergence_breadth"]["divergence_state"] == "present"
    assert any(row["series_id"] == SERIES_BROAD_USD for row in divergences)
    assert any(row["series_id"] == SERIES_DFII10 for row in divergences)


def test_build16_future_relationship_rows_are_excluded() -> None:
    rows = _relationship_history()
    rows.append(
        {
            "independent_episode_id": "future",
            "first_observed_at": (AS_OF + timedelta(minutes=1)).isoformat(),
            "pit_reconstructable": True,
            "regime": "trend|normal",
            "gold_return_bps": "-999",
            "series_changes_bps": {SERIES_BROAD_USD: "999"},
        }
    )
    result = _build(relationship_rows=rows)
    usd = result["relationships"]["relationships"][SERIES_BROAD_USD]

    assert usd["sample_n"] == RELATIONSHIP_MINIMUM_N + 12
    assert usd["relationship_sign"] == "positive"


def test_build16_insufficient_regime_history_remains_unknown() -> None:
    result = _build(relationship_rows=_relationship_history()[:5])
    usd = result["relationships"]["relationships"][SERIES_BROAD_USD]

    assert usd["state"] == "unknown_insufficient_regime_history"
    assert usd["sample_n"] == 5
    assert usd["correlation"] is None
    assert usd["beta"] is None


def test_build16_future_cross_asset_observation_is_ignored() -> None:
    rows = _cross_observations()
    future = build_observation(
        series_id=SERIES_SI,
        value="999",
        observed_at=AS_OF + timedelta(minutes=1),
        first_observed_at=AS_OF + timedelta(minutes=1, seconds=2),
        source_snapshot_digest=SHA,
        provenance_class="first_observed_capture",
        pit_reconstructable=True,
    )
    rows.append(future)
    result = _build(cross_rows=rows)

    assert result["cross_asset_current"]["series"][SERIES_SI]["value"] != "999"


def test_build16_future_rate_vintage_is_ignored() -> None:
    records = _rate_records()
    future_snapshot = AlfredSnapshot(
        series_id=SERIES_DFII10,
        vintage_date=AS_OF.date() + timedelta(days=1),
        observation_start=AS_OF.date() + timedelta(days=1),
        observation_end=AS_OF.date() + timedelta(days=1),
        values=((AS_OF.date() + timedelta(days=1), "99"),),
        source_url="https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=DFII10",
        source_sha256=SHA,
    )
    records.extend(build_version_history([future_snapshot]))
    result = build_rates_usd_cross_asset_expert(
        global_environment=_environment(),
        rates_version_records=records,
        cross_asset_observations=_cross_observations(),
        relationship_history_rows=_relationship_history(),
        current_gold_return_bps="5",
    )

    assert result["daily_rates"]["series"][SERIES_DFII10]["value_percent"] != "99"


def test_build16_environment_specific_trust_scope_is_created() -> None:
    result = _build()
    scope_types = {scope["scope_type"] for scope in result["trust_scopes"]}

    assert "mini_exact" in scope_types
    assert "mini_reduced_relationship_regime" in scope_types
    assert "mini_reduced_rates_usd_context" in scope_types
    assert "mini_reduced_cross_asset_context" in scope_types
