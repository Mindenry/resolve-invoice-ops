"""Check that relative Markdown links resolve to existing files."""

from __future__ import annotations

import re
from pathlib import Path

roots = [Path("portfolio"), Path("docs")]
files = [Path("README.md"), Path("SECURITY.md"), Path("CHANGELOG.md"), Path("RELEASE_NOTES.md")]
for root in roots:
    files.extend(root.rglob("*.md"))

pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
broken: list[str] = []
for path in files:
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    for target in pattern.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        clean = target.split("#", 1)[0].strip()
        if not clean:
            continue
        resolved = (path.parent / clean).resolve()
        if not resolved.exists():
            broken.append(f"{path}: {target}")

print(f"checked {len(files)} files; broken links: {len(broken)}")
for item in broken[:40]:
    print(" -", item)
raise SystemExit(1 if broken else 0)
