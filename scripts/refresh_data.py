"""Refresh the checked-in IPL match archive from Cricsheet's official JSON zip."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://cricsheet.org/downloads/ipl_json.zip"


def refresh(archive: Path | None) -> dict:
    if archive is None:
        with urlopen(SOURCE_URL, timeout=60) as response:
            payload = response.read()
    else:
        payload = archive.read_bytes()

    from io import BytesIO

    digest = sha256(payload).hexdigest()
    with ZipFile(BytesIO(payload)) as source:
        bad = source.testzip()
        if bad:
            raise ValueError(f"Corrupt zip entry: {bad}")
        names = source.namelist()
        json_names = sorted(name for name in names if name.endswith(".json"))
        if any(Path(name).name != name or not name.removesuffix(".json").isdigit() for name in json_names):
            raise ValueError("Unexpected match path in archive")
        if len(json_names) < 1000 or "README.txt" not in names:
            raise ValueError("Archive is missing the IPL match set or README")

        years: Counter[str] = Counter()
        versions: Counter[str] = Counter()
        dates: list[str] = []
        deliveries = 0
        validated: dict[str, bytes] = {}
        for name in json_names:
            raw = source.read(name)
            match = json.loads(raw)
            info = match["info"]
            if info["event"]["name"] != "Indian Premier League":
                raise ValueError(f"Unexpected competition in {name}")
            match_date = str(info["dates"][0])
            dates.append(match_date)
            years[match_date[:4]] += 1
            versions[match["meta"]["data_version"]] += 1
            deliveries += sum(
                len(over["deliveries"])
                for innings in match["innings"]
                for over in innings["overs"]
            )
            validated[name] = raw

        output = ROOT / "json"
        output.mkdir(exist_ok=True)
        for name, raw in validated.items():
            destination = output / name
            if not destination.exists() or destination.read_bytes() != raw:
                destination.write_bytes(raw)
        for stale in set(path.name for path in output.glob("*.json")) - set(validated):
            (output / stale).unlink()
        (ROOT / "README.txt").write_bytes(source.read("README.txt"))

    manifest = {
        "source": SOURCE_URL,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "archive_sha256": digest,
        "matches": len(json_names),
        "deliveries": deliveries,
        "first_match_date": min(dates),
        "last_match_date": max(dates),
        "matches_by_year": dict(sorted(years.items())),
        "cricsheet_data_versions": dict(sorted(versions.items())),
    }
    (ROOT / "data_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded Cricsheet zip")
    args = parser.parse_args()
    print(json.dumps(refresh(args.archive), indent=2))
