from __future__ import annotations

import argparse
import json
import runpy
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidy.telegram_publisher import (
    DEFAULT_GROUP_NAME,
    SimulatedTelegramTransport,
    build_publication_envelope,
    canonical_json,
    day50_manifest,
    digest,
    publish_envelope,
    verify_publication_envelope,
    verify_publication_receipt,
)

_DAY34 = runpy.run_path(str(Path(__file__).with_name("day34_decision_ledger_acceptance.py")))
_cycle = _DAY34["_cycle"]

BASE_SHA = "6119b97d422374d4bd7a9bd660e5ca597693fc23"
FIXTURE_TIME = datetime(2026, 9, 1, 14, 30, tzinfo=UTC)
SIMULATED_CHAT_ID = "-1001234567890"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 50 Telegram publisher acceptance")
    parser.add_argument("--output-dir", default="day50_artifacts")
    return parser.parse_args()


def _head_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def build_artifacts(head_sha: str) -> dict[str, Any]:
    admitted = _cycle(FIXTURE_TIME, 0, "decision_admitted")
    envelope = build_publication_envelope(
        ex_ante_record=admitted,
        group_name=DEFAULT_GROUP_NAME,
        chat_id=SIMULATED_CHAT_ID,
    )
    if not verify_publication_envelope(envelope):
        raise RuntimeError("Day 50 publication envelope verification failed.")

    transport = SimulatedTelegramTransport(sent_at_utc=FIXTURE_TIME)
    first = publish_envelope(envelope, transport=transport)
    retry = publish_envelope(envelope, transport=transport, existing_receipt=first)
    if first != retry or len(transport.calls) != 1:
        raise RuntimeError("Day 50 idempotent retry contract failed.")
    if not verify_publication_receipt(first):
        raise RuntimeError("Day 50 simulated publication receipt failed verification.")

    blocked_states: dict[str, bool] = {}
    for index, disposition in enumerate(
        ("pre_model_blocked", "model_failed", "post_model_blocked", "no_trade"),
        start=1,
    ):
        record = _cycle(FIXTURE_TIME, index, disposition)
        rejected = False
        try:
            build_publication_envelope(ex_ante_record=record, chat_id=SIMULATED_CHAT_ID)
        except ValueError:
            rejected = True
        blocked_states[disposition] = rejected
    if not all(blocked_states.values()):
        raise RuntimeError("Day 50 allowed an ineligible cycle to publish.")

    source_blocks: dict[str, bool] = {}
    for source_state in ("replay", "shadow", "historical", "failed"):
        rejected = False
        try:
            build_publication_envelope(
                ex_ante_record=admitted,
                chat_id=SIMULATED_CHAT_ID,
                source_state=source_state,
            )
        except ValueError:
            rejected = True
        source_blocks[source_state] = rejected
    if not all(source_blocks.values()):
        raise RuntimeError("Day 50 allowed a replay/shadow source to publish.")

    manifest = day50_manifest()
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "manifest_digest": manifest["manifest_digest"],
        "configured_private_group_name": manifest["configured_private_group_name"],
        "publication_id": envelope["publication_id"],
        "decision_id": envelope["decision_id"],
        "message_digest": envelope["message_digest"],
        "envelope_verified": True,
        "receipt_verified": True,
        "simulated_send_count": len(transport.calls),
        "idempotent_retry_sent_no_duplicate": len(transport.calls) == 1 and first == retry,
        "ineligible_cycle_blocks": blocked_states,
        "ineligible_source_blocks": source_blocks,
        "only_actionable_provider_instructions_publish": True,
        "ledger_identity_retained": first["decision_id"] == admitted["decision_id"],
        "secrets_persisted": False,
        "real_telegram_post_performed": False,
        "broker_dependency_allowed": False,
        "follower_dependency_allowed": False,
        "super_signals_dependency_allowed": False,
        "formal_forward_evidence_created": False,
    }
    summary["summary_digest"] = digest(summary)
    return {"summary": summary, "envelope": envelope, "receipt": first, "manifest": manifest}


def main() -> None:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = build_artifacts(_head_sha())
    (output / "summary.json").write_text(canonical_json(artifacts["summary"]) + "\n", encoding="utf-8")
    (output / "publication.json").write_text(
        canonical_json(
            {
                "envelope": artifacts["envelope"],
                "receipt": artifacts["receipt"],
                "manifest": artifacts["manifest"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifacts["summary"], sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
