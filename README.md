# nem-mcp

> An MCP server that gives any AI assistant live access to Australian grid data.

**Status:** v0.1 core built and verified against live NEMWeb · Portfolio project #6 · see `../README.md`

## The idea

Let Claude or any MCP client answer "What's the price in SA right now, and why is it negative?" from live AEMO data.

## Stack

Python (uv), the official MCP Python SDK, httpx, pandas, pytest.

Python project managed with `uv`; target a one-command run (`uv run ...`).

## Build plan (v1)

- [x] Shared `nem` data client (`src/nem/`): MMS CSV parser, NEMWeb "current" reports (DispatchIS, Dispatch_SCADA, CDEII generator registry), a daily **archive** loader, fuel grouping, generation mix and emissions intensity. Disk cache for immutable files. Reused by `carbon-aware-au` and `nem-pulse` as a path dependency. reading NEMWeb "current" files, with caching (reused by `carbon-aware-au` and `nem-pulse`)
- [x] Tools: `get_current_prices`, `get_generation_mix`, `get_interconnector_flows`, `get_recent_price_spikes`, generation mix by fuel, interconnector flows, recent price spikes
- [x] Clear tool descriptions and units in every response (units are in the field names)
- [ ] Demo transcript and GIF in the README

## Run it

```bash
uv sync
uv run pytest -q          # 21 tests, no network
uv run nem-mcp            # stdio MCP server
```

Claude Code / Claude Desktop config:

```json
{ "mcpServers": { "nem": { "command": "uv", "args": ["--directory", "/path/to/nem-mcp", "run", "nem-mcp"] } } }
```

## How I know it's right

- **Recorded fixtures**: 21 tests run against a real DispatchIS interval, a real SCADA interval and the real generator registry (`tests/fixtures/`), through an `httpx.MockTransport`, so CI never touches the live feed.
- **Interconnector sign convention** (positive = from the first-named region to the second) was checked against AEMO's own region-pair table in the same file: `NSW1-QLD1` + `N-Q-MNSP1` = −926.03 MW = the published `NSW1→QLD1` total, and `V-SA` + `V-S-MNSP1` = +348.10 = `VIC1→SA1`. This is a test.
- Live run (2026-10-12 21:35 NEM time): prices came back for all five regions; SA was 91 % wind at $19.96/MWh while NSW (71 % black coal) was $200.75/MWh with power flowing toward it. Plausible, but **not yet spot-checked line by line against AEMO's dashboard**.
- Emissions intensity from this feed is validated against AEMO's published CDEII in `carbon-aware-au` (mean error 2.8 % over 35 region-days).

## Limits

The generation mix covers scheduled and semi-scheduled units with SCADA data; **rooftop solar is not included**. Units missing from the CDEII registry (e.g. pumped-hydro and battery charging loads) are dropped and reported as `unmapped_generation_mw_excluded`. Unusable NEMWeb responses raise a typed `NemDataError`, and an empty region gives `null` intensity, never NaN. Battery output is counted as generation only when positive. Intensity is an average of local generation, not marginal, and ignores imports.

Reports published data only; no forecasts or trading advice. Fuel mapping depends on AEMO registration data.

## Next (tomorrow)

- Add rooftop PV (ROOFTOP_PV/ACTUAL) so shares are not understated for NSW/QLD/SA by day.
- A real client test: run the server over stdio from an MCP client and record the demo transcript and GIF.
- Spot-check against AEMO's dashboard for one interval.
- A `why did the price spike` tool using binding constraints from `DISPATCH.CONSTRAINT`.

## Stretch

Historical queries via NEMOSIS; a "why did the price spike?" tool that pulls binding constraints.

## Definition of done

- [ ] Hero GIF or screenshot at the top of this README
- [x] Live demo link or one-command run (`uv run nem-mcp`)
- [ ] "How I know it's right" section filled in with real results
- [ ] Tests passing in CI, badge added
- [ ] "Limits" section written
- [ ] Licence chosen, repo description and topics set
- [ ] Pinned on GitHub profile and added to guinerve.github.io
- [ ] Added to `career-radar/data/cv/portfolio.json`
