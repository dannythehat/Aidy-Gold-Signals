"""Canonical StrategySpec v1 parser contract tests. No strategy is executed."""
import copy
import json
from pathlib import Path

import pytest

from aidy.strategy_lab_spec import SCHEMA_VERSION, StrategySpec

FIXTURE = (
    Path(__file__).parents[1] / "research" / "strategy_lab"
    / "fixtures" / "strategy_spec_v1_sample.json"
)


def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def patch(path, value):
    data = copy.deepcopy(sample())
    item = data
    for key in path[:-1]:
        item = item[key]
    item[path[-1]] = value
    return data


def test_full_spec_load_and_canonical_wire_round_trip():
    loaded = StrategySpec.from_wire(sample())
    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.market.symbol == "XAUUSD"
    assert loaded.long.entry.enabled and not loaded.short.entry.enabled
    assert loaded.long.exit.stop_loss.value == 120
    assert loaded.long.exit.take_profit.value == 240
    assert loaded.sizing.risk_percent_equity == 1
    assert loaded.warmup_closed_bars == 50
    assert len(loaded.sessions.allowed) == 5
    as_wire = loaded.to_wire()
    assert as_wire == sample()
    assert StrategySpec.from_json(loaded.to_json()) == loaded
    assert StrategySpec.from_json(loaded.to_json()).to_json() == loaded.to_json()


def test_canonical_json_does_not_include_executable_code_or_verified_returns():
    spec = StrategySpec.from_wire(sample())
    serialized = spec.to_wire()
    assert serialized["origin"]["claimed_performance"] is None
    assert "verified_performance" not in serialized
    assert serialized["execution"]["entry_execution"] == "next_tradable_quote"


@pytest.mark.parametrize(("path", "value"), [
    (("schema_version",), "v999"),
    (("strategy_id",), "Non Canonical ID"),
    (("strategy_id",), ""),
    (("revision",), True),
    (("revision",), 0),
    (("candidate_type",), "claimed_profitable"),
    (("origin", "author"), ""),
    (("origin", "source_language"), "javascript"),
    (("origin", "source_sha256"), "not-a-hash"),
    (("origin", "source_url"), "file:///etc/passwd"),
    (("origin", "source_snapshot_ref"), 99),
    (("origin", "licence"), ""),
    (("market", "symbol"), "EURUSD"),
    (("market", "signal_timeframe"), "M3"),
    (("market", "source_clock"), "America/New_York"),
    (("market", "price_basis"), "unknown"),
    (("warmup_closed_bars",), 0),
    (("warmup_closed_bars",), True),
    (("indicators", 0, "id"), "Bad-MA"),
    (("indicators", 0, "kind"), "EVAL"),
    (("indicators", 0, "period"), 0),
    (("indicators", 0, "price_field"), "future_close"),
    (("indicators", 0, "additional_parameters"), {"bad-param": "4"}),
    (("long", "entry", "combination"), "exec"),
    (("long", "entry", "enabled"), "yes"),
    (("long", "entry", "predicates", 0, "operator"), "eval"),
    (("long", "entry", "predicates", 0, "left", "reference"), "missing_indicator"),
    (("long", "entry", "predicates", 0, "left", "offset_closed_bars"), -1),
    (("long", "entry", "predicates", 0, "left", "offset_closed_bars"), True),
    (("long", "exit", "stop_loss", "mode"), "python"),
    (("long", "exit", "stop_loss", "value"), "NaN"),
    (("long", "exit", "stop_loss", "value"), "-10"),
    (("long", "exit", "stop_loss", "value"), 1.01),
    (("sessions", "timezone"), "Europe/Sofia"),
    (("sessions", "allowed", 0, "weekday"), 7),
    (("sessions", "allowed", 0, "start_hhmm"), "07:00:00"),
    (("sessions", "allowed", 0, "end_hhmm"), "07:00"),
    (("sessions", "excluded_dates"), ["2025-02-30"]),
    (("sizing", "mode"), "guess"),
    (("sizing", "risk_percent_equity"), "101"),
    (("sizing", "risk_percent_equity"), 1.0),
    (("portfolio", "max_positions"), 0),
    (("portfolio", "allow_hedging"), 0),
    (("portfolio", "max_total_risk_percent"), "101"),
    (("execution", "signal_evaluation"), "forming_bar"),
    (("execution", "entry_execution"), "signal_close"),
])
def test_invalid_spec_fails_closed(path, value):
    with pytest.raises(ValueError):
        StrategySpec.from_wire(patch(path, value))


def test_unknown_or_missing_root_field_fails_closed():
    data = sample()
    data["arbitrary_python_code"] = "import os"
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)
    data = sample()
    del data["sizing"]
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)


def test_unknown_nested_field_fails_closed():
    data = sample()
    data["origin"]["made_up_field"] = True
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)


def test_duplicate_source_json_keys_rejected():
    text = FIXTURE.read_text(encoding="utf-8").replace(
        '"revision": 1,', '"revision": 1, "revision": 42,'
    )
    with pytest.raises(ValueError, match="duplicate JSON"):
        StrategySpec.from_json(text)


def test_disabled_long_with_rules_rejected():
    with pytest.raises(ValueError):
        StrategySpec.from_wire(patch(("long", "entry", "enabled"), False))


def test_enabled_short_without_rules_rejected():
    with pytest.raises(ValueError):
        StrategySpec.from_wire(patch(("short", "entry", "enabled"), True))


def test_enabled_side_never_silently_translated_into_an_exit():
    data = sample()
    data["short"]["exit"]["stop_loss"] = {
        "mode": "ticks", "value": "20", "indicator_id": None
    }
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)


def test_duplicate_indicators_rejected():
    data = sample()
    data["indicators"].append(copy.deepcopy(data["indicators"][0]))
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)


def test_atr_distance_requires_valid_indicator_reference():
    data = sample()
    data["long"]["exit"]["stop_loss"] = {
        "mode": "atr_multiple", "value": "2", "indicator_id": "not_known"
    }
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)
    data["long"]["exit"]["stop_loss"]["indicator_id"] = "fast_ema"
    assert StrategySpec.from_wire(data).long.exit.stop_loss.indicator_id == "fast_ema"


def test_partial_exits_cannot_exceed_position():
    data = sample()
    data["long"]["exit"]["partial_exits"] = [
        {"fraction_percent": "60", "target": {"mode": "ticks", "value": "10", "indicator_id": None}},
        {"fraction_percent": "50", "target": {"mode": "ticks", "value": "20", "indicator_id": None}},
    ]
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)


def test_fixed_lots_requires_its_value_and_no_risk_percent():
    data = sample()
    data["sizing"]["mode"] = "fixed_lots"
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)
    data["sizing"]["risk_percent_equity"] = None
    data["sizing"]["fixed_lots"] = "0.02"
    assert str(StrategySpec.from_wire(data).sizing.fixed_lots) == "0.02"


def test_constant_operand_cannot_access_future_time():
    data = sample()
    data["long"]["entry"]["predicates"][0]["right"] = {
        "kind": "constant", "reference": "2650.50", "field": "value",
        "offset_closed_bars": 1,
    }
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)
    data["long"]["entry"]["predicates"][0]["right"]["offset_closed_bars"] = 0
    assert StrategySpec.from_wire(data).long.entry.predicates[0].right.reference == "2650.50"


def test_json_nonfinite_and_malformed_rejected():
    with pytest.raises(ValueError):
        StrategySpec.from_json('{"revision":NaN}')
    with pytest.raises(ValueError):
        StrategySpec.from_json("{")
