"""Held-out exam: hindcast SKYFALL and EASA on re-entries never used to learn.

Exam half only: objects with an odd NORAD id and a post-re-entry confirmation
in the bulk TIP query (the even half built the tables; 46698 is never used).
A fixed-seed random sample of them is hindcast notice by notice. Each result
is appended to a journal under data_local/validation/ (git-ignored), so the
run can be stopped and restarted without redoing finished notices. Notices
run shortest lead first: those are quick and the ones that matter, while
notices issued days ahead close half the planet and take minutes each.
Prints hits per 100 notices and the median closed area by lead time.

Usage (from backend/):
  ..\\.venv\\Scripts\\python.exe scripts\\exam_reentries.py [n_objects] [seed] [max_notices]
"""

import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict

from build_track_drift_table import confirmed_objects

from skyfall.holdout import BULK_PATH, is_exam
from skyfall.sources.spacetrack import REPO_ROOT, SpaceTrackClient, parse_utc
from skyfall.tip_errors import LEAD_LABELS, lead_bucket
from skyfall.validation import confirmation, hindcast

LABELS = {
    "skyfall_90": "SKYFALL 90",
    "skyfall_95": "SKYFALL 95",
    "skyfall_99": "SKYFALL 99",
    "easa_70km": "EASA 70",
    "easa_120km": "EASA 120",
}
# v1 journals predate the cross-track footprint fix: their areas are inflated.
JOURNAL_VERSION = "v2"


def exam_sample(client: SpaceTrackClient, n_objects: int, seed: int) -> set[int]:
    """Fixed random pick among exam objects that have a confirmation notice."""
    candidates = sorted(
        {
            int(t["NORAD_CAT_ID"])
            for t in client.query(BULK_PATH, math.inf)
            if is_exam(int(t["NORAD_CAT_ID"]))
            and t.get("LAT")
            and parse_utc(t["MSG_EPOCH"]) >= parse_utc(t["DECAY_EPOCH"])
        }
    )
    return set(random.Random(seed).sample(candidates, min(n_objects, len(candidates))))


def load_journal(path) -> dict[tuple[int, str], dict]:
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {(r["norad"], r["issued_at"]): r for r in rows}


def summary(rows: list[dict]) -> None:
    by_bucket = defaultdict(list)
    for r in rows:
        by_bucket[lead_bucket(r["lead_hours"])].append(r)
    print(f"\n{len({r['norad'] for r in rows})} objects, {len(rows)} notices")
    print(f"{'lead':<7} {'n':>5}" + "".join(f" {label:>22}" for label in LABELS.values()))
    for i, label in enumerate(LEAD_LABELS):
        mine = by_bucket.get(i, [])
        if not mine:
            continue
        cells = []
        for name in LABELS:
            hits = sum(r["zones"][name]["hit"] for r in mine)
            area = statistics.median(r["zones"][name]["area_km2"] for r in mine) / 1e6
            cells.append(f" {100 * hits / len(mine):>7.1f}/100 {area:>7.1f} M")
        print(f"{label:<7} {len(mine):>5}" + "".join(cells))
    print("(hits per 100 notices; median closed area in million km2)")


def main(n_objects: int, seed: int, max_notices: int | None = None) -> int:
    client = SpaceTrackClient.from_env()
    if client is None:
        print("Needs Space-Track credentials in .env (or cached queries).")
        return 1
    journal = REPO_ROOT / "data_local" / "validation" / f"exam_{JOURNAL_VERSION}_n{n_objects}_seed{seed}.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    done = load_journal(journal)
    print(f"Journal {journal} ({len(done)} notices already done)", flush=True)

    picked = exam_sample(client, n_objects, seed)
    objects = confirmed_objects(client, lambda norad_id: norad_id in picked)
    todo = []
    for norad_id, notices in objects.items():
        truth = confirmation(notices)
        for n in sorted(notices, key=lambda n: n.issued_at):
            if n.issued_at < truth.decay_epoch and (norad_id, n.issued_at.isoformat()) not in done:
                todo.append((norad_id, n, truth))
    todo.sort(key=lambda item: item[2].decay_epoch - item[1].issued_at)
    todo = todo[:max_notices]
    print(f"{len(objects)} objects ready, {len(todo)} notices to go", flush=True)

    started = time.perf_counter()
    with journal.open("a", encoding="utf-8") as out:
        for k, (norad_id, notice, truth) in enumerate(todo, 1):
            h = hindcast(notice, truth, include_uniform=False)
            row = {
                "norad": norad_id,
                "issued_at": notice.issued_at.isoformat(),
                "window_minutes": notice.window_minutes,
                "lead_hours": h.lead_hours,
                "z": h.z if math.isfinite(h.z) else None,
                "zones": {
                    z.name: {"hit": z.hit, "area_km2": z.area_km2, "miss_km": z.miss_km}
                    for z in h.zones
                },
            }
            out.write(json.dumps(row) + "\n")
            out.flush()
            done[(norad_id, row["issued_at"])] = row
            elapsed = time.perf_counter() - started
            marks = " ".join(
                f"{LABELS[z.name]}={'IN' if z.hit else 'out'}" for z in h.zones
            )
            print(
                f"[{k}/{len(todo)}] {norad_id} lead {h.lead_hours:6.1f} h  {marks}"
                f"  ({elapsed / k:.1f} s/notice, ~{elapsed / k * (len(todo) - k) / 60:.0f} min left)",
                flush=True,
            )

    summary([r for r in done.values() if r["norad"] in objects])
    return 0


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:]]
    sys.exit(main(*(args + [80, 7, None][len(args):])))
