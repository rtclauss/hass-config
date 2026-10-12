"""Render ignored Home Assistant YAML from public templates and private values.

Templates use ``@@PRIVATE:key@@`` markers for embedded text and
``@@PRIVATE:key|json@@`` for a complete quoted YAML scalar. The value file is ignored locally;
CI uses the committed synthetic example. Rendering validates every file before
writing any output, and never prints a private value.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile


ROOT = Path(__file__).resolve().parents[1]
MARKER = re.compile(r"@@PRIVATE:([a-z][a-z0-9_]*)(?:\|(json))?@@")


class RenderError(ValueError):
    """A manifest, template, or private value is invalid."""


def _inside(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise RenderError("Manifest paths must be relative to the repository")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise RenderError("Manifest path escapes the repository")
    return path


def _load_manifest(path: Path) -> list[tuple[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RenderError("Manifest version must be 1")
    files = data.get("files")
    if not isinstance(files, list):
        raise RenderError("Manifest files must be a list")
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"template", "output"}:
            raise RenderError("Each manifest entry needs template and output")
        template, output = entry["template"], entry["output"]
        if not isinstance(template, str) or not isinstance(output, str):
            raise RenderError("Manifest paths must be strings")
        if output in seen:
            raise RenderError("Duplicate manifest output")
        seen.add(output)
        result.append((template, output))
    return result


def _load_values(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RenderError("Private values must be a JSON object")
    for key, value in data.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise RenderError("Private value keys must be lowercase identifiers")
        if not isinstance(value, str) or not value or any(c in value for c in "\x00\r\n"):
            raise RenderError(f"Private value {key} must be a nonempty single line")
    return data


def render_all(root: Path, manifest: Path, values_path: Path, *, check: bool = False) -> int:
    """Validate and render every target; return the number of files checked."""
    entries = _load_manifest(manifest)
    values = _load_values(values_path)
    prepared: list[tuple[Path, str]] = []
    for source_name, output_name in entries:
        source = _inside(root, source_name)
        output = _inside(root, output_name)
        if source == output or not source.is_file():
            raise RenderError(f"Missing or invalid template: {source_name}")
        template = source.read_text(encoding="utf-8")
        keys = {match.group(1) for match in MARKER.finditer(template)}
        missing = keys - values.keys()
        if missing:
            raise RenderError(f"Missing private values: {', '.join(sorted(missing))}")
        rendered = MARKER.sub(
            lambda match: json.dumps(values[match.group(1)])
            if match.group(2) == "json"
            else values[match.group(1)],
            template,
        )
        if "@@PRIVATE:" in rendered:
            raise RenderError(f"Unresolved private marker in {source_name}")
        prepared.append((output, rendered))

    if check:
        for output, rendered in prepared:
            if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
                raise RenderError(f"Rendered output is stale: {output.relative_to(root)}")
        return len(prepared)

    for output, rendered in prepared:
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".privacy-render-", dir=output.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return len(prepared)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs/private_config_manifest.json")
    parser.add_argument("--values", type=Path, default=ROOT / ".private-runtime-config/values.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        count = render_all(args.root, args.manifest, args.values, check=args.check)
    except (OSError, json.JSONDecodeError, RenderError) as error:
        parser.exit(2, f"Private config render failed: {error}\n")
    print(f"Validated {count} private config target(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
