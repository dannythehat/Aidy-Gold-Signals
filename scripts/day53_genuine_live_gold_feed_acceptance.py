from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from aidy.live_gold_recorder import day53_genuine_live_gold_feed_manifest


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    manifest = day53_genuine_live_gold_feed_manifest()
    summary = {
        "acceptance_version": "aidy_day53_genuine_live_gold_feed_acceptance_v1",
        "manifest_digest": manifest["manifest_digest"],
        "quote_source": manifest["quote_source"],
        "candle_source": manifest["candle_source"],
        "public_independent_only": True,
        "genuine_bid_ask_required": True,
        "closed_bucket_ohlc_only": True,
        "sparse_data_fails_closed": manifest["missing_or_sparse_data_fails_closed"],
        "secret_persisted": manifest["api_key_persisted"],
        "decision_adapter_enabled": manifest["decision_adapter_enabled_by_this_change"],
        "live_money_execution_allowed": manifest["live_money_execution_allowed"],
        "freeze_break_reason": manifest["freeze_break_reason"],
    }
    summary["summary_digest"] = sha256(_canonical(summary).encode()).hexdigest()
    (output / "manifest.json").write_text(_canonical(manifest) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(_canonical(summary) + "\n", encoding="utf-8")
    print(_canonical(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
