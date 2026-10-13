"""MCP server exposing live NEM data. Every tool returns plain JSON with units in the field names."""

from __future__ import annotations

import logging
import math

from mcp.server.mcpserver import MCPServer

from nem import NemClient, emissions_intensity, generation_mix, renewable_share, unmapped_mw
from nem.client import REGIONS

logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = MCPServer(
    "nem",
    instructions=(
        "Live data for Australia's National Electricity Market (NEM), from AEMO's NEMWeb. "
        "Regions: NSW1, QLD1, VIC1, SA1, TAS1. Times are NEM time (AEST, UTC+10). "
        "Prices are regional reference prices in $/MWh. The data is what AEMO published. "
        "It is not a forecast and it is not advice."
    ),
)
_client: NemClient | None = None


def client() -> NemClient:
    global _client
    if _client is None:
        _client = NemClient()
    return _client


def _check_region(region: str | None) -> str | None:
    if region is None:
        return None
    r = region.upper().strip()
    if r in {"NSW", "QLD", "VIC", "SA", "TAS"}:
        r += "1"
    if r not in REGIONS:
        raise ValueError(f"Unknown region {region!r}. Use one of {', '.join(REGIONS)}.")
    return r


@mcp.tool()
def get_current_prices() -> dict:
    """Regional reference price (RRP, $/MWh) and total demand (MW) for each NEM region.

    The data is for the latest 5 minute dispatch interval. The market floor price is -$1,000/MWh.
    The market price cap is above $20,000/MWh, and AEMO updates it each financial year.
    A negative price usually means there is more solar or wind than the region can use.
    """
    snap = client().dispatch_snapshots(1)[0]
    return {
        "interval_end_nem_time": snap.interval_end.isoformat(),
        "regions": [
            {"region": r.region, "price_aud_per_mwh": round(r.rrp, 2), "demand_mw": round(r.demand, 0)}
            for r in snap.prices.itertuples()
        ],
    }


@mcp.tool()
def get_generation_mix(region: str | None = None) -> dict:
    """Current generation by fuel (MW and share), renewable share and average emissions intensity.

    Args:
        region: Optional NEM region (NSW1, QLD1, VIC1, SA1, TAS1). Omit it for the whole NEM.

    The mix covers only units that send 5 minute SCADA data to AEMO. It does not include rooftop solar.
    Emissions intensity (t CO2e per MWh) is the average of local generation. It is not marginal and it
    ignores imports. unmapped_generation_mw_excluded is output from units that are not in AEMO's
    register. Those units have no region, so this number is always for the whole NEM.
    """
    r = _check_region(region)
    units = client().generation_by_unit()
    mix = generation_mix(units, r)
    return {
        "interval_end_nem_time": units["interval_end"].iloc[0].isoformat(),
        "region": r or "NEM",
        "total_generation_mw": round(float(mix["mw"].sum()), 0),
        "renewable_share": round(renewable_share(mix), 3),
        "emissions_intensity_tco2e_per_mwh": None if math.isnan(i := emissions_intensity(mix)) else round(i, 3),
        "unmapped_generation_mw_excluded": round(unmapped_mw(units), 0),
        "by_fuel": [
            {"fuel": x.fuel, "mw": round(x.mw, 0), "share": round(x.share, 3)} for x in mix.itertuples()
        ],
    }


@mcp.tool()
def get_interconnector_flows() -> dict:
    """Current power flow on each interconnector between regions (MW).

    A positive flow runs from `from_region` to `to_region`. A negative flow runs the other way.
    The export and import limits apply to this interval. A flow at its limit shows a constrained link.
    """
    snap = client().dispatch_snapshots(1)[0]
    return {
        "interval_end_nem_time": snap.interval_end.isoformat(),
        "interconnectors": [
            {
                "id": r.id,
                "from_region": r.from_region,
                "to_region": r.to_region,
                "flow_mw": round(r.mw_flow, 1),
                "losses_mw": round(r.losses_mw, 1),
                "export_limit_mw": round(r.export_limit, 1),
                "import_limit_mw": round(r.import_limit, 1),
            }
            for r in snap.interconnectors.itertuples()
        ],
    }


@mcp.tool()
def get_recent_price_spikes(
    region: str, hours: float = 2.0, above_aud_per_mwh: float = 300.0, below_aud_per_mwh: float = 0.0
) -> dict:
    """Intervals in the last few hours where the price in a region was high or negative.

    Args:
        region: NEM region (NSW1, QLD1, VIC1, SA1, TAS1).
        hours: How far back to look, up to 4 hours (48 intervals of 5 minutes).
        above_aud_per_mwh: Report intervals with a price above this value ($/MWh).
        below_aud_per_mwh: Report intervals with a price below this value ($/MWh). The default of 0
            reports negative prices.
    """
    r = _check_region(region)
    if r is None:
        raise ValueError("region is required")
    count = max(1, min(48, int(hours * 12)))
    rows = []
    snaps = client().dispatch_snapshots(count)
    for snap in snaps:
        row = snap.prices[snap.prices["region"] == r]
        if row.empty:
            continue
        price = float(row["rrp"].iloc[0])
        if price > above_aud_per_mwh or price < below_aud_per_mwh:
            rows.append(
                {
                    "interval_end_nem_time": snap.interval_end.isoformat(),
                    "price_aud_per_mwh": round(price, 2),
                    "demand_mw": round(float(row["demand"].iloc[0]), 0),
                    "kind": "high" if price > above_aud_per_mwh else "negative_or_low",
                }
            )
    return {"region": r, "intervals_checked": len(snaps),
        "intervals_requested": count, "events": rows}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
