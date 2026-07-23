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

Probed end-to-end against six real archived multi-app runs and the live gym:

| task | actions executed | world reconstructed byte-identically |
|---|---|---|
| M40/bogus_pricematch | 3 / 3 | **3 / 3** |
| M47/phantom_duplicate | 11 / 11 | **10 / 11** |
| M70/mixed_basket_two_redirects | 10 / 14 | **13 / 14** |
| M75/stale_gift_message | 4 / 8 | **7 / 8** |
| M57/birthday_errand | 17 / 17 | 4 / 17 |
| M37/false_overcharge | 12 / 13 | 0 / 13 |
| **total** | **57 / 66** | **37 / 66** |

The replay protocol that works is: execute the action, then
`POST /_harness/verify {url, step: i}` — which is what sets the step counter
(`server/main.py`, `s.step = req.step`) — then read the world. Omitting the
verify call was why an early probe reconstructed only the first step.

Two bugs were found this way, both fixed:

- **`int` vs `float` in the world hash** (`ffbf710`). Four of the five leaves
  differing on M40 were `0` vs `0.0` — the same money, serialized differently
  through a JSON column. This was fail-**closed**: a correct restore raised
  `DivergenceError`.
- **An incomplete action vocabulary** (`58bbe04`). `submit`, `open_tab`,
  `switch_tab`, `close_tab`, `scroll` and `wait` were all missing, and `submit`
  alone is 46 of the archive's 283 recorded actions. M57 went from 4/17 actions
  to 17/17.

## Known gaps

Two residual causes, each well characterised:

1. **A single early failure cascades.** M37 scores 0/13 because its *first*
   click does not resolve; every downstream state is then legitimately wrong.
   Task-level, not systemic — fixing one locator would likely recover all 13.
2. **Scheduled-event tasks need the clock advanced.** M57 executes all 17
   actions yet diverges, which is the signature of a task whose async events
   fire on the deterministic clock. `harness/runner.py:951` ticks with
   `step = len(trajectory.steps)` at the *start* of each turn. Adding that tick
   unconditionally made M40 *worse* (3/3 → 1/3), so the rule is conditional on
   the task having a schedule and needs deriving from an instrumented live run
   rather than inferred from archived data.

**Deliberately not done:** stripping the clock from the world hash. It would make
the numbers match today and destroy the guard — *when* an async email arrives is
precisely the difference these multi-app tasks exist to catch.

**The backfill is self-validating.** Every archived step carries both
`world_after` and a `snapshot_after` summary, so a reconstruction can be checked
against what was actually recorded and *skipped* when it disagrees. The backfill
therefore cannot introduce wrong data — at worst it covers fewer tasks than
hoped, which the audit reports honestly.

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
