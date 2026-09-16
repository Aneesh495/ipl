"""Give every published asset one content-derived URL version.

GitHub Pages caches files independently for ten minutes. A new HTML document
can otherwise combine with old JavaScript, CSS, or JSON in a returning browser.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs"
HTML = SITE / "index.html"
ASSET_REFERENCE = re.compile(
    r"(\./(?:styles\.css|app\.js|vendor/echarts\.min\.js))(?:\?v=[0-9a-f]+)?"
)
HTML_BUILD = re.compile(r'<html lang="en"(?: data-build="[0-9a-f]+")?>')


def build_version() -> str:
    files = [
        SITE / "app.js",
        SITE / "styles.css",
        SITE / "vendor" / "echarts.min.js",
        *sorted((SITE / "data").rglob("*.json")),
    ]
    digest = sha256()
    for path in files:
        digest.update(path.relative_to(SITE).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def expected_html(html: str, version: str) -> str:
    updated, count = HTML_BUILD.subn(
        f'<html lang="en" data-build="{version}">', html, count=1
    )
    if count != 1:
        raise ValueError("Expected one HTML root")
    updated, count = ASSET_REFERENCE.subn(
        lambda match: f"{match.group(1)}?v={version}", updated
    )
    if count != 3:
        raise ValueError(f"Expected three versioned frontend assets, found {count}")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if HTML is stale")
    args = parser.parse_args()
    version = build_version()
    original = HTML.read_text()
    updated = expected_html(original, version)
    if args.check:
        if updated != original:
            raise SystemExit("Site asset version is stale. Run make assets.")
    elif updated != original:
        HTML.write_text(updated)
    print(f"Site asset version: {version}")


if __name__ == "__main__":
    main()
