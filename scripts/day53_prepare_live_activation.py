from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidy.decision_ledger import decision_ledger_manifest
from aidy.end_to_end import day52_runtime_manifest
from aidy.forward_live_observer import day53_live_forward_manifest
from aidy.forward_start_amendment import (
    AMENDMENT_EFFECTIVE_UTC,
    FORWARD_COHORT_VERSION_V2,
    FORWARD_MANIFEST_VERSION_V2,
    amended_cohort_id_for_manifest,
    build_amended_frozen_version_manifest,
    digest,
)
from aidy.gc_shadow_spine import day41_architecture_manifest
from aidy.macro_event_intelligence import EVENT_INTELLIGENCE_VERSION, SURPRISE_CAPTURE_VERSION
from aidy.openai_gateway_v2 import openai_gateway_manifest_v2
from aidy.selective_abstention import day45_manifest
from aidy.self_consistency_v2 import self_consistency_manifest_v2


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Activation timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare AIDY Day 53 remote live activation")
    parser.add_argument("--accepted-code-head", required=True)
    parser.add_argument("--activated-at-utc", required=True)
    parser.add_argument("--output-dir", default="day53_live_activation_artifacts")
    return parser.parse_args()


def _component(version: str, manifest: dict[str, Any]) -> dict[str, str]:
    manifest_digest = str(manifest.get("manifest_digest") or "")
    if not manifest_digest:
        raise RuntimeError(f"Component {version} has no manifest digest.")
    return {"version": version, "digest": manifest_digest}


def _components() -> dict[str, dict[str, str]]:
    runtime = day52_runtime_manifest()
    gateway = openai_gateway_manifest_v2()
    consistency = self_consistency_manifest_v2()
    ledger = decision_ledger_manifest()
    selective = day45_manifest()
    gc = day41_architecture_manifest()
    macro_identity = {
        "event_intelligence_version": EVENT_INTELLIGENCE_VERSION,
        "surprise_capture_version": SURPRISE_CAPTURE_VERSION,
        "historical_consensus_backfilled": False,
        "forward_capture_required": True,
    }
    return {
        "day52_runtime": _component(str(runtime["runtime_version"]), runtime),
        "openai_gateway_v2": _component(str(gateway["gateway_version"]), gateway),
        "self_consistency_v2": _component(
            str(consistency["self_consistency_version"]), consistency
        ),
        "immutable_decision_ledger": _component(str(ledger["ledger_version"]), ledger),
        "selective_abstention_shadow": _component(str(selective["layer_version"]), selective),
        "gc_xau_shadow": _component(str(gc["manifest_version"]), gc),
        "macro_surprise": {
            "version": SURPRISE_CAPTURE_VERSION,
            "digest": digest(macro_identity),
        },
    }


def _sql_text(value: object) -> str:
    return str(value).replace("'", "''")


def build_activation(*, accepted_code_head: str, activated_at_utc: str) -> dict[str, Any]:
    head = accepted_code_head.strip().lower()
    if len(head) != 40 or any(ch not in "0123456789abcdef" for ch in head):
        raise ValueError("accepted_code_head must be a 40-character git SHA.")
    activated = _utc(activated_at_utc)
    amendment = _utc(AMENDMENT_EFFECTIVE_UTC)
    if activated < amendment:
        raise ValueError("Activation cannot precede the ex-ante immediate-start amendment.")

    frozen = build_amended_frozen_version_manifest(
        accepted_code_head=head,
        earliest_start_utc=AMENDMENT_EFFECTIVE_UTC,
        components=_components(),
    )
    cohort_id = amended_cohort_id_for_manifest(frozen)
    observer = day53_live_forward_manifest()
    manifest_json = canonical_json(frozen)
    stamp = activated.isoformat()
    sql = f"""
INSERT INTO aidy_forward_cohorts (
    cohort_id,cohort_version,manifest_version,manifest_json,manifest_digest,
    accepted_code_head,earliest_start_utc,prepared_at_utc,state
) VALUES (
    '{_sql_text(cohort_id)}',
    '{_sql_text(FORWARD_COHORT_VERSION_V2)}',
    '{_sql_text(FORWARD_MANIFEST_VERSION_V2)}',
    '{_sql_text(manifest_json)}',
    '{_sql_text(frozen['manifest_digest'])}',
    '{_sql_text(head)}',
    '{_sql_text(frozen['earliest_start_utc'])}',
    '{_sql_text(stamp)}',
    'prepared'
)
ON CONFLICT(cohort_id) DO NOTHING;

UPDATE aidy_forward_cohorts
SET state='active', activated_at_utc='{_sql_text(stamp)}'
WHERE cohort_id='{_sql_text(cohort_id)}' AND state='prepared';
""".strip()
    metadata: dict[str, Any] = {
        "activation_contract_version": "aidy_day53_remote_activation_v1",
        "cohort_id": cohort_id,
        "accepted_code_head": head,
        "activated_at_utc": stamp,
        "earliest_start_utc": frozen["earliest_start_utc"],
        "manifest_digest": frozen["manifest_digest"],
        "observer_manifest_digest": observer["manifest_digest"],
        "cohort_version": FORWARD_COHORT_VERSION_V2,
        "manifest_version": FORWARD_MANIFEST_VERSION_V2,
        "formal_forward_enabled": True,
        "pre_activation_backfill_allowed": False,
        "day54_minimum_model_resolved_episode_independent_n": 300,
        "blocked_cycles_can_satisfy_day54_gate": False,
        "telegram_publication_enabled": False,
        "live_money_execution_enabled": False,
        "super_signals_dependency_allowed": False,
    }
    metadata["metadata_digest"] = digest(metadata)
    return {
        "frozen_manifest": frozen,
        "observer_manifest": observer,
        "metadata": metadata,
        "activation_sql": sql,
    }


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = build_activation(
        accepted_code_head=args.accepted_code_head,
        activated_at_utc=args.activated_at_utc,
    )
    (output / "frozen_manifest.json").write_text(
        canonical_json(artifacts["frozen_manifest"]) + "\n",
        encoding="utf-8",
    )
    (output / "observer_manifest.json").write_text(
        canonical_json(artifacts["observer_manifest"]) + "\n",
        encoding="utf-8",
    )
    (output / "metadata.json").write_text(
        canonical_json(artifacts["metadata"]) + "\n",
        encoding="utf-8",
    )
    (output / "activation.sql").write_text(str(artifacts["activation_sql"]) + "\n", encoding="utf-8")
    (output / "cohort_id.txt").write_text(str(artifacts["metadata"]["cohort_id"]) + "\n", encoding="utf-8")
    print(canonical_json(artifacts["metadata"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
