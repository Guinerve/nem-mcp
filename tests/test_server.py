import pytest

from nem_mcp import server


@pytest.fixture(autouse=True)
def use_fixture_client(client, monkeypatch):
    monkeypatch.setattr(server, "_client", client)


def test_get_current_prices():
    out = server.get_current_prices()
    nsw = next(r for r in out["regions"] if r["region"] == "NSW1")
    assert nsw["price_aud_per_mwh"] == 200.41 and nsw["demand_mw"] == 8220
    assert out["interval_end_nem_time"].startswith("2026-10-12T21:30")


def test_get_generation_mix_whole_nem_and_region():
    nem = server.get_generation_mix()
    assert nem["region"] == "NEM" and nem["by_fuel"][0]["fuel"] == "Black coal"
    sa = server.get_generation_mix("sa")
    assert sa["region"] == "SA1" and sa["renewable_share"] > 0.8


def test_unknown_region_gives_a_helpful_error():
    with pytest.raises(ValueError, match="Use one of"):
        server.get_generation_mix("ATLANTIS")


def test_interconnectors_have_units_and_direction():
    out = server.get_interconnector_flows()
    row = next(r for r in out["interconnectors"] if r["id"] == "VIC1-NSW1")
    assert row["from_region"] == "VIC1" and row["flow_mw"] > 0


def test_price_spike_scan():
    out = server.get_recent_price_spikes("NSW1", hours=1, above_aud_per_mwh=150)
    assert out["events"] and out["events"][0]["kind"] == "high"
    assert server.get_recent_price_spikes("SA1", hours=1)["events"] == []


def test_tools_are_registered_with_descriptions():
    import asyncio

    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert {"get_current_prices", "get_generation_mix", "get_interconnector_flows", "get_recent_price_spikes"} <= names
    assert all(t.description for t in tools)


def test_price_spike_scan_flags_low_prices_and_caps_the_window():
    out = server.get_recent_price_spikes("SA1", hours=100, below_aud_per_mwh=50)
    assert out["intervals_requested"] == 48  # 4 hours of 5-minute intervals
    assert [e["kind"] for e in out["events"]] == ["negative_or_low"]
    assert out["events"][0]["price_aud_per_mwh"] == 19.33
