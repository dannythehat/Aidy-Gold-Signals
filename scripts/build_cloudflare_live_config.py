from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from aidy.config import AidySettings


def main() -> None:
    source = Path("wrangler.test.example.jsonc")
    target = Path("wrangler.research.live.jsonc")
    cfg = json.loads(source.read_text(encoding="utf-8"))

    cfg["d1_databases"][0]["database_name"] = os.environ["AIDY_D1_DATABASE_NAME"]
    cfg["d1_databases"][0]["database_id"] = os.environ["AIDY_D1_DATABASE_ID"]
    cfg["r2_buckets"][0]["bucket_name"] = os.environ["AIDY_R2_BUCKET_NAME"]
    cfg["vars"]["AIDY_CAPTURE_ENABLED"] = "true"
    cfg["vars"]["AIDY_MARKET_DATA_SOURCE"] = "twelve_data"
    cfg["vars"]["AIDY_MARKET_DATA_OWNERSHIP"] = "public_independent"
    cfg["vars"]["AIDY_MARKET_POLL_SECONDS"] = "300"
    cfg["vars"]["AIDY_TWELVE_INTRADAY_SELF_HEAL_ENABLED"] = "true"
    cfg["vars"]["AIDY_FORMAL_FORWARD_ENABLED"] = "false"

    settings = AidySettings.from_worker_env(SimpleNamespace(**cfg["vars"]))
    assert settings.capture_enabled is True
    assert settings.market_data_source == "twelve_data"
    assert settings.market_data_ownership == "public_independent"
    assert settings.twelve_intraday_self_heal_enabled is True
    assert str(cfg["vars"]["AIDY_FORMAL_FORWARD_ENABLED"]).lower() == "false"
    assert cfg["triggers"]["crons"] == ["* * * * *"]

    target.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print("cloudflare_live_config_built=true")


if __name__ == "__main__":
    main()
