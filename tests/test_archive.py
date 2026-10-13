import io
import zipfile
from datetime import date
from pathlib import Path

import httpx

from nem import archive

FIX = Path(__file__).parent / "fixtures"


def nested(text: str, n: int = 2) -> bytes:
    """A day zip containing n inner zips, like AEMO's archive layout."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as outer:
        for i in range(n):
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w") as z:
                z.writestr(f"f{i}.CSV", text)
            outer.writestr(f"f{i}.zip", inner.getvalue())
    return out.getvalue()


def client(body: bytes) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=body)))


def test_scada_day_reads_nested_zips(monkeypatch, tmp_path):
    monkeypatch.setattr(archive, "_cache_dir", lambda: tmp_path)
    df = archive.load_scada_day(date(2026, 10, 12), client(nested((FIX / "dispatchscada.csv").read_text())))
    assert {"interval_end", "duid", "mw"} == set(df.columns)
    assert len(df) % 2 == 0 and df["duid"].eq("ER01").sum() == 2


def test_prices_day_pairs_price_with_demand(monkeypatch, tmp_path):
    monkeypatch.setattr(archive, "_cache_dir", lambda: tmp_path)
    df = archive.load_prices_day(date(2026, 10, 12), client(nested((FIX / "dispatchis.csv").read_text(), 1)))
    nsw = df[df["region"] == "NSW1"].iloc[0]
    assert abs(nsw["rrp"] - 200.40963) < 1e-6 and abs(nsw["demand"] - 8220.08) < 1e-6
    assert len(df) == 5


def test_second_load_comes_from_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(archive, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(archive, "_complete", lambda df: True)
    calls = []
    def handler(req):
        calls.append(1)
        return httpx.Response(200, content=nested((FIX / "dispatchscada.csv").read_text(), 1))
    http = httpx.Client(transport=httpx.MockTransport(handler))
    archive.load_scada_day(date(2026, 10, 12), http)
    archive.load_scada_day(date(2026, 10, 12), http)
    assert len(calls) == 1


def test_archive_urls_match_nemweb_naming(monkeypatch, tmp_path):
    monkeypatch.setattr(archive, "_cache_dir", lambda: tmp_path)
    seen = []
    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, content=nested((FIX / "dispatchis.csv").read_text(), 1))
    http = httpx.Client(transport=httpx.MockTransport(handler))
    archive.load_scada_day(date(2026, 9, 28), http)
    archive.load_prices_day(date(2026, 9, 28), http)
    assert seen == [
        "https://nemweb.com.au/Reports/Archive/Dispatch_SCADA/PUBLIC_DISPATCHSCADA_20260928.zip",
        "https://nemweb.com.au/Reports/Archive/DispatchIS_Reports/PUBLIC_DISPATCHIS_20260928.zip",
    ]


def test_partial_day_is_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(archive, "_cache_dir", lambda: tmp_path)
    archive.load_scada_day(date(2026, 10, 12), client(nested((FIX / "dispatchscada.csv").read_text(), 1)))
    assert list(tmp_path.glob("scada_*")) == []  # one interval is not a day


def test_bad_archive_zip_raises_a_typed_error(monkeypatch, tmp_path):
    """Callers catch NemDataError for unusable NEMWeb files, so a bad zip must raise it too."""
    import pytest

    from nem import NemDataError

    monkeypatch.setattr(archive, "_cache_dir", lambda: tmp_path)
    with pytest.raises(NemDataError):
        archive.load_scada_day(date(2026, 10, 12), client(b"<html>not a zip</html>"))
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("f0.zip", b"also not a zip")
    with pytest.raises(NemDataError):
        archive.load_prices_day(date(2026, 10, 12), client(outer.getvalue()))


def test_parse_scada_rows_preserves_unicode_line_separator_in_duid():
    text = (
        'D,DISPATCH,UNIT_SCADA,1,2026/10/12 21:25:00,"WIND\u2028UNIT",12.5,x\n'
    )

    assert archive.parse_scada_rows(text) == [
        ("2026/10/12 21:25:00", "WIND\u2028UNIT", 12.5)
    ]
