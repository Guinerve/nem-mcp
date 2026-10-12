import math

import pytest

from nem import emissions_intensity, generation_mix, renewable_share
from nem.mms import parse_mms


def test_parse_mms_handles_multiple_tables_and_blank_cells():
    text = (
        'C,NEMP.WORLD,X\n'
        'I,GRP,A,1,SETTLEMENTDATE,NAME,VALUE\n'
        'D,GRP,A,1,"2026/10/12 21:30:00",foo,1.5\n'
        'D,GRP,A,1,"2026/10/12 21:35:00",bar,\n'
        'I,GRP,B,1,K,V\n'
        'D,GRP,B,1,x,2\n'
        'C,"END OF REPORT",4\n'
    )
    t = parse_mms(text)
    assert set(t) == {"GRP.A", "GRP.B"}
    assert t["GRP.A"]["SETTLEMENTDATE"].iloc[0].isoformat() == "2026-10-12T21:30:00+10:00"
    assert t["GRP.A"]["VALUE"].iloc[0] == 1.5 and math.isnan(t["GRP.A"]["VALUE"].iloc[1])
    assert t["GRP.B"]["K"].iloc[0] == "x"


def test_prices_match_the_recorded_interval(client):
    snap = client.dispatch_snapshots(1)[0]
    assert snap.interval_end.isoformat() == "2026-10-12T21:30:00+10:00"
    p = snap.prices.set_index("region")
    assert p.loc["NSW1", "rrp"] == pytest.approx(200.40963)
    assert p.loc["SA1", "rrp"] == pytest.approx(19.33274)
    assert p.loc["NSW1", "demand"] == pytest.approx(8220.08)


def test_interconnector_flows_reconcile_with_region_pair_totals(client):
    """NSW1->QLD1 region-pair flow in AEMO's table is the sum of NSW1-QLD1 and N-Q-MNSP1."""
    ic = client.dispatch_snapshots(1)[0].interconnectors.set_index("id")
    assert ic.loc["NSW1-QLD1", "mw_flow"] + ic.loc["N-Q-MNSP1", "mw_flow"] == pytest.approx(-926.02725)
    assert ic.loc["V-SA", "mw_flow"] + ic.loc["V-S-MNSP1", "mw_flow"] == pytest.approx(348.09889)
    assert ic.loc["NSW1-QLD1", "from_region"] == "NSW1" and ic.loc["NSW1-QLD1", "to_region"] == "QLD1"


def test_generator_registry_maps_fuels(client):
    g = client.generators().set_index("duid")
    assert g.loc["ER01", "fuel"] == "Black coal" and g.loc["ER01", "region"] == "NSW1"
    assert g.loc["ER01", "ef_t_per_mwh"] == pytest.approx(0.87893798)
    assert g.loc["AVLSF1", "fuel"] == "Solar" and g.loc["AVLSF1", "ef_t_per_mwh"] == 0


def test_generation_mix_is_consistent(client):
    units = client.generation_by_unit()
    mix = generation_mix(units)
    assert mix["share"].sum() == pytest.approx(1.0)
    assert mix.iloc[0]["fuel"] == "Black coal"
    assert 0.5 < emissions_intensity(mix) < 0.8  # evening, coal-heavy interval
    assert 0 < renewable_share(mix) < 0.5


def test_regional_mix_picks_out_wind_heavy_sa(client):
    sa = generation_mix(client.generation_by_unit(), "SA1")
    assert sa.iloc[0]["fuel"] == "Wind"
    assert emissions_intensity(sa) < 0.1
    assert renewable_share(sa) > 0.8


def test_cache_means_second_fetch_skips_the_network(client):
    client.dispatch_snapshots(1)
    calls = []
    original = client.http.get
    client.http.get = lambda url, *a, **k: calls.append(url) or original(url, *a, **k)
    client.dispatch_snapshots(1)
    assert [c for c in calls if c.endswith(".zip")] == []


def test_empty_listing_raises_a_typed_error(tmp_path):
    import httpx

    from nem import NemClient, NemDataError

    c = NemClient(cache_dir=tmp_path, http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>nothing</html>"))))
    with pytest.raises(NemDataError):
        c.dispatch_snapshots(1)


def test_report_missing_tables_raises_typed_error():
    from nem import NemClient, NemDataError

    with pytest.raises(NemDataError):
        NemClient.parse_dispatch_is("C,only a comment\n")


def test_unmapped_generation_is_reported(client):
    from nem import unmapped_mw

    assert unmapped_mw(client.generation_by_unit()) > 0
