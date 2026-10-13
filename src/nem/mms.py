"""Parser for AEMO's MMS CSV format.

A file is a sequence of rows whose first field says what they are:
  C  comment / footer
  I  information: declares a table and its column names
  D  data row for the most recently declared table with the same name
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict

import pandas as pd

NEM_TZ = "Etc/GMT-10"  # the NEM runs on AEST (UTC+10) all year, with no daylight saving


def parse_mms(text: str) -> dict[str, pd.DataFrame]:
    """Return {"GROUP.TABLE": DataFrame}. Values are numeric where every value in a column is."""
    headers: dict[str, list[str]] = {}
    rows: dict[str, list[list[str]]] = defaultdict(list)
    for rec in csv.reader(io.StringIO(text)):
        if not rec:
            continue
        kind = rec[0]
        if kind == "I":
            headers[f"{rec[1]}.{rec[2]}"] = rec[4:]
        elif kind == "D":
            key = f"{rec[1]}.{rec[2]}"
            if key in headers:
                rows[key].append(rec[4:])
    out: dict[str, pd.DataFrame] = {}
    for key, cols in headers.items():
        data = rows.get(key, [])
        width = len(cols)
        df = pd.DataFrame([r[:width] + [""] * (width - len(r)) for r in data], columns=cols)
        out[key] = _coerce(df)
    return out


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if col.endswith(("DATE", "DATETIME")) or col == "LASTCHANGED":
            parsed = pd.to_datetime(df[col], format="%Y/%m/%d %H:%M:%S", errors="coerce")
            if parsed.notna().any():
                df[col] = parsed.dt.tz_localize(NEM_TZ)
                continue
        numeric = pd.to_numeric(df[col].replace("", pd.NA), errors="coerce")
        non_blank = df[col].ne("")
        if non_blank.any() and numeric[non_blank].notna().all():
            df[col] = numeric
    return df
