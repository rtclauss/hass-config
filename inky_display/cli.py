from __future__ import annotations

import argparse
import json
from pathlib import Path

from .payload import validate_payload
from .renderer import render_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an Inky display payload to a PNG preview.")
    parser.add_argument("payload", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    payload = validate_payload(json.loads(args.payload.read_text(encoding="utf-8")))
    args.output.write_bytes(render_payload(payload))


if __name__ == "__main__":
    main()

