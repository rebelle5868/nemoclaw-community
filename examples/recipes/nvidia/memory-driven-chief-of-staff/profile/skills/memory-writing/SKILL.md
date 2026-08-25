---
name: memory-writing
description: Create and update the memory pages that the ranking job gates its top tier on, from evidence the selector collected.
version: 0.1.0
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [memory, intake]
---

# Writing the memory

The other three memory jobs maintain a memory. None of them creates one.
Repair checks invariants, consolidation compacts what grew too large,
preference-update writes the policy — all three assume pages already exist.
This job is where they come from.

That gap is not cosmetic. `ranking.py` reserves `high` for work the person has
chosen, and the only pages that can answer "chosen" are `attention/` and
`goals/`. With an empty memory nothing reaches the top tier, and the assistant
degrades into measuring how loudly the outside world is asking — which is
precisely what it exists not to do.

## What you are given

`select_memory.py` has already done the counting: who has been in touch inside
the window, how many times, who already has a page, and which attention pages
are missing or past their decay window. It also hands you the currently open
obligations, because those are the evidence for `active_threads.md`.

It does not decide who deserves a page. That is judgment, and it is yours.

## Read first

`$HERMES_HOME/schema.md` is authoritative for page types, required
frontmatter, section order, and growth ceilings. Read it before writing
anything. A page that violates it is a defect the repair job will rewrite, so
writing one costs two turns and gains nothing.

Then read `$HERMES_HOME/workspace/memory/index.md` and any existing page you
are about to change. Always write the **complete updated page**, never a
fragment: these are whole documents, not append-only logs.

## The frontmatter is the part that gets forgotten

Observed on the first real run: every page written was structurally
incomplete, and the repair job spent its own turn adding the same fields back.
A writer that reliably emits defects costs two turns a night and teaches the
repair log to be noise. Emit these in full.

People pages require **all** of:

```yaml
---
name: Full Name
role: Job title or function      # write "unknown" rather than omitting it
relationship: How they relate to the user, 1-2 sentences
importance: high | medium | low
last_interaction: YYYY-MM-DD
interaction_frequency: daily | weekly | monthly | rare
---
```

Attention pages require **all** of `type`, `updated`, **and `decay`** —
`decay: daily` for `current_priorities.md`, `decay: weekly` for
`active_threads.md`. The decay field is what lets the repair job tell a stale
page from a current one; omitting it makes the page permanently unverifiable.

Two ordering rules, for the same reason:

- **Write a page before you index it.** An index entry pointing at a file that
  does not exist yet makes the repair job create a stub, which then competes
  with the page you were about to write.
- **Index links are relative to the memory root** — `people/dana_okoro.md`,
  not an absolute path and not `../people/...`. Links *between* pages are
  relative to the page, which is where `../` belongs.

## People pages (`people/<slug>.md`)

Create one when the selector shows somebody at or above the threshold **and**
the exchanges look like a working relationship rather than a feed. Two
messages is the floor, not the test.

Write a page when:

- The user has exchanged messages with them in both directions, or
- They are in the user's reporting chain, or
- They are addressed by name and asked for something.

Do **not** write a page for:

- Senders the user never replies to, however frequent.
- Mailing lists, digests, and broadcast announcements.
- Anything the selector's evidence shows as one-directional notification
  traffic, even if it carries a human name.

`importance` is about working proximity, not seniority — the schema says so
and it is easy to get backwards. Somebody whose silence would block the user's
work is `high` even with a modest title.

Recent Interactions holds one bullet per exchange, newest first, each with a
date and what it was about. Do not restate the message; state what it meant
for the working relationship.

## Attention pages (`attention/`)

**`current_priorities.md` is the load-bearing page.** Write it when the
selector reports it missing or stale.

Its content is what the user has *chosen* to work on, in their own framing.
That is a strong claim, so the evidence bar is correspondingly high: something
belongs here when the user has said they are doing it, committed to it, or
repeatedly acted on it. A deadline somebody else set is not a chosen priority.
A busy thread is not a chosen priority. If the evidence does not support a
line, leave it out — an invented priority is worse than an empty page, because
the ranking job will promote work the user never picked.

When the evidence supports nothing, write the page with an empty list and an
honest note saying the assistant has not yet observed a chosen priority. That
is a true page. A guessed one is not.

`active_threads.md` takes the open obligations the selector handed you: what
is awaiting a reply or a decision, one entry each, per the schema's contract.

## What NOT to write

- **No `log.md` prose beyond one line per pass.** Append what you did, not why
  at length. The log is how the repair job explains itself later; a wall of
  text there buries the entries that matter.
- **No project pages from this job.** A project needs a bounded outcome, a
  durable owner, and a distinct identity, and one window of message traffic is
  weak evidence for all three. Let a project earn its page from the user or
  from sustained evidence, not from a busy week.
- **No `goals/` pages.** Goals come from the user. Inferring somebody's goals
  from their inbox is exactly the overreach this design avoids.
- **No page for anybody the selector did not surface.** If they were below the
  threshold, the counting already said so.

## Provenance

Every non-obvious claim carries where it came from, per the schema. "Prefers
async decisions" needs a source; "works on the storage team" does not if it is
in their signature. A page whose claims cannot be traced cannot be corrected
at its source, only argued with.

## Finishing

1. Update `index.md` in the same pass, after the pages exist — the schema
   requires it, and the repair job treats index drift as a defect.
2. Append one line to `memory/log.md`: what you created, what you updated.
3. Report the count of pages written. Nothing else.
