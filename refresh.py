#!/usr/bin/env python3
"""
DreamHost daily refresh script.

Cron entry (set in DH panel → Goodies → Cron Jobs):
  Hour: 6, Minute: 30, Day/Month/Weekday: 1-5 (Mon-Fri)
  Command: /usr/bin/python3 /home/USERNAME/amwest-cloud/refresh.py

Reads all configs in ./configs/*.json, fetches live data for each company,
and writes JSON files under ./data/{company_id}/livedata.json plus a dated
snapshot in ./data/{company_id}/history/YYYY-MM-DD.json.

Logs each run to ./logs/refresh.log so you can debug if cron emails report errors.
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Add this script's directory to sys.path so pullers.py imports cleanly
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from pullers import fetch_fred, fetch_yahoo, fetch_edgar  # noqa: E402

CONFIGS_DIR = SCRIPT_DIR / "configs"
DATA_DIR = SCRIPT_DIR / "data"
LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOGS_DIR / "refresh.log", "a") as f:
        f.write(line + "\n")


def refresh_company(config_path: Path) -> tuple[str, int]:
    """Run pullers for a single company, write JSON outputs. Returns (company_id, n_obs)."""
    config = json.loads(config_path.read_text())
    cid = config["company_id"]
    log(f"  start company={cid}")

    observations: list[dict] = []
    observations.extend(fetch_fred(config.get("fred_series", [])))
    observations.extend(fetch_yahoo(config.get("yahoo_peers", []) + config.get("yahoo_etfs", [])))
    observations.extend(fetch_edgar(config.get("edgar_peers", [])))

    refreshed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    livedata = {
        "company_id": cid,
        "display_name": config.get("display_name", cid),
        "refreshed_at": refreshed_at,
        "observation_count": len(observations),
        "observations": observations,
    }

    # Write latest snapshot
    cdir = DATA_DIR / cid
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "livedata.json").write_text(json.dumps(livedata, indent=2))

    # Write dated historical snapshot
    hdir = cdir / "history"
    hdir.mkdir(exist_ok=True)
    date_part = refreshed_at.split("T")[0]
    (hdir / f"{date_part}.json").write_text(json.dumps(livedata, indent=2))

    log(f"  done  company={cid} observations={len(observations)}")
    return cid, len(observations)


def main() -> int:
    log("=== refresh start ===")

    if not CONFIGS_DIR.exists():
        log(f"FAIL configs directory missing: {CONFIGS_DIR}")
        return 1

    configs = sorted(CONFIGS_DIR.glob("*.json"))
    if not configs:
        log(f"FAIL no company configs found in {CONFIGS_DIR}")
        return 1

    log(f"found {len(configs)} company config(s): {[c.name for c in configs]}")

    results: dict[str, int] = {}
    errors: list[str] = []
    for cfg in configs:
        try:
            cid, n = refresh_company(cfg)
            results[cid] = n
        except Exception as e:
            log(f"FAIL config={cfg.name} error={e}")
            errors.append(f"{cfg.name}: {e}")
            traceback.print_exc()

    if errors:
        log(f"=== refresh complete with {len(errors)} errors: {errors} ===")
        return 2
    log(f"=== refresh OK: {results} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
