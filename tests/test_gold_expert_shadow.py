from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_expert_shadow import (
    EXPECTED_GATES,
    GOLD_EXPERT_SCORECARD_VERSION,
    GOLD_EXPERT_SHADOW_VERSION,
    _unknown_context_result,
)

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 9, 21, 16, 10, tzinfo=UTC)
TARGET = datetime(2026, 9, 21, 16, 15, tzinfo=UTC)


def _environment() -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=TARGET,
        session_code="new_york",
        observed_state="bullish",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": "up", "state": "known"},
                    "M15": {"net_close_direction": "up", "state": "known"},
                    "H1": {"net_close_direction": "down", "state": "known"},
                    "H4": {"net_close_direction": "up", "state": "known"},
                    "D1": {"net_close_direction": "up", "state": "known"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "normal",
                "five_minute_range_state": "normal",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "2.5"},
                    "15m": {"direction": "up", "return_bps": "4.5"},
                    "60m": {"direction": "down", "return_bps": "-3.0"},
                },
            },
            "volatility": {
                "state": "normal",
                "jump_continuous": {"state": "continuous_dominant"},
            },
            "scheduled_event_risk": {
                "state": "unknown",
                "timing_state": "unknown",
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
        regime={"compound_regime_key": "mixed|normal"},
    )


def test_build24_registry_covers_all_fifteen_expert_gates_once() -> None:
    assert GOLD_EXPERT_SHADOW_VERSION == "aidy_gold_expert_shadow_v1"
    assert GOLD_EXPERT_SCORECARD_VERSION == "aidy_gold_expert_scorecard_v1"
    assert len(EXPECTED_GATES) == 15
    assert len(set(EXPECTED_GATES)) == 15
    assert {
        "m5_price_structure_expert",
        "m15_price_structure_expert",
        "h1_price_structure_expert",
        "h4_price_structure_expert",
        "d1_context_expert",
        "price_location_expert",
        "momentum_impulse_expert",
        "liquidity_reclaim_expert",
        "volatility_jump_expert",
        "session_participation_expert",
        "macro_event_expert",
        "rates_usd_cross_asset_expert",
        "futures_microstructure_expert",
        "news_movement_mechanism_expert",
        "analogue_episode_expert",
    } == set(EXPECTED_GATES)


def test_disconnected_context_gate_is_explicit_unknown_and_cannot_vote() -> None:
    result = _unknown_context_result(
        gate_id="news_movement_mechanism_expert",
        gate_version="aidy_gold_news_movement_mechanism_expert_v1",
        dependency_family="news_mechanism",
        global_environment=_environment(),
    )
    packet = result["expert_packet"]
    assert verify_expert_gate_packet(packet)
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False
    assert packet["internal_conviction"] is None
    assert len(packet["subcalculators"]) == 1
    calculator = packet["subcalculators"][0]
    assert calculator["state"] == "unavailable"
    assert calculator["vote"] == "unknown"
    assert calculator["scoreable"] is False
    assert result["runtime_availability"] == "explicit_unknown"
    assert result["future_values_used"] is False
    assert result["live_money_execution_allowed"] is False


def test_build24_schema_is_prospective_immutable_and_non_executable() -> None:
    sql = (
        ROOT / "migrations" / "d1" / "0027_gold_expert_shadow_scorecard.sql"
    ).read_text(encoding="utf-8")
    assert "aidy_gold_expert_shadow_runtime_state" in sql
    assert "activated_at_utc TEXT NOT NULL" in sql
    assert "prospective_only INTEGER NOT NULL DEFAULT 1" in sql
    assert "aidy_gold_expert_shadow_cycles" in sql
    assert "aidy_gold_expert_gate_snapshots" in sql
    assert "aidy_gold_expert_subcalculator_snapshots" in sql
    assert "aidy_gold_meta_view_results" in sql
    assert "aidy_gold_expert_shadow_sync_health" in sql
    assert "future_values_used INTEGER NOT NULL DEFAULT 0" in sql
    assert sql.count("live_money_execution_allowed INTEGER NOT NULL DEFAULT 0") >= 6
    assert sql.count("formal_forward_authority INTEGER NOT NULL DEFAULT 0") >= 3


def test_runtime_never_backfills_pre_activation_cycles() -> None:
    source = (ROOT / "src" / "aidy" / "gold_expert_shadow.py").read_text(
        encoding="utf-8"
    )
    creation = source[source.index("async def create_new_cycles"):source.index(
        "async def _insert_expert_results"
    )]
    assert "v.decided_at_utc>=?" in creation
    assert "activated.isoformat()" in creation
    assert "LEFT JOIN aidy_gold_expert_shadow_cycles" in creation
    assert "s.cycle_view_id IS NULL" in creation
    assert "retrospective" not in creation.lower()
    assert "backfill" not in creation.lower()


def test_restart_idempotency_is_structural_not_best_effort() -> None:
    migration = (
        ROOT / "migrations" / "d1" / "0027_gold_expert_shadow_scorecard.sql"
    ).read_text(encoding="utf-8")
    source = (ROOT / "src" / "aidy" / "gold_expert_shadow.py").read_text(
        encoding="utf-8"
    )
    assert "singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1)" in migration
    assert "ON CONFLICT(singleton_id) DO NOTHING" in source
    assert "ON CONFLICT(cycle_view_id) DO NOTHING" in source
    assert "ON CONFLICT(cycle_view_id,gate_id) DO NOTHING" in source
    assert "ON CONFLICT(cycle_view_id,gate_id,calculator_id) DO NOTHING" in source
    assert source.count("ON CONFLICT(result_id,scope_key) DO NOTHING") == 1


def test_outcomes_are_scored_only_from_existing_post_window_cycle_outcomes() -> None:
    source = (ROOT / "src" / "aidy" / "gold_expert_shadow.py").read_text(
        encoding="utf-8"
    )
    scoring = source[source.index("async def score_resolved_cycles"):source.index(
        "async def scorecard_snapshot"
    )]
    assert "JOIN aidy_gold_cycle_outcomes o" in scoring
    assert "LEFT JOIN aidy_gold_meta_view_results r" in scoring
    assert "r.cycle_view_id IS NULL" in scoring
    assert "score_expert_packet" in source
    assert "score_directional_outcome" in scoring
    assert "UPDATE aidy_gold_expert_shadow_cycles" not in scoring
    assert "UPDATE aidy_gold_expert_gate_snapshots" not in scoring


def test_cron_sets_activation_before_cycle_freeze_then_scores_shadow_after() -> None:
    wrapper = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    scheduled = wrapper[wrapper.index("async def scheduled"):wrapper.index(
        "async def queue"
    )]
    activation = scheduled.index("_activate_gold_expert_shadow_best_effort")
    cycle = scheduled.index("_sync_gold_cycle_memory_best_effort")
    shadow_sync = scheduled.index("_sync_gold_expert_shadow_best_effort")
    assert activation < cycle < shadow_sync
    assert "gold_expert_shadow_version" in wrapper
    assert "gold_expert_scorecard_version" in wrapper


def test_scorecard_is_read_only_provider_context_not_a_decision_input() -> None:
    provider = (ROOT / "src" / "aidy" / "provider_context_api.py").read_text(
        encoding="utf-8"
    )
    forward = (ROOT / "src" / "aidy" / "private_forward_context.py").read_text(
        encoding="utf-8"
    )
    assert 'gold_state["expert_shadow_scorecard"]' in provider
    assert "D1GoldExpertShadowStore" in provider
    assert "expert_shadow_scorecard" not in forward
    assert "D1GoldExpertShadowStore" not in forward


def test_exact_snapshot_helper_preserves_pit_admission_boundary() -> None:
    forward = (ROOT / "src" / "aidy" / "private_forward_context.py").read_text(
        encoding="utf-8"
    )
    helper = forward[forward.index("async def load_private_forward_snapshot_bundle"):forward.index(
        "async def build_private_forward_decision_inputs"
    )]
    assert "_snapshot(d1, snapshot_id)" in helper
    assert "_decision_candles(d1, as_of=as_of)" in helper
    assert '"future_values_used": False' in helper
    assert '"live_money_execution_allowed": False' in helper


def test_scorecard_keeps_environment_trust_dependency_calibration_and_time_visible() -> None:
    source = (ROOT / "src" / "aidy" / "gold_expert_shadow.py").read_text(
        encoding="utf-8"
    )
    scorecard = source[source.index("async def scorecard_snapshot"):source.index(
        "async def ensure_gold_expert_shadow_activation"
    )]
    for token in (
        '"mini_environment"',
        '"sample_n"',
        '"raw_reliability"',
        '"shrunk_reliability"',
        '"net_score"',
        '"recent_accuracy"',
        '"drift"',
        '"uncertainty"',
        '"dependency_adjustment"',
        '"calibration"',
        '"last_score_time_utc"',
        '"latest_aidy_view"',
    ):
        assert token in scorecard
    assert '"formal_forward_authority": False' in scorecard
    assert '"live_money_execution_allowed": False' in scorecard


def test_activation_timestamp_is_strictly_pre_outcome_and_restart_safe() -> None:
    source = (ROOT / "src" / "aidy" / "gold_expert_shadow.py").read_text(
        encoding="utf-8"
    )
    ensure = source[source.index("async def ensure_activation"):source.index(
        "async def _environment_for_cycle"
    )]
    assert "INSERT INTO aidy_gold_expert_shadow_runtime_state" in ensure
    assert "ON CONFLICT(singleton_id) DO NOTHING" in ensure
    assert "SELECT activated_at_utc" in ensure
    assert "UPDATE" not in ensure


def test_no_live_money_or_formal_forward_authority_is_created() -> None:
    source = (ROOT / "src" / "aidy" / "gold_expert_shadow.py").read_text(
        encoding="utf-8"
    )
    assert '"formal_forward_authority": False' in source
    assert '"live_money_execution_allowed": False' in source
    assert "formal_forward_evidence_created" not in source
    assert "MetaAPI" not in source
    assert "Vantage" not in source
    assert "execute_trade" not in source
