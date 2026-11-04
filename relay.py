"""Relay D.C. Board of Elections results for Initiative 86 into results.json.

The DCBOE API sends no CORS headers, so the page can't read it directly. This
polls the API and pushes results.json whenever the numbers change. config.json
holds the hand-set Twitter vibes and the expected turnout.

    python relay.py                 poll and push until stopped
    python relay.py --once --no-push --slug 2024-General-Election --contest "INITIATIVE 83"
"""
import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://electionresults.dcboe.org"
HERE = Path(__file__).resolve().parent
OUT = HERE / "results.json"


def get(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "goose-needle-relay"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def snapshot(slug, contest):
    config = json.loads((HERE / "config.json").read_text())
    data = {"status": "waiting", "vibes": config["vibes"], "expected_votes": config["expected_votes"]}
    try:
        info = get(f"/electionResults/getElectionInfo/{slug}")
        offices = get(f"/cityWide/getCityWide/{slug}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"{slug} not available: {e}")
        return data

    match = next((o for o in offices if re.search(contest, o["OfficeName"], re.I)), None)
    if match is None:
        print(f"{slug} is up but no contest matches {contest!r}: "
              + "; ".join(o["OfficeName"] for o in offices))
        return data

    def votes(prefix):
        return sum(c["Votes"] for c in match["ElectionData"]
                   if c["Contestant"].strip().lower().startswith(prefix))

    data.update(
        status="live",
        contest=match["OfficeName"],
        yes=votes("yes"),
        no=votes("no"),
        precincts_counted=info.get("PrecinctsCounted"),
        precincts_total=info.get("TotalPrecincts"),
        results_type=info.get("ElectionResultsTypeName"),
        dcboe_updated=info.get("LastUpdated"),
    )
    return data


def publish(data, push):
    previous = json.loads(OUT.read_text()) if OUT.exists() else None
    if data == previous:
        return False
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(datetime.now(timezone.utc).isoformat(timespec="seconds"), data)
    if push:
        subprocess.run(["git", "add", "results.json"], cwd=HERE, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "Update results",
                        "-m", "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"],
                       cwd=HERE, check=True)
        subprocess.run(["git", "push", "-q"], cwd=HERE, check=True)
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--slug", default="2026-General-Election")
    p.add_argument("--contest", default=r"INITIATIVE.*86|FORCE.?FEEDING")
    p.add_argument("--interval", type=int, default=120)
    p.add_argument("--once", action="store_true")
    p.add_argument("--no-push", action="store_true")
    a = p.parse_args()
    while True:
        try:
            publish(snapshot(a.slug, a.contest), not a.no_push)
        except subprocess.CalledProcessError as e:
            print(f"git failed: {e}")
        if a.once:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
