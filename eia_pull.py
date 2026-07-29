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

# EIA facet codes: EPLLPZ = propane/propylene, NUS = US total, SAE = Ending Stocks
# (confirmed against /v2/petroleum/stoc/wstk/facet/product/ and /facet/duoarea/)
PRODUCT_CODE = "EPLLPZ"
AREA_CODE = "NUS"
PROCESS_CODE = "SAE"


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
