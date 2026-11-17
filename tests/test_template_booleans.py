"""Templates must render real booleans, never bare `true`/`false` text.

Home Assistant parses rendered results with Python literal parsing: `True`
and `False` become booleans, but lowercase `false` stays a non-empty, truthy
string. A `variables:` value or attribute that renders bare `false` text is
therefore truthy (issue #1196; the catnip bug Codex caught on PR #1195).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

# A line holding only a boolean word can only live inside a block scalar,
# i.e. a template; an inline `%}false` / `%} true` is the same mistake.
BARE_LINE = re.compile(r"^\s+(true|false|True|False)\s*$")
INLINE = re.compile(r"%\}\s*(true|false|True|False)\s*(\{%|$)")
QUOTED_RESULT = re.compile(r"['\"](true|false)['\"]\s+if\b|\belse\s+['\"](true|false)['\"]")


def _template_files() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files", "packages/*.yaml", "private_templates/*.tmpl", "scripts.yaml", "configuration.yaml"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return tracked


@pytest.mark.parametrize("path", _template_files())
def test_templates_render_real_booleans(path: str) -> None:
    offenders = [
        f"{path}:{number}: {line.strip()}"
        for number, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1)
        if BARE_LINE.match(line) or INLINE.search(line) or QUOTED_RESULT.search(line)
    ]
    assert not offenders, "render {{ true }}/{{ false }} or one boolean expression:\n" + "\n".join(offenders)
