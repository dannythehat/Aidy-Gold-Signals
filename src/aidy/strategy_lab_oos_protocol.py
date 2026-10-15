"""Day26: chronological, label-maturity-aware XAUUSD research validation.

Technical demonstration only. Original source is retrospective HistData BID M1
resampled to closed M5, not independently observed ask/fill/commission data.
Return signs are toy outcomes, not model profits, client returns or an edge.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256

from aidy.strategy_lab_history_reader import ReadResult

H = 2
STEP = timedelta(minutes=5)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MODEL_RULE = b"aidy.day26.training_only_prior_mean_sign.v1;horizon=2;never_fit_holdout"
MODEL_SHA256 = sha256(MODEL_RULE).hexdigest()


def _hash(data: object) -> str:
    return sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class LabeledSample:
    decision_at_utc: str
    feature_available_at_utc: str
    outcome_available_at_utc: str
    bid_close: Decimal
    two_bar_future_change: Decimal

    def wire(self) -> dict:
        return {
            "decision_at_utc": self.decision_at_utc,
            "feature_available_at_utc": self.feature_available_at_utc,
            "outcome_available_at_utc": self.outcome_available_at_utc,
            "bid_close": format(self.bid_close, "f"),
            "two_bar_future_change": format(self.two_bar_future_change, "f"),
        }


@dataclass(frozen=True)
class OOSPolicy:
    minimum_training: int = 32
    validation_length: int = 12
    embargo_bars: int = 2
    sealed_holdout_length: int = 20
    forward_label_horizon: int = H

    def validate(self) -> None:
        checks = (self.minimum_training, self.validation_length,
                  self.embargo_bars, self.sealed_holdout_length,
                  self.forward_label_horizon)
        if any(type(i) is not int for i in checks):
            raise ValueError("policy requires explicit integer parameters")
        if (self.minimum_training < 20 or self.validation_length < 4
                or self.embargo_bars < H or self.sealed_holdout_length < 10
                or self.forward_label_horizon != H):
            raise ValueError("policy does not adequately purge/embargo outcomes")


@dataclass(frozen=True)
class FoldResult:
    ordinal: int
    train_count: int
    train_last_decision_utc: str
    train_last_outcome_available_utc: str
    validation_first_decision_utc: str
    validation_last_decision_utc: str
    embargo_cutoff_utc: str
    validation_count: int
    train_only_direction: int
    correct_signs: int
    always_positive_correct_signs: int

    def wire(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DevelopmentReview:
    source_sha256: str
    policy_sha256: str
    model_sha256: str
    development_sha256: str
    holdout_sha256: str
    holdout_first_utc: str
    sealed_holdout_size: int
    excluded_boundary_bars: int
    folds: tuple[FoldResult, ...]
    fold_evidence_sha256: str

    def wire(self) -> dict:
        return {**asdict(self), "folds": [f.wire() for f in self.folds]}


class SealedOOS:
    """The public development accessor never returns a holdout sample.

    This is an API/operational seal, NOT an OS-level security sandbox against
    a researcher with raw warehouse privileges; production isolation is future.
    """
    def __init__(self, history: ReadResult, policy: OOSPolicy = OOSPolicy()) -> None:
        policy.validate()
        bars = history.bars
        if (history.provenance != "retrospective_history" or history.pit_eligible
                or history.native_m1_rows != len(bars) * 5
                or len(bars) < 110 or not HASH_RE.fullmatch(history.input_digest)
                or not history.source_archive_hashes
                or any(not HASH_RE.fullmatch(h) for h in history.source_archive_hashes)):
            raise ValueError("unqualified frozen real-history source")
        for i, bar in enumerate(bars):
            if (bar.price_basis != "bid" or not bar.close.is_finite()
                    or bar.close <= 0 or bar.available_at_utc - bar.open_time_utc != STEP
                    or bar.open_time_utc.tzinfo is None
                    or bar.open_time_utc.utcoffset() != timedelta(0)
                    or i and bar.open_time_utc != bars[i-1].available_at_utc):
                raise ValueError("gapped, non-UTC or unavailable historical sample")
        self.source_sha256 = history.input_digest
        self.policy = policy
        samples = []
        for i in range(len(bars) - H):
            current, future = bars[i], bars[i + H]
            now = current.available_at_utc.isoformat().replace("+00:00", "Z")
            samples.append(LabeledSample(
                now, now,
                future.available_at_utc.isoformat().replace("+00:00", "Z"),
                current.close, future.close - current.close,
            ))
        self._samples = tuple(samples)
        self._holdout_start = len(samples) - policy.sealed_holdout_length
        self._development_end = self._holdout_start - policy.embargo_bars - H
        if self._development_end < policy.minimum_training + policy.validation_length:
            raise ValueError("no defensible independent holdout split")
        self.policy_sha256 = _hash(asdict(policy))
        self.development_sha256 = _hash([s.wire() for s in self._samples[:self._development_end]])
        self.holdout_sha256 = _hash([s.wire() for s in self._samples[self._holdout_start:]])
        self.holdout_first_utc = self._samples[self._holdout_start].decision_at_utc

    def development(self) -> tuple[LabeledSample, ...]:
        """Public modelling interface; no gap or sealed holdout bars released."""
        return self._samples[:self._development_end]

    def _fit(self, training: tuple[LabeledSample, ...]) -> int:
        if len(training) < self.policy.minimum_training:
            raise ValueError("insufficient as-of training labels")
        prior_mean = sum((r.two_bar_future_change for r in training), Decimal(0))
        return 1 if prior_mean >= 0 else -1

    def review_development(self) -> DevelopmentReview:
        dev = self.development()
        folds: list[FoldResult] = []
        start = self.policy.minimum_training + self.policy.embargo_bars + H
        number = 0
        while start + self.policy.validation_length <= len(dev):
            val = dev[start:start+self.policy.validation_length]
            # as-of window: the training label must be MATURE before the
            # validation start, after an extra two closed bars of embargo.
            cutoff = val[0].decision_at_utc
            from datetime import datetime

            cutoff_at = datetime.fromisoformat(cutoff.replace("Z", "+00:00")) - (
                self.policy.embargo_bars * STEP
            )
            eligible = tuple(x for x in dev[:start] if
                             datetime.fromisoformat(
                                 x.outcome_available_at_utc.replace("Z", "+00:00")
                             ) <= cutoff_at)
            if len(eligible) < self.policy.minimum_training:
                raise ValueError("purged fold no longer has adequate train observations")
            if (eligible[-1].outcome_available_at_utc >
                    cutoff_at.isoformat().replace("+00:00", "Z")):
                raise ValueError("training outcome leaks over embargo cutoff")
            direction = self._fit(eligible)
            folds.append(FoldResult(
                number, len(eligible), eligible[-1].decision_at_utc,
                eligible[-1].outcome_available_at_utc,
                val[0].decision_at_utc, val[-1].decision_at_utc,
                cutoff_at.isoformat().replace("+00:00", "Z"),
                len(val), direction,
                sum((x.two_bar_future_change > 0) == (direction == 1) for x in val),
                sum(x.two_bar_future_change > 0 for x in val),
            ))
            number += 1
            start += self.policy.validation_length
        if len(folds) < 3:
            raise ValueError("insufficient strict chronological folds")
        return DevelopmentReview(
            self.source_sha256, self.policy_sha256, MODEL_SHA256,
            self.development_sha256, self.holdout_sha256,
            self.holdout_first_utc, self.policy.sealed_holdout_length,
            self._holdout_start - self._development_end,
            tuple(folds), _hash([f.wire() for f in folds]),
        )

    def _sealed_final_result(self) -> dict:
        """Only TrialRegistry may authorize this method after freeze."""
        dev = self.development()
        direction = self._fit(dev)
        holdout = self._samples[self._holdout_start:]
        return {
            "holdout_count": len(holdout),
            "holdout_start_utc": self.holdout_first_utc,
            "frozen_train_direction": direction,
            "holdout_correct_signs": sum(
                (v.two_bar_future_change > 0) == (direction == 1) for v in holdout
            ),
            "always_positive_correct_signs": sum(
                v.two_bar_future_change > 0 for v in holdout
            ),
            "holdout_labels_sha256": self.holdout_sha256,
            "claim": "RETROSPECTIVE_BID_CHANGE_SIGN_DIAGNOSTIC_ONLY",
            "broker_cost_net_return_verified": False,
            "independent_out_of_sample_alpha_qualified": False,
        }
