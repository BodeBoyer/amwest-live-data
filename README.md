# amwest-live-data

Daily refresh of public market data used by the [AmWest Master v3](https://github.com/BodeBoyer/amwest-master-v3) Excel workbook (private).

## What it does

GitHub Actions runs `refresh.py` every weekday at **11:30 UTC** (7:30 AM EDT / 6:30 AM EST), pulling:

- FRED rates and macro series (10Y/2Y UST, SOFR, Fed Funds, MBA mortgage rates, housing starts, CPI, unemployment, etc.)
- Yahoo Finance peer prices (RKT, UWMC, PFSI, LDI, VEL) + MBS ETFs (MBB, VMBS)
- SEC EDGAR XBRL company facts (stockholders' equity, shares outstanding) for peer set

The job commits the refreshed JSON back to this repo under `data/{company_id}/`.

## Endpoints

The Excel workbook reads from raw GitHub URLs (no auth — public repo):

| What | URL |
|---|---|
| Latest snapshot | `https://raw.githubusercontent.com/BodeBoyer/amwest-live-data/main/data/amwest/livedata.json` |
| Dated history | `https://raw.githubusercontent.com/BodeBoyer/amwest-live-data/main/data/amwest/history/YYYY-MM-DD.json` |

## Adding a company

Drop a new `configs/{id}.json` in the same shape as `configs/amwest.json`. The next scheduled run picks it up automatically and starts publishing `data/{id}/livedata.json`.

## Manual run

Actions tab → "Refresh live data" → Run workflow.

## Data sources (all public, no API keys)

- [FRED](https://fred.stlouisfed.org/) — public CSV graphs
- [Yahoo Finance chart API](https://query1.finance.yahoo.com/v7/finance/chart/) — public JSON
- [SEC EDGAR company facts](https://data.sec.gov/api/xbrl/companyfacts/) — public JSON, requires User-Agent

Refresh code is `refresh.py` + `pullers.py` (Python stdlib only).
