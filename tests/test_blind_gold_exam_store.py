from aidy.blind_gold_exam_store import _actual_direction, _confidence, _difficulty, _predicted_direction


def test_direction_normalizes_trade_and_shadow_predictions() -> None:
    assert _predicted_direction({"decision": {"direction": "BUY"}}) == "long"
    assert _predicted_direction({"decision": {"shadow_direction": "sell"}}) == "short"


def test_outcome_direction_uses_only_resolved_forward_path() -> None:
    assert _actual_direction(predicted="long", outcome={"outcome_state": "all_targets_hit"}) == "long"
    assert _actual_direction(predicted="long", outcome={"outcome_state": "stop_hit"}) == "short"
    assert _actual_direction(predicted="short", outcome={"outcome_state": "shadow_direction_favorable"}) == "short"
    assert _actual_direction(predicted="short", outcome={"outcome_state": "shadow_direction_adverse"}) == "long"


def test_confidence_is_never_invented() -> None:
    assert _confidence({"decision": {"direction": "long"}}) is None
    assert _confidence({"decision": {"confidence": 72}}) == 0.72
    assert _confidence({"decision": {"confidence": 0.64}}) == 0.64


def test_difficulty_defaults_easy_until_frozen_context_exists() -> None:
    assert _difficulty({}) == 1
    assert _difficulty({"exam_context": {"difficulty": 4}}) == 4
