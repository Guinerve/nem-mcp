"""Call the real server over stdio and draw the results as assets/demo.svg.

Run from the repo root: uv run python scripts/render_demo.py
It needs network access to NEMWeb. The raw tool output is also saved to assets/demo.json.
Add --from-json to redraw the SVG from the saved assets/demo.json without new calls.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime
from html import escape
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
CALLS = [("get_current_prices", {}), ("get_generation_mix", {"region": "SA1"})]

BG, PANEL, BORDER = "#0d1117", "#161b22", "#30363d"
TEXT, DIM, KEY, STR, NUM, ACCENT = "#e6edf3", "#8b949e", "#79c0ff", "#a5d6ff", "#ffa657", "#7ee787"
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
LINE, CHAR, PAD = 19, 7.8, 20


async def capture() -> list[tuple[str, dict, dict]]:
    params = StdioServerParameters(command="uv", args=["--directory", str(ROOT), "run", "nem-mcp"])
    out = []
    async with Client(params) as c:
        for name, args in CALLS:
            result = await c.call_tool(name, args)
            if result.is_error:
                raise SystemExit(f"{name} failed: {result.content}")
            out.append((name, args, json.loads(result.content[0].text)))
    return out


def compact(obj: dict) -> list[str]:
    """Pretty JSON, but each small object in a list stays on one line."""
    lines = ["{"]
    items = list(obj.items())
    for i, (k, v) in enumerate(items):
        end = "," if i < len(items) - 1 else ""
        if isinstance(v, list):
            lines.append(f'  "{k}": [')
            for j, row in enumerate(v):
                sep = "," if j < len(v) - 1 else ""
                lines.append("    " + json.dumps(row, separators=(", ", ": ")) + sep)
            lines.append("  ]" + end)
        else:
            lines.append(f'  "{k}": {json.dumps(v)}{end}')
    lines.append("}")
    return lines


TOKEN = re.compile(r'("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?)|(null|true|false)|([^"\d\-nft]+|.)')


def colour(line: str) -> str:
    parts = []
    for s, colon, num, lit, other in TOKEN.findall(line):
        if s:
            parts.append(f'<tspan fill="{KEY if colon else STR}">{escape(s)}</tspan>{escape(colon)}')
        elif num:
            parts.append(f'<tspan fill="{NUM}">{num}</tspan>')
        elif lit:
            parts.append(f'<tspan fill="{NUM}">{lit}</tspan>')
        else:
            parts.append(escape(other))
    return "".join(parts)


def panel(x: float, width: float, name: str, args: dict, body: list[str], rows: int) -> str:
    head = 64
    height = head + rows * LINE + PAD
    call = f"{name}({json.dumps(args)[1:-1]})" if args else f"{name}()"
    svg = [
        f'<rect x="{x}" y="56" width="{width}" height="{height}" rx="8" fill="{PANEL}" stroke="{BORDER}"/>',
        (
            f'<text x="{x + PAD}" y="84" fill="{DIM}" xml:space="preserve">tool call  '
            f'<tspan fill="{ACCENT}">{escape(call)}</tspan></text>'
        ),
        f'<line x1="{x}" y1="{56 + head - 18}" x2="{x + width}" y2="{56 + head - 18}" stroke="{BORDER}"/>',
    ]
    for i, line in enumerate(body):
        y = 56 + head + 6 + i * LINE
        svg.append(f'<text x="{x + PAD}" y="{y}" fill="{TEXT}" xml:space="preserve">{colour(line)}</text>')
    return "\n".join(svg)


def render(results: list[tuple[str, dict, dict]]) -> str:
    bodies = [compact(r) for _, _, r in results]
    widths = [max(len(s) for s in b) * CHAR + 2 * PAD for b in bodies]
    gap, margin = 20, 20
    total_w = sum(widths) + gap * (len(widths) - 1) + 2 * margin
    rows = max(len(b) for b in bodies)
    panels, x = [], margin
    for (name, args, _), body, w in zip(results, bodies, widths, strict=True):
        panels.append(panel(x, w, name, args, body, rows))
        x += w + gap
    total_h = 56 + 64 + rows * LINE + PAD + margin
    day = datetime.fromisoformat(results[0][2]["interval_end_nem_time"]).strftime("%-d %b %Y")
    title = f"nem-mcp: two real tool calls over stdio, with live AEMO data from {day}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" height="{total_h:.0f}" '
        f'viewBox="0 0 {total_w:.0f} {total_h:.0f}" font-family="{FONT}" font-size="13">\n'
        f"<title>{escape(title)}</title>\n"
        f'<rect width="100%" height="100%" rx="10" fill="{BG}"/>\n'
        f'<circle cx="{margin + 6}" cy="28" r="6" fill="#ff5f57"/>'
        f'<circle cx="{margin + 26}" cy="28" r="6" fill="#febc2e"/>'
        f'<circle cx="{margin + 46}" cy="28" r="6" fill="#28c840"/>\n'
        f'<text x="{margin + 66}" y="32" fill="{DIM}">{escape(title)}</text>\n'
        + "\n".join(panels)
        + "\n</svg>\n"
    )


def main() -> None:
    assets = ROOT / "assets"
    if "--from-json" in sys.argv:
        raw = json.loads((assets / "demo.json").read_text())
        results = [(c["tool"], c["arguments"], c["result"]) for c in raw]
    else:
        results = asyncio.run(capture())
        assets.mkdir(exist_ok=True)
        raw = [{"tool": n, "arguments": a, "result": r} for n, a, r in results]
        (assets / "demo.json").write_text(json.dumps(raw, indent=2) + "\n")
    (assets / "demo.svg").write_text(render(results))
    print(f"wrote {assets / 'demo.svg'} and {assets / 'demo.json'}")


if __name__ == "__main__":
    main()
