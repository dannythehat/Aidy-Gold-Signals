"""Stored packets are verified against the rule that built them, not today's rule.

WHAT HAPPENED

Scoring neutral votes changed `subcalculator_is_scoreable` without giving the packet
contract a new version. Verification re-derives `scoreable` and compares it to the
stored value, so every packet written before the change - all 1,785 of them - failed
against the newly deployed rule. The failure raises RuntimeError inside the scoring
loop, which aborts the whole scheduled run, so no new cycles were created either. The
unscored cycle stayed at the head of the queue, so it failed again every minute.

AIDY produced zero cycles for five hours and two minutes (last cycle
2026-09-23T01:40:21Z, first error 01:47:54Z, 307 consecutive failed runs) while candle
ingestion carried on normally. It was a permanent wedge, not a transient error: nothing
in the loop could have cleared it.

WHY THE STORED PACKETS ARE NOT REWRITTEN

`calculator_digest` covers `scoreable`, and `packet_digest` covers the body. Amending a
stored packet to satisfy a newer rule would mean recomputing the digests that are the
only reason the packet counts as evidence. The seal is the point. So the packet declares
which rule built it and verification honours that, forever.
"""

from __future__ import annotations

from copy import deepcopy

from test_gold_expert_gate_contract import _build, _neutral_calculators

from aidy.gold_expert_gate_contract import (
    EXPERT_GATE_CONTRACT_VERSION,
    LEGACY_EXPERT_GATE_CONTRACT_VERSION,
    SUPPORTED_EXPERT_GATE_CONTRACT_VERSIONS,
    _digest,
    _normalise,
    subcalculator_is_scoreable,
    verify_expert_gate_packet,
)


def _as_stored_v1(packet: dict) -> dict:
    """Rebuild a v2 packet into the packet the old builder would have written.

    Not a hand-written fixture: the shape is taken from a real stored snapshot
    (momentum_impulse_expert at 2026-09-22T23:10:26Z), which carries four
    role=directional, state=known, vote=neutral subcalculators with scoreable=false.
    Digests are recomputed the same way verification derives them, so this is a
    genuinely valid v1 packet rather than a packet with the checks switched off.
    """
    body = _normalise(deepcopy(packet))
    body.pop("packet_digest", None)
    body["contract_version"] = LEGACY_EXPERT_GATE_CONTRACT_VERSION
    for item in body["subcalculators"]:
        item["scoreable"] = subcalculator_is_scoreable(
            role=str(item["role"]),
            state=str(item["state"]),
            vote=str(item["vote"]),
            contract_version=LEGACY_EXPERT_GATE_CONTRACT_VERSION,
        )
        item.pop("calculator_digest", None)
        item["calculator_digest"] = _digest(dict(item))
    return {**body, "packet_digest": _digest(body)}


def _stored_v1_neutral_packet() -> dict:
    return _as_stored_v1(
        _build(
            subcalculators=_neutral_calculators(),
            conclusion="neutral",
            internal_conviction=None,
        )
    )


def test_the_production_wedge_reproduces_and_is_fixed() -> None:
    """The exact packet shape that took AIDY down for five hours must verify."""
    packet = _stored_v1_neutral_packet()
    neutral = [
        item
        for item in packet["subcalculators"]
        if item["role"] == "directional" and item["vote"] == "neutral"
    ]
    assert neutral, "fixture must carry the subcalculator shape that failed"
    for item in neutral:
        assert item["scoreable"] is False  # the old rule, as stored
    assert verify_expert_gate_packet(packet), (
        "a stored v1 packet must stay verifiable after the rule changed"
    )


def test_a_v1_packet_is_not_silently_accepted_by_switching_checks_off() -> None:
    """Tolerating old packets must not mean tolerating tampered ones. Flipping one
    stored scoreable flag has to fail, or the version dispatch is just a bypass."""
    packet = _stored_v1_neutral_packet()
    for item in packet["subcalculators"]:
        if item["role"] == "directional" and item["vote"] == "neutral":
            item["scoreable"] = True
            break
    assert not verify_expert_gate_packet(packet)


def test_new_packets_are_built_at_the_current_version_and_score_neutral() -> None:
    packet = _build(
        subcalculators=_neutral_calculators(),
        conclusion="neutral",
        internal_conviction=None,
    )
    assert packet["contract_version"] == EXPERT_GATE_CONTRACT_VERSION
    assert verify_expert_gate_packet(packet)
    for item in packet["subcalculators"]:
        if item["role"] == "directional" and item["vote"] == "neutral":
            assert item["scoreable"] is True


def test_the_two_versions_disagree_about_neutral_and_agree_elsewhere() -> None:
    """The whole reason a version exists: one rule changed, and only one."""
    for vote, legacy, current in (
        ("neutral", False, True),
        ("bullish", True, True),
        ("bearish", True, True),
        ("abstain", False, False),
    ):
        assert (
            subcalculator_is_scoreable(
                role="directional",
                state="known",
                vote=vote,
                contract_version=LEGACY_EXPERT_GATE_CONTRACT_VERSION,
            )
            is legacy
        )
        assert (
            subcalculator_is_scoreable(
                role="directional", state="known", vote=vote
            )
            is current
        )


def test_an_unrecognised_contract_version_is_rejected() -> None:
    """Accepting two known versions is not accepting anything."""
    packet = _stored_v1_neutral_packet()
    body = {k: v for k, v in packet.items() if k != "packet_digest"}
    body["contract_version"] = "aidy_gold_expert_gate_contract_v99"
    assert not verify_expert_gate_packet({**body, "packet_digest": _digest(body)})


def test_changing_the_scoreable_rule_again_requires_a_new_version() -> None:
    """The actual lesson. `scoreable` is sealed inside calculator_digest, so any future
    change to the rule strands every packet already written unless it ships a new
    version alongside. This fails the moment someone edits the rule without adding one,
    which is precisely the review that was missing the first time."""
    rules = {
        version: tuple(
            subcalculator_is_scoreable(
                role="directional", state="known", vote=vote, contract_version=version
            )
            for vote in ("bullish", "bearish", "neutral", "abstain", "unknown")
        )
        for version in sorted(SUPPORTED_EXPERT_GATE_CONTRACT_VERSIONS)
    }
    assert rules == {
        "aidy_gold_expert_gate_contract_v1": (True, True, False, False, False),
        "aidy_gold_expert_gate_contract_v2": (True, True, True, False, False),
    }, "a changed scoreable rule needs its own contract version and this pin updated"
