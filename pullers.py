"""
DreamHost-compatible data pullers. Uses Python stdlib only (no requests, no boto3,
no openpyxl). Run from `refresh.py`.

Pullers:
  - fetch_fred: FRED CSV endpoints (no API key)
  - fetch_yahoo: Yahoo Finance chart API (no key)
  - fetch_edgar: SEC EDGAR XBRL companyfacts (User-Agent required)

Output: list of observation dicts ready to JSON-serialize.
"""
from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "AmWest Master v3 cloud refresh - bodetboyer@gmail.com"


def http_get(url: str, *, timeout: int = 30, retries: int = 2) -> bytes:
    """GET with retry, courteous User-Agent."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


# =============================================================================
# FRED puller
# =============================================================================

def fetch_fred(series_list: list[dict]) -> list[dict]:
    """series_list: [{'id': 'DGS10', 'name': 'Rate_10Y_UST', 'unit': '%'}, ...]"""
    out = []
    for s in series_list:
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s['id']}"
            text = http_get(url).decode("utf-8")
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
            for row in reversed(rows[1:]):
                if len(row) >= 2 and row[1] not in ("", ".", "NA"):
                    try:
                        out.append({
                            "name": s["name"],
                            "value": float(row[1]),
                            "unit": s["unit"],
                            "as_of": row[0],
                            "source": "FRED",
                            "series_id": s["id"],
                            "url": f"https://fred.stlouisfed.org/series/{s['id']}",
                        })
                        break
                    except ValueError:
                        continue
        except Exception as e:
            print(f"FRED {s['id']}: ERROR {e}")
    return out


# =============================================================================
# Yahoo Finance puller
# =============================================================================

def fetch_yahoo(symbols: list[dict]) -> list[dict]:
    """symbols: [{'ticker': 'RKT', 'price_name': 'RKT_Price'}, ...]"""
    out = []
    for sym in symbols:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym['ticker']}?interval=1d&range=5d"
            payload = json.loads(http_get(url).decode("utf-8"))
            result = payload["chart"]["result"][0]
            ts = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
            for t, c in reversed(list(zip(ts, closes))):
                if c is not None:
                    iso = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
                    out.append({
                        "name": sym["price_name"],
                        "value": float(c),
                        "unit": "USD",
                        "as_of": iso,
                        "source": "Yahoo Finance",
                        "series_id": sym["ticker"],
                        "url": f"https://finance.yahoo.com/quote/{sym['ticker']}",
                    })
                    break
        except Exception as e:
            print(f"Yahoo {sym['ticker']}: ERROR {e}")
    return out


# =============================================================================
# EDGAR puller
# =============================================================================

SE_TAGS = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)


def _pick_latest_fact(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    return max(rows, key=lambda r: (r.get("filed", ""), r.get("end", "")))


def _se_from_payload(payload: dict) -> tuple[float | None, str]:
    pooled = []
    for tag in SE_TAGS:
        try:
            pooled.extend(payload["facts"]["us-gaap"][tag]["units"]["USD"])
        except KeyError:
            continue
    if not pooled:
        return None, ""
    qrt = [r for r in pooled if r.get("form") == "10-Q"]
    candidates = qrt if qrt else [r for r in pooled if r.get("form") == "10-K"]
    latest = _pick_latest_fact(candidates)
    if not latest or latest.get("val") is None:
        return None, ""
    return float(latest["val"]) / 1_000_000.0, latest.get("end", "")


def _shares_from_payload(payload: dict) -> tuple[float | None, str]:
    # Try dei first
    try:
        shares = payload["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
        latest = _pick_latest_fact(shares)
        if latest and latest.get("val") is not None:
            return float(latest["val"]) / 1_000_000.0, latest.get("end", "")
    except KeyError:
        pass
    # Fallback to us-gaap
    try:
        shares = payload["facts"]["us-gaap"]["CommonStockSharesOutstanding"]["units"]["shares"]
        latest = _pick_latest_fact(shares)
        if latest and latest.get("val") is not None:
            return float(latest["val"]) / 1_000_000.0, latest.get("end", "")
    except KeyError:
        pass
    return None, ""


def fetch_edgar(peers: list[dict]) -> list[dict]:
    """peers: [{'ticker': 'RKT', 'cik': '0001805526',
                'stkeq_name': 'RKT_StkEq', 'shares_name': 'RKT_Shares'}, ...]"""
    out = []
    for p in peers:
        try:
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{p['cik']}.json"
            payload = json.loads(http_get(url, timeout=40).decode("utf-8"))

            # Stockholders Equity
            val_m, as_of = _se_from_payload(payload)
            if val_m is not None:
                out.append({
                    "name": p["stkeq_name"],
                    "value": val_m,
                    "unit": "USDm",
                    "as_of": as_of,
                    "source": "SEC EDGAR",
                    "series_id": f"{p['ticker']}_SE",
                    "url": f"https://data.sec.gov/submissions/CIK{p['cik']}.json",
                })

            # Shares Outstanding
            sh_m, as_of_sh = _shares_from_payload(payload)
            if sh_m is not None:
                out.append({
                    "name": p["shares_name"],
                    "value": sh_m,
                    "unit": "m",
                    "as_of": as_of_sh,
                    "source": "SEC EDGAR",
                    "series_id": f"{p['ticker']}_SHRS",
                    "url": f"https://data.sec.gov/submissions/CIK{p['cik']}.json",
                })
        except Exception as e:
            print(f"EDGAR {p['ticker']}: ERROR {e}")
    return out
