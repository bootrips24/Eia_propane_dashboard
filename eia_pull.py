"""
eia_pull.py

Pulls weekly US propane/propylene stocks (kbbl) from the EIA API,
calculates the 5-year seasonal min/max band and percentile rank for
each observation, and writes the result to propane_dashboard.csv.

Requires an environment variable EIA_API_KEY to be set.
In GitHub Actions, this is injected from the repo secret of the same name.
Locally, you can set it in your terminal before running, e.g.:
    export EIA_API_KEY="your_key_here"      (Mac/Linux)
    set EIA_API_KEY=your_key_here           (Windows cmd)
"""

import os
import sys
from datetime import date, datetime

import pandas as pd
import requests

API_URL = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
OUTPUT_FILE = "propane_dashboard.csv"

# EIA facet codes: EPLLPZ = propane/propylene, NUS = US total,
# SAXP = "Ending Stocks Excluding Propylene at Terminal" (series WPRSTUS1) —
# this is the actively-published weekly series; the SAE process code was
# discontinued around April 2020 and no longer updates.
PRODUCT_CODE = "EPLLPZ"
AREA_CODE = "NUS"
PROCESS_CODE = "SAXP"


def get_api_key() -> str:
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        print("ERROR: EIA_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return key


def fetch_propane_stocks(api_key: str) -> pd.DataFrame:
    """Pull the full weekly history of US propane stocks from EIA."""
    params = {
        "api_key": api_key,
        "frequency": "weekly",
        "data[0]": "value",
        "facets[product][]": PRODUCT_CODE,
        "facets[duoarea][]": AREA_CODE,
        "facets[process][]": PROCESS_CODE,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
        "offset": 0,
    }

    all_rows = []
    while True:
        resp = requests.get(API_URL, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"ERROR: EIA API returned HTTP {resp.status_code}", file=sys.stderr)
            print(resp.text[:500], file=sys.stderr)
            sys.exit(1)

        payload = resp.json()
        rows = payload.get("response", {}).get("data", [])
        if not rows:
            break

        all_rows.extend(rows)

        # EIA paginates; keep pulling until a page comes back short of the page size
        if len(rows) < params["length"]:
            break
        params["offset"] += params["length"]

    if not all_rows:
        print("ERROR: No data returned from EIA API. Check API key and facet codes.", file=sys.stderr)
        sys.exit(1)

    df = pd.DataFrame(all_rows)
    df["period"] = pd.to_datetime(df["period"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df = df[["period", "value"]].rename(columns={"period": "date", "value": "stocks_kbbl"})
    df = df.sort_values("date").reset_index(drop=True)
    return df


def add_5yr_band(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each row, calculate the 5-year seasonal min/max band and percentile
    rank using the same ISO week across the prior 5 years (excluding the
    current year itself, matching the earlier Power BI methodology).
    """
    df = df.copy()
    df["iso_week"] = df["date"].dt.isocalendar().week
    df["year"] = df["date"].dt.year

    band_mins, band_maxs, pct_ranks = [], [], []

    for _, row in df.iterrows():
        wk, yr = row["iso_week"], row["year"]
        hist_years = range(yr - 5, yr)
        hist_values = df[(df["iso_week"] == wk) & (df["year"].isin(hist_years))]["stocks_kbbl"]

        if len(hist_values) >= 2:
            b_min, b_max = hist_values.min(), hist_values.max()
            if b_max > b_min:
                pct = (row["stocks_kbbl"] - b_min) / (b_max - b_min) * 100
            else:
                pct = None
        else:
            b_min, b_max, pct = None, None, None

        band_mins.append(b_min)
        band_maxs.append(b_max)
        pct_ranks.append(pct)

    df["band_5yr_min"] = band_mins
    df["band_5yr_max"] = band_maxs
    df["percentile_rank"] = pct_ranks
    return df.drop(columns=["iso_week", "year"])


def add_week_over_week(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["wow_change_kbbl"] = df["stocks_kbbl"].diff()
    return df


def main():
    api_key = get_api_key()
    print("Fetching weekly propane stocks from EIA...")
    df = fetch_propane_stocks(api_key)
    print(f"Pulled {len(df)} weekly observations "
          f"({df['date'].min().date()} to {df['date'].max().date()})")

    print("Calculating 5-year seasonal band and percentile rank...")
    df = add_5yr_band(df)
    df = add_week_over_week(df)

    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df["pulled_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Wrote {len(df)} rows to {OUTPUT_FILE}")

    latest = df.iloc[-1]
    pct_str = f"{latest['percentile_rank']:.0f}" if pd.notna(latest["percentile_rank"]) else "n/a"
    print(f"Latest week: {latest['date']} | "
          f"Stocks: {latest['stocks_kbbl']:,.0f} kbbl | "
          f"5yr percentile: {pct_str}")


if __name__ == "__main__":
    main()
