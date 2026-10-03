"""How the weekly readings fared.

Each market balance is set against what a benchmark did over the following
week: from the close of the watch's Friday to the close of the next one. A
balance that said "partagée" took no side and is not scored.

A score means little without a point of comparison, so the same weeks are also
scored for the laziest forecast there is: "up, every week".
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

HORIZON_DAYS = 7
LATE_DAYS = 4  # a benchmark closed on the last days of the week still gives a verdict
MIN_FOR_RATE = 10  # below it, a success rate would be noise

RIGHT, WRONG, UNSCORED, PENDING, UNKNOWN = "juste", "à côté", "non notée", "en attente", "inconnu"


def score(readings: Sequence[dict], closes: Sequence[tuple[str, Decimal]], today: date) -> dict:
    """Verdict of each reading, newest first, and the tally.

    `readings`: the watches that carry a reading, as ``{semaine, du, au, sens,
    confiance}``. `closes`: the benchmark's daily closes, sorted by day.
    """
    days = [day for day, _ in closes]

    def at(day: str) -> tuple[str, Decimal] | None:
        index = bisect_right(days, day) - 1
        return closes[index] if index >= 0 else None

    rows = []
    for reading in sorted(readings, key=lambda r: r["au"]):
        target = date.fromisoformat(reading["au"]) + timedelta(days=HORIZON_DAYS)
        first, last = at(reading["au"]), at(target.isoformat())
        row = {**reading, "jusqu_au": target.isoformat(), "variation": None}
        complete = (
            first is not None
            and last is not None
            and today > target
            and last[0] > first[0]
            and days[-1] >= (target - timedelta(days=LATE_DAYS)).isoformat()
        )
        if first is None and today > target:
            row["verdict"] = UNKNOWN  # the benchmark has no price that far back
        elif not complete:
            row["verdict"] = PENDING
        else:
            change = last[1] / first[1] - 1
            row["variation"] = float(change.quantize(Decimal("0.0001")))
            if reading["sens"] == "hausse":
                row["verdict"] = RIGHT if change > 0 else WRONG
            elif reading["sens"] == "baisse":
                row["verdict"] = RIGHT if change < 0 else WRONG
            else:
                row["verdict"] = UNSCORED
        rows.append(row)

    scored = [row for row in rows if row["verdict"] in (RIGHT, WRONG)]
    return {
        "rows": rows[::-1],
        "summary": {
            "scored": len(scored),
            "right": sum(1 for row in scored if row["verdict"] == RIGHT),
            "always_up_right": sum(1 for row in scored if row["variation"] > 0),
            "unscored": sum(1 for row in rows if row["verdict"] == UNSCORED),
            "pending": sum(1 for row in rows if row["verdict"] == PENDING),
            "enough": len(scored) >= MIN_FOR_RATE,
            "minimum": MIN_FOR_RATE,
        },
    }
