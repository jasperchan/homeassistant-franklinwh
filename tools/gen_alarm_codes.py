"""Regenerate ``alarm_codes.py`` from a captured ``selectDeviceRunLogList`` reply.

Usage (run with ``-I`` because the input is captured data, not code)::

    python3 -I tools/gen_alarm_codes.py runlog_catalog.json [-o alarm_codes.py]

The input may be the bare ``result`` list, the full ``{"code": 200, "result":
[...]}`` envelope, or a probe dump that holds the envelope under a
``runlog_catalog`` key. Each entry needs ``alarmCode`` and ``enLogName``.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import sys
from typing import Any

HEADER = '''"""FranklinWH alarm code catalog (generated, do not edit by hand).

Maps ``alarmCode`` to the vendor's English log name as returned by
``hes-gateway/terminal/selectDeviceRunLogList``. Regenerate with
``tools/gen_alarm_codes.py`` from a fresh capture.
"""

from typing import Final

ALARM_CODES: Final[dict[str, str]] = {
'''

FOOTER = '''}


def alarm_name(code: str | None) -> str | None:
    """Return the catalog name for an alarm code, ``None`` when unknown."""
    if code is None:
        return None
    return ALARM_CODES.get(str(code).strip().upper())
'''


def extract_entries(payload: Any) -> list[Mapping[str, Any]]:
    """Return the catalog entry list from any of the accepted input shapes."""
    if isinstance(payload, Mapping):
        if "runlog_catalog" in payload:
            return extract_entries(payload["runlog_catalog"])
        if "result" in payload:
            return extract_entries(payload["result"])
        raise TypeError("expected a list, an API envelope or a probe dump")
    if not isinstance(payload, list):
        raise TypeError("expected a list of catalog entries")
    return payload


def catalog(entries: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Build the ``alarmCode -> enLogName`` mapping, sorted by code."""
    codes: dict[str, str] = {}
    for entry in entries:
        code = str(entry["alarmCode"]).strip().upper()
        name = str(entry.get("enLogName") or "").strip()
        if not code or not name:
            continue
        if code in codes and codes[code] != name:
            raise ValueError(f"alarm code {code} has two names")
        codes[code] = name
    return dict(sorted(codes.items()))


def render(codes: Mapping[str, str]) -> str:
    """Render the module source (ruff-format stable: one entry per line)."""
    lines = [
        f"    {json.dumps(code, ensure_ascii=False)}: "
        f"{json.dumps(name, ensure_ascii=False)},"
        for code, name in codes.items()
    ]
    return HEADER + "\n".join(lines) + "\n" + FOOTER


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help="captured JSON file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "alarm_codes.py",
        help="module to write (default: alarm_codes.py next to the integration)",
    )
    args = parser.parse_args(argv)

    with args.input.open(encoding="utf-8") as f:
        codes = catalog(extract_entries(json.load(f)))
    args.output.write_text(render(codes), encoding="utf-8")
    print(f"wrote {len(codes)} alarm codes to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
