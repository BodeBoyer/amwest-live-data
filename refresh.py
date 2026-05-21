#!/usr/bin/env python3
"""
Universal live-data refresh — deduplicating fetcher.

Architecture (Option B): build a UNION of all series/tickers across every config in
./configs/*.json, fetch each unique item exactly ONCE, then assemble a per-company
livedata.json file containing only the items that company's config declared.

This means:
  - Shared series (DGS10, MORTGAGE30US, UNRATE, etc.) are fetched once per run,
    not once per company.
  - Each company's workbook still reads a single self-contained file
    (data/{company_id}/livedata.json).
  - Adding a new company config picks up shared series for free; only the
    company-specific series add new fetch work.

GitHub Actions cron entry (.github/workflows/refresh.yml) runs this weekdays at 11:30 UTC.
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

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


def build_union(configs: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Build deduplicated lists of FRED series, Yahoo tickers, and EDGAR peers
    across all companies. Each item is keyed by its natural identifier:
      - FRED: series id
      - Yahoo: ticker
      - EDGAR: CIK
    When the same id appears in multiple configs, the first occurrence wins
    (the name + unit metadata is taken from whoever declared it first; values
    are identical regardless)."""
    fred_seen: dict[str, dict] = {}
    yahoo_seen: dict[str, dict] = {}
    edgar_seen: dict[str, dict] = {}

    for cfg in configs:
        for s in cfg.get("fred_series", []):
            fred_seen.setdefault(s["id"], s)
        for s in cfg.get("yahoo_peers", []) + cfg.get("yahoo_etfs", []):
            yahoo_seen.setdefault(s["ticker"], s)
        for s in cfg.get("edgar_peers", []):
            edgar_seen.setdefault(s["cik"], s)

    return list(fred_seen.values()), list(yahoo_seen.values()), list(edgar_seen.values())


def index_observations(observations: list[dict]) -> dict[str, dict]:
    """Build a lookup dict keyed by an observation's natural id."""
    idx: dict[str, dict] = {}
    for obs in observations:
        # FRED uses series_id; Yahoo/EDGAR use the name field as the key
        key = obs.get("series_id") or obs.get("name")
        if key:
            idx[key] = obs
    return idx


def write_company_file(cid: str, display_name: str, observations: list[dict],
                       refreshed_at: str) -> int:
    """Write the per-company livedata.json plus dated history snapshot."""
    livedata = {
        "company_id": cid,
        "display_name": display_name,
        "refreshed_at": refreshed_at,
        "observation_count": len(observations),
        "observations": observations,
    }

    cdir = DATA_DIR / cid
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "livedata.json").write_text(json.dumps(livedata, indent=2))

    hdir = cdir / "history"
    hdir.mkdir(exist_ok=True)
    date_part = refreshed_at.split("T")[0]
    (hdir / f"{date_part}.json").write_text(json.dumps(livedata, indent=2))

    return len(observations)


def main() -> int:
    log("=== refresh start ===")

    if not CONFIGS_DIR.exists():
        log(f"FAIL configs directory missing: {CONFIGS_DIR}")
        return 1

    config_paths = sorted(CONFIGS_DIR.glob("*.json"))
    if not config_paths:
        log(f"FAIL no company configs found in {CONFIGS_DIR}")
        return 1

    configs = [json.loads(p.read_text()) for p in config_paths]
    company_ids = [c["company_id"] for c in configs]
    log(f"found {len(configs)} company config(s): {company_ids}")

    # === Step 1: union all unique series across configs ===
    fred_union, yahoo_union, edgar_union = build_union(configs)
    log(f"union: {len(fred_union)} FRED series, {len(yahoo_union)} Yahoo tickers, "
        f"{len(edgar_union)} EDGAR peers (deduplicated across all configs)")

    # === Step 2: fetch each unique item exactly once ===
    refreshed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log("fetching FRED ...")
    fred_obs = fetch_fred(fred_union)
    log(f"  → {len(fred_obs)} FRED observations")
    log("fetching Yahoo ...")
    yahoo_obs = fetch_yahoo(yahoo_union)
    log(f"  → {len(yahoo_obs)} Yahoo observations")
    log("fetching EDGAR ...")
    edgar_obs = fetch_edgar(edgar_union)
    log(f"  → {len(edgar_obs)} EDGAR observations")

    # Index observations by the natural lookup key each company config uses
    fred_idx = {o["series_id"]: o for o in fred_obs}
    yahoo_idx = {o["name"]: o for o in yahoo_obs}        # keyed by price_name (e.g. "AIZ_Price")
    edgar_idx = {o["name"]: o for o in edgar_obs}        # keyed by stkeq_name / shares_name

    # === Step 3: assemble per-company files from the cached union ===
    results: dict[str, int] = {}
    errors: list[str] = []
    for cfg in configs:
        cid = cfg["company_id"]
        try:
            obs_for_company: list[dict] = []
            for s in cfg.get("fred_series", []):
                obs = fred_idx.get(s["id"])
                if obs:
                    obs_for_company.append(obs)
            for s in cfg.get("yahoo_peers", []) + cfg.get("yahoo_etfs", []):
                obs = yahoo_idx.get(s["price_name"])
                if obs:
                    obs_for_company.append(obs)
            for s in cfg.get("edgar_peers", []):
                for k in ("stkeq_name", "shares_name"):
                    if s.get(k) and s[k] in edgar_idx:
                        obs_for_company.append(edgar_idx[s[k]])

            n = write_company_file(cid, cfg.get("display_name", cid),
                                   obs_for_company, refreshed_at)
            log(f"  ✓ company={cid} observations={n}")
            results[cid] = n
        except Exception as e:
            log(f"FAIL company={cid} error={e}")
            errors.append(f"{cid}: {e}")
            traceback.print_exc()

    if errors:
        log(f"=== refresh complete with {len(errors)} errors: {errors} ===")
        return 2
    log(f"=== refresh OK: {results} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
