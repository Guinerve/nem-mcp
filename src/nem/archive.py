"""Historical 5-minute data from AEMO's NEMWeb archive (one zip per day, 288 nested zips each)."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

BASE = "https://nemweb.com.au/Reports/Archive"


def _cache_dir() -> Path:
    p = Path.home() / ".cache" / "nem" / "archive"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _fetch_day_zip(report: str, prefix: str, day: date, http: httpx.Client | None) -> bytes:
    url = f"{BASE}/{report}/PUBLIC_{prefix}_{day:%Y%m%d}.zip"
    if http is None:
        with httpx.Client(timeout=180, follow_redirects=True) as own:
            resp = own.get(url)
    else:
        resp = http.get(url)
    resp.raise_for_status()
    return resp.content


def _inner_csvs(outer_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(outer_bytes)) as outer:
        for name in sorted(outer.namelist()):
            with zipfile.ZipFile(io.BytesIO(outer.read(name))) as inner:
                yield inner.read(inner.namelist()[0]).decode("utf-8", "replace")


def _complete(df: pd.DataFrame, min_intervals: int = 280) -> bool:
    """Only cache a day that looks complete, so a partial early fetch is never frozen in."""
    return df["interval_end"].nunique() >= min_intervals


def _write_atomic(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name("part-" + path.name)  # keep the real suffix so pandas compresses it
    df.to_csv(tmp, index=False)
    tmp.replace(path)


def _stamp(df: pd.DataFrame) -> pd.DataFrame:
    df["interval_end"] = pd.to_datetime(df["interval_end"], format="%Y/%m/%d %H:%M:%S")
    return df


def parse_scada_rows(text: str) -> list[tuple[str, str, float]]:
    out = []
    for rec in csv.reader(text.splitlines()):
        if len(rec) > 6 and rec[0] == "D" and rec[2] == "UNIT_SCADA" and rec[6] != "":
            out.append((rec[4], rec[5], float(rec[6])))
    return out


def parse_price_rows(text: str) -> list[tuple[str, str, float, float | None]]:
    """(interval_end, region, rrp, demand) from the PRICE and REGIONSUM tables, excluding interventions."""
    prices: dict[tuple[str, str], float] = {}
    demand: dict[tuple[str, str], float] = {}
    for rec in csv.reader(text.splitlines()):
        if len(rec) < 10 or rec[0] != "D" or rec[1] != "DISPATCH" or rec[8] != "0":
            continue
        if rec[2] == "PRICE":
            prices[(rec[4], rec[6])] = float(rec[9])
        elif rec[2] == "REGIONSUM":
            demand[(rec[4], rec[6])] = float(rec[9])
    return [(ts, reg, rrp, demand.get((ts, reg))) for (ts, reg), rrp in prices.items()]


def load_scada_day(day: date, http: httpx.Client | None = None, cache: bool = True) -> pd.DataFrame:
    """Unit output (interval_end, duid, mw) for one NEM day (intervals ending 00:05 to 24:00)."""
    path = _cache_dir() / f"scada_{day:%Y%m%d}.csv.gz"
    if cache and path.exists():
        return _stamp(pd.read_csv(path))
    rows = [r for text in _inner_csvs(_fetch_day_zip("Dispatch_SCADA", "DISPATCHSCADA", day, http)) for r in parse_scada_rows(text)]
    df = pd.DataFrame(rows, columns=["interval_end", "duid", "mw"])
    if cache and _complete(df):
        _write_atomic(df, path)
    return _stamp(df)


def load_prices_day(day: date, http: httpx.Client | None = None, cache: bool = True) -> pd.DataFrame:
    """Regional price and demand (interval_end, region, rrp, demand) for one NEM day."""
    path = _cache_dir() / f"prices_{day:%Y%m%d}.csv.gz"
    if cache and path.exists():
        return _stamp(pd.read_csv(path))
    rows = [r for text in _inner_csvs(_fetch_day_zip("DispatchIS_Reports", "DISPATCHIS", day, http)) for r in parse_price_rows(text)]
    df = pd.DataFrame(rows, columns=["interval_end", "region", "rrp", "demand"])
    if cache and _complete(df):
        _write_atomic(df, path)
    return _stamp(df)
