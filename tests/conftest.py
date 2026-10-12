from pathlib import Path

import httpx
import pytest

from nem import NemClient

FIX = Path(__file__).parent / "fixtures"


def _zip(name: str, text: str) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def client(tmp_path) -> NemClient:
    """A NemClient wired to recorded fixtures: no network, ever."""
    is_zip = _zip("d.CSV", (FIX / "dispatchis.csv").read_text())
    scada_zip = _zip("s.CSV", (FIX / "dispatchscada.csv").read_text())
    gens = (FIX / "co2eii_generators.csv").read_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p.endswith("/DispatchIS_Reports/"):
            return httpx.Response(200, text='<A HREF="/Reports/CURRENT/DispatchIS_Reports/PUBLIC_DISPATCHIS_202610122130_1.zip">x</A>')
        if p.endswith("/Dispatch_SCADA/"):
            return httpx.Response(200, text='<A HREF="/Reports/CURRENT/Dispatch_SCADA/PUBLIC_DISPATCHSCADA_202610122125_1.zip">x</A>')
        if "PUBLIC_DISPATCHIS" in p:
            return httpx.Response(200, content=is_zip)
        if "PUBLIC_DISPATCHSCADA" in p:
            return httpx.Response(200, content=scada_zip)
        if p.endswith("CO2EII_AVAILABLE_GENERATORS.CSV"):
            return httpx.Response(200, content=gens)
        return httpx.Response(404)

    return NemClient(cache_dir=tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)))
