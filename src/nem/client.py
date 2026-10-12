"""A small client for AEMO NEMWeb "current" reports.

Everything goes through one `httpx.Client`, so tests can inject a MockTransport and CI
never depends on the live feed.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd

from .fuels import RENEWABLE_GROUPS, fuel_group
from .mms import parse_mms

BASE_URL = "https://nemweb.com.au"
REGIONS = ["NSW1", "QLD1", "SA1", "TAS1", "VIC1"]
_PAIRS = {
    "NSW1-QLD1": ("NSW1", "QLD1"),
    "N-Q-MNSP1": ("NSW1", "QLD1"),
    "VIC1-NSW1": ("VIC1", "NSW1"),
    "NSW1-SA1": ("NSW1", "SA1"),
    "V-SA": ("VIC1", "SA1"),
    "V-S-MNSP1": ("VIC1", "SA1"),
    "T-V-MNSP1": ("TAS1", "VIC1"),
}
_LINK = re.compile(r'HREF="([^"]+\.(?:zip|CSV|csv))"', re.IGNORECASE)


class NemDataError(RuntimeError):
    """NEMWeb returned something we can't use (empty listing, missing table, bad zip)."""


@dataclass
class DispatchSnapshot:
    """One 5-minute dispatch interval from a DispatchIS report."""

    interval_end: pd.Timestamp
    prices: pd.DataFrame  # region, rrp ($/MWh), demand (MW)
    interconnectors: pd.DataFrame  # id, from_region, to_region, mw_flow, losses_mw, limits


class NemClient:
    def __init__(
        self,
        cache_dir: str | Path | None = None,
        http: httpx.Client | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=30, follow_redirects=True)
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "nem"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- transport -----------------------------------------------------------------
    def _get(self, url: str, immutable: bool = False) -> bytes:
        """Fetch a URL. Timestamped report files never change, so they are cached on disk."""
        cache = self.cache_dir / url.split("/Reports/", 1)[-1].replace("/", "__") if immutable else None
        if cache is not None and cache.exists():
            return cache.read_bytes()
        resp = self.http.get(url)
        resp.raise_for_status()
        if cache is not None:
            tmp = cache.with_suffix(cache.suffix + ".part")
            tmp.write_bytes(resp.content)
            tmp.replace(cache)  # atomic: a crash never leaves a truncated cache file
        return resp.content

    def list_files(self, report: str) -> list[str]:
        """Absolute URLs for the files in a Reports/Current directory, oldest first."""
        url = f"{self.base_url}/Reports/Current/{report}/"
        html = self._get(url).decode("utf-8", "replace")
        links = [self.base_url + h if h.startswith("/") else h for h in _LINK.findall(html)]
        if not links:
            raise NemDataError(f"no report files listed at {url} (page layout changed or empty)")
        return sorted(links)

    @staticmethod
    def _read_zip_csv(blob: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                return zf.read(name).decode("utf-8", "replace")
        except (zipfile.BadZipFile, StopIteration) as exc:
            raise NemDataError(f"unusable report zip: {type(exc).__name__}") from exc

    # ---- reports -------------------------------------------------------------------
    def dispatch_snapshots(self, count: int = 1) -> list[DispatchSnapshot]:
        """The latest `count` dispatch intervals (5 minutes each), oldest first."""
        urls = self.list_files("DispatchIS_Reports")[-count:]
        return [self.parse_dispatch_is(self._read_zip_csv(self._get(u, immutable=True))) for u in urls]

    @staticmethod
    def parse_dispatch_is(text: str) -> DispatchSnapshot:
        tables = parse_mms(text)
        for need in ("DISPATCH.PRICE", "DISPATCH.REGIONSUM", "DISPATCH.INTERCONNECTORRES"):
            if need not in tables or tables[need].empty:
                raise NemDataError(f"report is missing table {need}")
        price = tables["DISPATCH.PRICE"]
        price = price[price["INTERVENTION"] == 0]
        region = tables["DISPATCH.REGIONSUM"]
        region = region[region["INTERVENTION"] == 0]
        prices = price[["REGIONID", "RRP"]].merge(
            region[["REGIONID", "TOTALDEMAND"]], on="REGIONID", how="left"
        )
        prices.columns = ["region", "rrp", "demand"]
        ic = tables["DISPATCH.INTERCONNECTORRES"]
        ic = ic[ic["INTERVENTION"] == 0][["INTERCONNECTORID", "MWFLOW", "MWLOSSES", "EXPORTLIMIT", "IMPORTLIMIT"]]
        ic.columns = ["id", "mw_flow", "losses_mw", "export_limit", "import_limit"]
        # Positive MWFLOW is from the first-named region to the second. Verified against the region-pair
        # totals in DISPATCH.INTERCONNECTION (e.g. NSW1-QLD1 + N-Q-MNSP1 = NSW1 to QLD1).
        ic["from_region"] = ic["id"].map(lambda i: _PAIRS.get(i, (None, None))[0])
        ic["to_region"] = ic["id"].map(lambda i: _PAIRS.get(i, (None, None))[1])
        interval_end = price["SETTLEMENTDATE"].iloc[0]
        return DispatchSnapshot(interval_end, prices.reset_index(drop=True), ic.reset_index(drop=True))

    def generators(self) -> pd.DataFrame:
        """DUID registry from AEMO's CDEII feed: station, region, emissions factor, fuel group."""
        url = f"{self.base_url}/Reports/Current/CDEII/CO2EII_AVAILABLE_GENERATORS.CSV"
        return self.parse_generators(self._get(url).decode("utf-8", "replace"))

    @staticmethod
    def parse_generators(text: str) -> pd.DataFrame:
        df = parse_mms(text)["CO2EII.PUBLISHING"]
        df = df.rename(
            columns={
                "STATIONNAME": "station",
                "DUID": "duid",
                "REGIONID": "region",
                "CO2E_EMISSIONS_FACTOR": "ef_t_per_mwh",
                "CO2E_ENERGY_SOURCE": "source",
            }
        )
        df["fuel"] = df["source"].map(fuel_group)
        return df[["duid", "station", "region", "ef_t_per_mwh", "source", "fuel"]].drop_duplicates("duid")

    def scada(self) -> pd.DataFrame:
        """Latest 5-minute unit output (MW) by DUID."""
        url = self.list_files("Dispatch_SCADA")[-1]
        return self.parse_scada(self._read_zip_csv(self._get(url, immutable=True)))

    @staticmethod
    def parse_scada(text: str) -> pd.DataFrame:
        df = parse_mms(text)["DISPATCH.UNIT_SCADA"]
        out = df.rename(columns={"SETTLEMENTDATE": "interval_end", "DUID": "duid", "SCADAVALUE": "mw"})
        return out[["interval_end", "duid", "mw"]]

    def generation_by_unit(self) -> pd.DataFrame:
        """SCADA output joined to the generator registry. Units not in the registry have fuel NaN."""
        return self.scada().merge(self.generators(), on="duid", how="left")


def unmapped_mw(units: pd.DataFrame) -> float:
    """Positive output from units missing from the generator registry (excluded from the mix)."""
    return float(units.loc[units["fuel"].isna() & (units["mw"] > 0), "mw"].sum())


def generation_mix(units: pd.DataFrame, region: str | None = None) -> pd.DataFrame:
    """MW and share by fuel group, plus emissions. Negative MW (e.g. battery charging) is excluded
    from the mix and reported separately by the caller."""
    df = units.dropna(subset=["fuel"])
    if region:
        df = df[df["region"] == region]
    df = df[df["mw"] > 0].copy()
    df["tco2e_per_h"] = df["mw"] * df["ef_t_per_mwh"]
    mix = df.groupby("fuel", as_index=False).agg(mw=("mw", "sum"), tco2e_per_h=("tco2e_per_h", "sum"))
    total = mix["mw"].sum()
    mix["share"] = mix["mw"] / total if total else 0.0
    return mix.sort_values("mw", ascending=False).reset_index(drop=True)


def emissions_intensity(mix: pd.DataFrame) -> float:
    """Generation-weighted average emissions intensity, t CO2e per MWh (average, not marginal)."""
    total = mix["mw"].sum()
    return float(mix["tco2e_per_h"].sum() / total) if total else float("nan")


def renewable_share(mix: pd.DataFrame) -> float:
    total = mix["mw"].sum()
    return float(mix.loc[mix["fuel"].isin(RENEWABLE_GROUPS), "mw"].sum() / total) if total else 0.0
