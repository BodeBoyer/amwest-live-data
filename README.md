# live-data

Universal daily refresh of public market data, consumed by multiple Excel workbooks (AmWest, CoverageX, and any future company).

## What it does

GitHub Actions runs `refresh.py` every weekday at **11:30 UTC** (7:30 AM EDT / 6:30 AM EST), pulling:

- **FRED** rates and macro series (rates, mortgage, housing, CPI, auto, consumer, etc.)
- **Yahoo Finance** peer prices and ETF prices
- **SEC EDGAR** XBRL company facts (stockholders' equity, shares outstanding)

The refresh builds a UNION of all unique series across every `configs/{id}.json` file, fetches each item exactly once per run, then distributes to per-company `data/{id}/livedata.json` files. Shared series (DGS10, MORTGAGE30US, UNRATE, etc.) are fetched once and appear in every workbook that needs them.

## Endpoints

Each workbook reads its own self-contained file from a raw GitHub URL (no auth — public repo):

| Company | URL |
|---|---|
| AmWest | `https://raw.githubusercontent.com/BodeBoyer/live-data/main/data/amwest/livedata.json` |
| CoverageX | `https://raw.githubusercontent.com/BodeBoyer/live-data/main/data/coveragex/livedata.json` |
| Dated history | `…/data/{company_id}/history/YYYY-MM-DD.json` |

Old `BodeBoyer/amwest-live-data` URLs auto-redirect to `BodeBoyer/live-data` thanks to GitHub's repo rename redirect — no consumer code breaks.

## Adding a company

1. Drop `configs/{id}.json` in the same shape as `configs/amwest.json` or `configs/coveragex.json`
2. Commit + push (or wait for the next scheduled run)
3. The job auto-discovers it and publishes `data/{id}/livedata.json`

Each company config declares which FRED series, Yahoo tickers, and EDGAR peers it needs. Overlap with other companies is automatic and free — the deduplicating fetcher only does the work once.

## Manual run

Actions tab → "Refresh live data" → Run workflow.

## Consuming the feed from a workbook

The recommended pattern (see `coveragex-master-v56/scripts/refresh_live_data.py`) is a small Python script that:

1. Pulls `https://raw.githubusercontent.com/BodeBoyer/live-data/main/data/{company}/livedata.json`
2. Matches FRED rows in the workbook's Live Data tab by `series_id` (in-place update, no duplicate rows)
3. Matches Yahoo peer rows by ticker
4. Captures prior values for drift detection

The same script works for any workbook by passing `--company` and `--workbook` flags.

## Data sources (all public, no API keys)

- [FRED](https://fred.stlouisfed.org/) — public CSV graphs
- [Yahoo Finance chart API](https://query1.finance.yahoo.com/v8/finance/chart/) — public JSON
- [SEC EDGAR company facts](https://data.sec.gov/api/xbrl/companyfacts/) — public JSON, requires User-Agent

Refresh code is `refresh.py` + `pullers.py` (Python stdlib only — no `requests`, no `openpyxl`, runs anywhere Python 3 runs).
