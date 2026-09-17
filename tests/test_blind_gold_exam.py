from aidy.blind_gold_exam import ExamEpisode, evaluate_learning, score_batch


def _ep(i: int, *, correct: bool, memory: int, confidence: float = 0.7, difficulty: int = 1) -> ExamEpisode:
    predicted = "long"
    actual = "long" if correct else "short"
    return ExamEpisode(
        episode_id=f"e{i:03d}",
        evaluated_at_utc=f"2026-09-{1 + i // 24:02d}T{i % 24:02d}:00:00+00:00",
        available_learning_count=memory,
        predicted_direction=predicted,
        actual_direction=actual,
        confidence=confidence,
        difficulty=difficulty,
    )


def test_score_batch_reports_direction_brier_and_difficulty() -> None:
    result = score_batch([
        _ep(1, correct=True, memory=0, difficulty=1),
        _ep(2, correct=False, memory=1, difficulty=2),
    ])
    assert result["direction_accuracy"] == 0.5
    assert result["brier_n"] == 2
    assert result["difficulty"]["1"]["n"] == 1
    assert result["difficulty"]["2"]["n"] == 1


def test_does_not_call_memory_growth_learning_without_performance_gain() -> None:
    rows = []
    for batch in range(3):
        for j in range(20):
            rows.append(_ep(batch * 20 + j, correct=j < 10, memory=batch * 20))
    result = evaluate_learning(rows, batch_size=20)
    assert result["memory_grew"] is True
    assert result["learning_observed"] is False
    assert result["state"] == "memory_accumulating"


def test_flags_regression_even_when_memory_grows() -> None:
    rows = []
    wins = [15, 12, 8]
    for batch, win_count in enumerate(wins):
        for j in range(20):
            rows.append(_ep(batch * 20 + j, correct=j < win_count, memory=batch * 20))
    result = evaluate_learning(rows, batch_size=20)
    assert result["memory_grew"] is True
    assert result["learning_observed"] is False
    assert result["state"] == "regression_candidate"


def test_small_improvement_is_candidate_not_proof() -> None:
    rows = []
    wins = [10, 11, 12]
    for batch, win_count in enumerate(wins):
        for j in range(20):
            rows.append(_ep(batch * 20 + j, correct=j < win_count, memory=batch * 20))
    result = evaluate_learning(rows, batch_size=20)
    assert result["state"] == "learning_candidate"
    assert result["learning_observed"] is False
