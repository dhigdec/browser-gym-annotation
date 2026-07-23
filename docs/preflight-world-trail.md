# Preflight: how much of the archive is actually forkable

§8.7 of the plan is explicit that capacity and data availability are **hypotheses
to be measured, not asserted from schema**. This is the measurement, taken
2026-07-23 against the live database and the full trajectory archive.

## What was measured

```
4,683 trajectory .jsonl files scanned across trajectories/**
  315  distinct task_ids have at least one run with steps
  315  of those carry per-step action_args        (100%)
   11  of those carry a per-step world trail       (3.5%)
```

Of the 11, ten are `openai[gpt-5.5]` captures and one is `oracle`.

In the database the picture is narrower still:

```
   11  gym tasks have a canonical run persisted at all
    1  of those canonical runs has a per-step world trail + checkpoints
```

That one is the `M310/cancel_sub_false_no_transit_claim` run captured after the
checkpoint wiring landed.

## What this means

**Fork-before-step-N currently works for one task, not 315.** Everything the
version graph, the replay validator and the correction loop are built on needs a
per-step world to fork *from*. Older runs recorded a screenshot and a prose
description; they never recorded the world between actions, so there is nothing
to restore to. No amount of schema fixes that — the data was not captured.

The heuristic that picks a canonical run ("oldest trajectory carrying a raw
payload") is separately unsound — it is duplicated in three modules, it is
order-dependent on insertion time, and post-wipe re-captures are new stochastic
runs — but it is *not* the cause of the missing world trails. For M40 and M76
specifically there is no better run to bind to: **none** of their persisted runs
has a world trail, so re-binding cannot fix them. Re-capture can.

## The cheap path, and how far it was validated

Every one of the 315 tasks has `action_args`, and the gym is deterministic
(seeded, and its clock is the step counter). So an archived trajectory can be
**replayed** to reconstruct the world trail it was never recorded with — no
model calls, no cost.

Probed end-to-end against a real archived M40 run and the live gym:

| | result |
|---|---|
| archived selectors resolved on the live page | **3 / 3** |
| world reconstructed byte-identically | **step 0 only** |

The probe is what found the `int`/`float` hash bug (fixed in `ffbf710`): four of
the five differing leaves were `0` vs `0.0`, and the fifth was a nested
`action_log`. After that fix step 0 matches exactly.

## Known gap

Steps 1+ still differ, and only in clock bookkeeping — `step`, `shop.step`,
`schedule.now`. The replayer does not advance the gym's deterministic clock, so
scheduled events never fire and the counters drift.

The fix is to reproduce the harness protocol exactly: `harness/runner.py:951`
ticks with `step = len(trajectory.steps)` at the **start** of each turn, before
the action. Adding a tick moved the counters but did not yet align them, so the
protocol needs to be derived by instrumenting a live harness run rather than
inferred from three archived data points.

**Deliberately not done:** stripping the clock from the world hash. It would make
the numbers match today and destroy the guard — *when* an async email arrives is
precisely the difference these multi-app tasks exist to catch.

## Consequence for planning

Before the live-gym workflow can be exercised across the breaker set, the runs
need world trails. In order of cost:

1. **Replay-backfill** (free, needs the clock protocol above) — recovers up to
   315 tasks.
2. **Re-capture with the oracle** (free, deterministic) — but produces a
   *passing* trajectory, so it cannot stand in for a breaking run under review.
3. **Re-capture with gpt-5.5** (costs model spend, currently org-capped) — the
   only way to get a fresh *breaking* run.

Claims about before/after visibility across the 85 breakers should cite this
file's numbers rather than the schema.
