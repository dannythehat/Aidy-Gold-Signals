from aidy.blind_gold_exam_context import frozen_exam_context


def test_context_uses_only_frozen_episode_evidence():
    episode = {
        "evidence": {
            "regime_state": {
                "trend_structure": "breakout",
                "volatility_state": "expansion",
                "liquidity_state": "normal",
                "session": "london",
                "event_timing": "pre_event",
            }
        },
        "context_summary": {"as_of_utc": "2026-09-17T08:00:00+00:00", "market_mid": "3680.1"},
    }
    result = frozen_exam_context(episode)
    assert result["market_structure"] == "breakout"
    assert result["volatility_state"] == "expansion"
    assert result["session"] == "london"
    assert result["difficulty"] == 4
    assert result["context_dimension_count"] == 5
    assert result["pit_only"] is True


def test_missing_context_stays_unknown_instead_of_being_backfilled():
    result = frozen_exam_context({"evidence": {}, "context_summary": {}})
    assert result["context_dimension_count"] == 0
    assert "market_structure" not in result
    assert "liquidity_state" not in result
    assert result["difficulty"] == 1
