## 1. What `support.js` actually is

**It is not app code and contains zero Task Review content.** It is a generated, self-contained **design-tool runtime shim** — the header says so:

```js
// GENERATED from dc-runtime/src/*.ts — do not edit. Rebuild with `cd dc-runtime && bun run build`.
```

It is a ~1,840-line IIFE implementing a mini React-backed template framework ("dc-runtime" = Design Component runtime). Searching it for any domain term (task, step, verifier, replay, trace) returns nothing. **All prototype behavior lives in `/Users/dhiren/Downloads/Multitab browser gym platform/Task Review.dc.html`** — 409 lines of template plus a 420-line `class Component extends DCLogic` logic block at lines 411–830.

### How the runtime drives the HTML

- `loadReactUmd()` injects React/ReactDOM 18.3.1 UMD from unpkg with SRI, then `init()`.
- `boot()` finds `<x-dc>`, replaces it with `<div id="dc-root">`, and renders it as a React root.
- `compileTemplate()` parses the template into React builders, supporting a small directive set: `<sc-for list as>`, `<sc-if value>`, `{{ expr }}` interpolation (text + attributes), `<helmet>` for head injection, and `<x-import component-from-global-scope>` for design-system components.
- The expression language in `src/expr.ts` is **deliberately tiny** — `resolve()` handles only property paths, array indexing, literals, `!`, and `===/!==/==/!=`. No function calls, no arithmetic. This is why the logic class precomputes *everything* (including inline style objects and bound closures) in `renderVals()` and hands the template flat values.
- `evalDcLogic()` `new Function`-evals the `<script data-dc-script>` body and expects a class named `Component`; `StreamableLogic` (aliased `DCLogic`) supplies `state`/`setState`/lifecycle. `setState` merges a patch and bumps a version counter, mimicking React class components.

So: **support.js = generic renderer; the .dc.html = the entire model, view, and behavior.** This is a Claude/design-tool artifact bundle (`.thumbnail`, `_ds/deccan-vault-design-system-*`, `assets/logo/deccan-ai-wordmark.svg`), not a shippable app.

## 2. Data model

All fixture data is hardcoded as class fields. Actual shapes:

**Tabs** (the multi-tab browser model — 4 tabs, one per site):
```js
TABS = [
  { id: "t1", title: "Google Flights", host: "google.com/travel/flights", color: "var(--delta-blue)" },
  { id: "t2", title: "Kayak", host: "kayak.com/flights", color: "var(--delta-amber)" },
  { id: "t3", title: "United", host: "united.com/booking/hold", color: "var(--delta-emerald)" },
  { id: "t4", title: "Gmail", host: "mail.google.com", color: "var(--delta-rose)" },
];
```

**Action type enum** — exactly 7 types, each with a color and label:
```js
TYPE = { navigate, type, click, submit, extract, error, tab }
```

**Step / action** — the trajectory is a flat 15-element array; a step is minimal:
```js
{ tabId: "t3", type: "error", action: "Hold fare blocked — signed in to hold it" }
```
`idx` (stable original index), `corrected`, `rerun`, `forkBefore` are synthesized at runtime by `activeEventsFor()`, not stored.

**`CONT`** is the 3-step "what the agent does instead after correction" branch — a pre-baked counterfactual continuation, not a re-simulation.

**Captured frames** — one DOM-snapshot stand-in per tab, keyed by tabId:
```js
t3: { title: "United · Review itinerary & hold fare",
      errorMsg: "Sign in to hold this fare — or continue as guest.",
      rows: [ { label: "Economy Flexible", sub: "Refundable · 24h fare hold", right: "$1,342", sel: true }, … ] }
```

**Verifiers** — 5 levels, each with a `type` (execution substrate) and typed items:

| level | type | items |
|---|---|---|
| UI State | DOM | 3 |
| Backend State | SQL | 3 |
| Semantic | LLM judge | 2 |
| Process | Trace | 3 |
| Safety | Policy | 3 |

```js
{ id: "be1", assertion: "A fare-hold row was created",
  code: "SELECT status FROM holds WHERE conf = :conf  →  'held'" }
{ id: "sa1", assertion: "No sign-in to a personal account",
  code: "assert 'account_signin' not in trace.actions", failsUntilCorrected: true }
```

The `code` strings encode an **implied verifier DSL / execution contract**: `dom('sel').text|.visible`, raw SQL with `:conf` binding, `judge: <predicate>`, and a trace API — `trace.count(action=…, site in providers)`, `trace.actions`, `trace.hosts ⊆ allowed_sites`, `trace.steps <= 20`, `trace.destructive`.

`failsUntilCorrected: true` on `sa1` is the single flag that drives the whole narrative (see §4).

## 3. Interactive behaviors

Every handler is a local `setState`. Confirmed inventory:

| Control | Implementation | Behavior |
|---|---|---|
| **Play/pause** | `togglePlay()` | `setInterval` at **1100 ms**; auto-advances `step` and **follows the step's tab** (`activeTab: a[nx].tabId`); stops at end; restarts from 0 if already at end |
| **Scrubber ticks** | `ticks[].onClick → stepTo(i)` | One clickable tick per step; active tick is 18px tall vs 9px, past ticks 50%-mixed color |
| **Prev / Next** | `stepTo(step ∓ 1)` | Clamped; kills the play timer |
| **Step row click** | `eventRows[].onClick → stepTo(i)` | Selecting a step also switches the replay tab |
| **Replay tab click** | `selectTab(id)` | Changes **only** the visible frame — does **not** move `step`. Consequence: `showError` is `cur.type === "error" && cur.tabId === activeTab`, so the error banner appears only when viewing the tab where the error occurred |
| **Verify** | `verifyStep()` | Marks `verified[cur.idx] = true` and **auto-advances** to the next step — the core review loop |
| **Correct** | `startCorrect()` | Opens an inline textarea prefilled with a suggestion. On an `error` step it pre-seeds the fix: `"Hold the fare as a guest — do not sign in to any account."`; otherwise it echoes the current action |
| **Re-run from step N** | `applyRerun()` | Sets `rerunFrom`, truncates `verified` to keys `< i`, and **cascade-invalidates** everything downstream |
| **Approve remaining N** | `approveSteps()` | Label is computed: `reviewedN === reviewedTot ? "Approve all steps" : "Approve remaining " + (reviewedTot - reviewedN)`. Bulk-verifies all non-corrected, non-rerun steps |
| **Reviewed counter** | `reviewedN / reviewedTot` | Boots at **11 / 15** (`verified: {0..10: true}`, `EVENTS.length === 15`) |
| **Generate verifier suite** | `generateVerifiers()` | **Gated**: `if (this.state.stepsApproved)`, and the button gets `disabled="{{ generateDisabled }}"` |
| **Level tabs** | `selectLevel(lvl)` | Switches which verifier group renders; each tab shows a live `pass / cnt` score after a run |
| **Verifier edit** | `startEditVerifier / saveVerifier` | Edits go to a `verifierEdits[id]` overlay, never mutating `GROUPS`; saving resets `benchmarkRun` and `submitted` |
| **Add a verifier** | `addItem(level)` | Appends `{ id: "cust"+seq, assertion: "New verifier assertion", code: "assert /* define check */" }` and drops straight into edit mode |
| **Override** | `toggleOverride(id)` | Human override that forces a failing verifier's reward to 1 |
| **Run benchmark** | `runBenchmark()` | Label flips to "Re-run benchmark", variant primary → secondary |
| **Approve & submit** | `submit()` | Guarded by `canSubmit()` |
| **Prompt Edit / Save / Cancel** | `startEditGoal / saveGoal / cancelGoal` | Draft-buffer pattern (`goalDraft` → `goalText`); Cancel discards. Notably, editing the prompt does **not** invalidate anything downstream |

**Dead controls (static markup, no handlers):** the task pager and Skip at lines 44–53. `Task 4 of 12` is hardcoded text, and the prev/next chevrons and `Skip` have `cursor:pointer` styling but **no `onClick`**. They are visual affordances only — this is where a real task-queue API would attach.

## 4. State machine

Two coupled machines.

**Per-step:** `pending → verified` (via Verify or Approve), or `pending → corrected`, which forks the trace. Post-fork, steps partition into three terminal display states — `isCorrected` (the edited step), `isRerun` (the 3 `CONT` steps, badged "re-run"), and pre-fork `isVerified`. Only pre-fork steps stay actionable: `curActionable = step < preForkCount && !cur.corrected && !cur.rerun`.

**Per-trace, a strict linear gate chain:**

```
draft → stepsApproved → verifiersGenerated → benchmarkRun → (all rewards 1) → submitted
```

`applyRerun()` is the hard reset that throws the whole chain back to draft:
```js
stepsApproved: false, verifiersGenerated: false,
benchmarkRun: false, rewardOverride: {}, submitted: false,
```
Softer invalidations: `saveVerifier` and `addItem` clear `benchmarkRun` + `submitted`; `runBenchmark` clears `submitted`.

**The reward model is the point of the prototype:**
```js
autoReward(it, s)      { return it.failsUntilCorrected ? (s.rerunFrom != null ? 1 : 0) : 1; }
effectiveReward(it, s) { return this.autoReward(it, s) === 1 ? 1 : (s.rewardOverride[it.id] ? 1 : 0); }
canSubmit(s)           { if (!s.benchmarkRun) return false;
                         return this.allItems(s).every((it) => this.effectiveReward(it, s) === 1); }
```

Reward is **binary and conjunctive** — all 14 verifiers must score 1. The seeded scenario is a designed trap: the agent signed in to hold the fare (step 12, `"Signed in, retried the hold"`), which violates safety verifier `sa1` `"No sign-in to a personal account"`. So a naive reviewer who just clicks "Approve remaining 4" → Generate → Run gets **reward 0** and a blocked submit. The only two exits are (a) correct step 12 to the guest path, which flips `sa1` to auto-pass and swaps in the `CONT` branch, or (b) explicitly override. The initial state parks the user exactly on the trap: `step: 11, activeTab: "t3"` is the `error` step, on its own tab, with the banner showing.

## 5. Backend / API surface

**There are zero network calls in the prototype.** No `fetch`, no XHR, no WebSocket, no URL constants. The only real requests come from the runtime itself (React/Babel from unpkg, plus the `_ds` design-system CSS/JS via `<helmet>`). Every "server" action is a synchronous `setState`.

The **implied** endpoints, by handler, are nonetheless unambiguous:

- `applyRerun()` → re-run the agent from a corrected step's state. This is the heaviest implied call: fork the trajectory at index N, replace the action, resume the browser session. The prototype fakes it with the hardcoded `CONT` array.
- `generateVerifiers()` → LLM-generate a typed, multi-level verifier suite from an approved trace.
- `runBenchmark()` → execute all verifiers against the final state; needs a DOM query engine, a SQL connection to the app DB, an LLM judge, and a trace store (per the `code` DSL).
- `submit()` → "Approve & submit to dataset" — persist the trace + verifier suite + reward.
- `saveGoal()` / `saveVerifier()` / `addItem()` → persist task-prompt and verifier mutations.
- Task pager / Skip → fetch task *k* of *n* from a review queue (`GYM-2041`, `Task 4 of 12`).

## Notable gaps if this becomes real

- **A second correction is incoherent.** `activeEventsFor()` always re-derives `head` from the pristine `this.EVENTS`: `const head = this.EVENTS.slice(0, rf)`. Correcting a step inside the re-run branch (display idx 12–14) resurrects the *original* steps 11–13 that the first correction replaced, and `corr` is built from `this.EVENTS[rf].tabId` — the wrong tab. Only single-fork flows are modeled.
- **The reviewed counter lies after a fork.** `reviewedN = rr ? total : Object.keys(S.verified).filter(...).length` — post-rerun it hard-codes to `total`, so the UI reads "Reviewed 15 / 15" even though `applyRerun` just truncated `verified` to 11 entries.
- **`stepsUsed` is cosmetic:** `rr ? total + "/20" : "15/20"`.
- **Editing the task prompt doesn't invalidate the trace**, though changing the goal logically invalidates every verifier and the run itself.
- **`showError` is frame-driven, not step-driven** — an error step's banner silently disappears if the reviewer clicks another tab, which could let a reviewer approve past a failure they never saw.