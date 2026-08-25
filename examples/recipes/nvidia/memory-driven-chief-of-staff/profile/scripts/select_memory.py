# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cron pre-step for the memory-writing pass.

The memory is what makes this recipe more than a mail sorter: ranking reserves
its top tier for work the person has *chosen*, and only `attention/` and
`goals/` can answer that. Until something writes those pages, nothing can ever
reach `high` and the assistant is left measuring how loudly the outside world
is asking — which is the thing it exists not to do.

The other three memory jobs do not fill that gap and are not meant to. Repair
checks invariants, consolidation compacts pages that grew past their ceiling,
preference-update writes the policy. All three maintain a memory; none creates
one.

So this selects the evidence and the agent writes the pages. The split matters
for the same reason it does elsewhere in this recipe: arithmetic that can be
done in Python is not left to a prompt. Who the recurring correspondents are,
how many exchanges there have been, which of them already have a page, and
which pages have gone stale are all counting problems, answered here. Which of
them is worth a page, and what it should say, is judgment, answered by the
model.

Emits `{"wakeAgent": false}` when there is nothing new to write, so a quiet day
costs no tokens.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from _db import ensure_store, write_txn

# How many exchanges before somebody is worth a page.
#
# One message is an event, not a relationship. Two is the smallest number that
# distinguishes a correspondent from a notification, and it is the threshold
# the production system this recipe is adapted from uses.
PEOPLE_THRESHOLD = 2

# How far back the evidence window reaches. The store holds more; the point of
# a page is who is around *now*.
WINDOW_DAYS = 30

# Bounds on one pass, for the same reason the intake slice is bounded: a turn
# that tries to write forty pages writes forty bad ones.
MAX_PEOPLE = 8
MAX_INTERACTIONS = 12

# Senders that are machinery rather than people. A page for a build server
# teaches the ranking job nothing and costs a turn to maintain.
AUTOMATED = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|alerts?|mailer|"
    r"automated|jenkins|gitlab|github|jira|bot)\b", re.I)


def memory_root():
    from _db import ledger_path
    return ledger_path().parent.parent / "memory"


def slug(name: str) -> str:
    """`Dana Okoro` -> `dana_okoro`, per the schema's filename rule."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower())
    return cleaned.strip("_")


def existing_people() -> set[str]:
    folder = memory_root() / "people"
    if not folder.is_dir():
        return set()
    return {p.stem for p in folder.glob("*.md")}


def stale_attention() -> list[dict[str, str]]:
    """Attention pages past their decay window, and pages that never existed.

    `current_priorities.md` is the one the ranking job gates on, so its absence
    is reported as loudly as its staleness. The repair job flags a stale page;
    it does not refresh one, because refreshing needs evidence it does not
    collect.
    """
    windows = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90}
    folder = memory_root() / "attention"
    wanted = ("current_priorities", "active_threads")
    found = []
    today = datetime.now(timezone.utc).date()

    for name in wanted:
        path = folder / (name + ".md")
        if not path.exists():
            found.append({"page": name, "state": "missing"})
            continue
        head = path.read_text(encoding="utf-8")[:400]
        updated = re.search(r"^updated:\s*(\d{4}-\d{2}-\d{2})", head, re.M)
        decay = re.search(r"^decay:\s*(\w+)", head, re.M)
        if not updated:
            found.append({"page": name, "state": "no updated field"})
            continue
        age = (today - datetime.strptime(updated.group(1), "%Y-%m-%d").date()).days
        allowed = windows.get(decay.group(1) if decay else "weekly", 7)
        if age > allowed:
            found.append({"page": name, "state": "stale",
                          "updated": updated.group(1), "days_old": age})
    return found


def evidence(conn, since: str) -> dict[str, object]:
    """Who has been in touch, how often, and about what.

    Counting is done in SQL and the message text is truncated there too. That
    is not premature optimisation: an earlier version selected whole bodies and
    sorted on them, which made SQLite spill the sort to a temporary file. In a
    sandbox that cannot create one, that surfaces as `unable to open database
    file` — an error that reads like a permission or locking fault and is
    neither. A fixture-sized store never reaches the spill, so the bug is
    invisible until the first real mailbox. Keep the payload small here.
    """
    counted = conn.execute(
        "SELECT sender, COUNT(*), MAX(event_at) FROM items"
        "  WHERE event_at >= ? AND sender IS NOT NULL"
        "  GROUP BY sender", (since,)).fetchall()

    counts: Counter[str] = Counter()
    latest: dict[str, str] = {}
    for sender, count, last in counted:
        if AUTOMATED.search(sender or ""):
            continue
        counts[sender] = count
        latest[sender] = last

    have = existing_people()
    candidates = []
    for sender, count in counts.most_common():
        if count < PEOPLE_THRESHOLD:
            continue
        candidates.append({
            "sender": sender,
            "slug": slug(sender),
            "messages": count,
            "last_interaction": (latest.get(sender) or "")[:10],
            "has_page": slug(sender) in have,
        })

    # A person with no page at all is more valuable than one whose page is
    # merely a few bullets behind, so they go first within the bound.
    candidates.sort(key=lambda c: (c["has_page"], -c["messages"]))
    chosen = candidates[:MAX_PEOPLE]
    wanted = {c["sender"] for c in chosen}

    interactions: dict[str, list[dict[str, str]]] = {}
    for sender in wanted:
        rows = conn.execute(
            "SELECT source, event_at, addressing,"
            "       substr(COALESCE(subject, body), 1, 200)"
            "  FROM items WHERE sender = ? AND event_at >= ?"
            "  ORDER BY event_at DESC LIMIT ?",
            (sender, since, MAX_INTERACTIONS)).fetchall()
        interactions[sender] = [
            {"when": (event_at or "")[:10], "source": source,
             "addressing": addressing, "text": " ".join((text or "").split())}
            for source, event_at, addressing, text in rows]

    return {"people": chosen, "interactions": interactions}


def open_obligations(conn) -> list[dict[str, object]]:
    """What the assistant currently believes is owed, for the attention pass."""
    rows = conn.execute(
        "SELECT global_rank, priority, title, source_id FROM obligations"
        " WHERE status='open' ORDER BY global_rank LIMIT 20").fetchall()
    return [{"rank": r[0], "priority": r[1], "title": r[2], "source_id": r[3]}
            for r in rows]


def main() -> int:
    ensure_store()
    since = (datetime.now(timezone.utc)
             - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with write_txn() as conn:
        found = evidence(conn, since)
        obligations = open_obligations(conn)

    report = {
        "window_days": WINDOW_DAYS,
        "since": since,
        "people_threshold": PEOPLE_THRESHOLD,
        "memory_root": str(memory_root()),
        "schema": str(memory_root().parent.parent / "schema.md"),
        "people": found["people"],
        "interactions": found["interactions"],
        "open_obligations": obligations,
        "attention": stale_attention(),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # Nothing to write is the common case on a quiet day, and it must be free.
    # A missing or stale attention page counts as work even when no person
    # qualifies, because that page is what the ranking job gates on.
    work = bool(found["people"]) or bool(report["attention"])
    if not work:
        print(json.dumps({"wakeAgent": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
