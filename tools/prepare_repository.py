"""Set real GitHub metadata before publishing. Does not contact GitHub."""

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="GitHub owner/repository")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("Expected owner/repository")
    owner, _ = args.repository.split("/")
    path = ROOT / "custom_components/unifi_wan_data_monitor/manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(
        documentation=f"https://github.com/{args.repository}#readme",
        issue_tracker=f"https://github.com/{args.repository}/issues",
        codeowners=[f"@{owner}"],
    )
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Repository metadata updated. No network request or publication was performed.")
