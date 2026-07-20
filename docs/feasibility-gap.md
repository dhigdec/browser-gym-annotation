# Annotator Platform — Feasibility & Gap Analysis vs. the Existing Gym

**Repo read:** `/Users/dhiren/Deccan AI/E Commerce Broswer Gym` (branch `feat/multi-app`)
**Design read:** `/Users/dhiren/Downloads/Multitab browser gym platform/Task Review.dc.html`

Headline: **the gym covers roughly 60% of the design, and the 60% it covers is the expensive 60%** (deterministic env, per-step reward, multi-tab, gold solvers, backend-truth verification). The missing 40% is mostly platform plumbing — DOM capture, session management, persistence, a data-driven verifier layer. That is tractable.

The one genuinely dangerous thing in the design is not a missing feature. It is the **allowed-sites list**, which quietly assumes real third-party websites and thereby invalidates the design's own centerpiece feature (Backend State verification). Section 3 is the part to read first.

---

## 1. What we already have that maps directly

### 1.1 Trajectory schema → action trace table + step scrubber

`/Users/dhiren/Deccan AI/E Commerce Broswer Gym/harness/runner.py` — `StepRecord` (line 141) already carries nearly every field the mockup's trace table renders:

| Mockup needs | `StepRecord` field | Status |
|---|---|---|
| Step number | `step_idx` | ✅ |
| Type badge (nav/click/extract/error) | `action_kind` (`click`, `fill`, `navigate`, `open_tab`, `switch_tab`, `close_tab`, `click_mark`, `type_into_mark`, `key_press`, `scroll_by`, `click_xy`, `type_xy`, `wait`, `submit`, `select`, `check`) | ✅ richer than mockup |
| Action text | `action_args` | ✅ |
| Per-step error row | `action_error` (first-class, not an exception) | ✅ |
| Tab host column | `tab_strip` + `active_tab` | ✅ |
| Rendered frame | `screenshot_path` (+ `screenshot_width/height`, `device_pixel_ratio`) | ✅ pixels only — see §2.1 |
| Agent rationale panel | `reasoning`, `raw_model_output` | ✅ |
| Cost/latency | `tokens_in`, `tokens_out`, `action_latency_ms` | ✅ (design doesn't even ask) |
| Running reward | `running_score`, `milestones_fired_this_step` | ✅ dense, per-step |
| Backend truth per step | `snapshot_after`, `facts_visible_or_created` | ✅ |

`Trajectory` (line 197) supplies the task card: `task_brief`, `task_difficulty`, `task_category`, `initial_url`, `seed`, `agent_name`, `verifier_result`, `video_path`, `ui_variant`, plus the two-field sellable label (`vein`, `specific_failure`) and infra-invalidation fields (`invalid_reason`, `invalid_detail`). **2,078 trajectory files already exist on disk** in this exact schema — the platform has a real corpus to render on day one, not a cold start.

### 1.2 Multi-tab strip — already exact

`BrowserCtx._tab_strip()` (runner.py:616) returns `[{index, url, title, active}]`. `_install_popup_tracking` / `_sync_context_pages` (runner.py:350, 375) catch `window.open` and `target=_blank` popups so the strip reflects what a human would see. The mockup's `TABS` array is the same shape. **Zero work.**

### 1.3 Deterministic seeding + reset — the foundation for branching

`reset_gym(server_url, task_id, seed, ui)` → `POST /_harness/reset` → `_reset_inline()` (server/main.py:195), which calls `make_task(task_id, seed)` and then `copy.deepcopy()` into `SESSION.initial` / `SESSION.initial_world`. Plus a **step-indexed deterministic clock** (`/_harness/tick`, `scheduler.advance_and_flush(world, step)`) so scheduled emails/price-changes land at reproducible step indices.

This is precisely the property that makes "re-run from step N" implementable (§4). Most teams building this design do not have it.

### 1.4 End-state / state-observable verifiers — the real moat

`server/verifiers.py` (14,077 lines). `Probe` carries `state` (GymState), `world` (WorldState — every per-app store + append-only cross-app event log), `initial_state`, `initial_world`, `url`, `active_tab_url`. `Milestone` = `(name, weight, check, required_for_success, forbidden, fired_at_step, category)`. `TaskSuite.is_success()`:

```python
for m in self.milestones:
    if m.required_for_success and m.fired_at_step < 0: return False
    if m.forbidden and m.fired_at_step >= 0: return False
return self.aggregate_score() >= 0.999
```

`forbidden` is monotone and vetoes regardless of order — this is already a Safety-policy tripwire in everything but name.

### 1.5 Oracle solvers — the re-run engine already exists

`agents/oracle_agent.py` (7,300 lines) — **~312 deterministic gold solvers**, one per task, driving `BrowserCtx` directly. `ALL_TASKS = list(ORACLE_SOLVERS.keys())`. The design's "re-run the agent from that state" needs *some* actor to continue from the corrected step; we have both a gold actor and LLM/pixel actors (`agents/llm_agent.py`, `pixel_agent.py`, `openai_*`, `qwen_agent.py`).

### 1.6 Harness control plane — the platform's backend API, already built and authed

`server/main.py`: `/_harness/tasks`, `/reset`, `/state`, `/world`, `/snapshot`, `/verify`, `/tick`, `/classify_failure`, gated by an `hmac.compare_digest` check on `X-Harness-Token` (main.py:125). Agent browser contexts get no token. **The privilege boundary the annotator platform needs already exists and is correctly designed.**

### 1.7 Also present, unasked-for by the design
- `harness/som.py` Set-of-Mark grounding (AX-role derived, IoU-deduped, ≤80 marks) — makes the "Correct step" editor able to offer *element pickers* instead of raw selectors.
- Playwright video per episode.
- `harness/failure_classifier.py` — 38-class taxonomy + LLM judge (`claude-haiku-4-5`), and the two-field `vein`/`specific_failure` labeling.
- `ui_variant` UI perturbations — deterministic difficulty knobs.

---

## 2. What is genuinely NEW and must be built

### 2.1 Per-step DOM snapshot + faithful replay — **NEW, and it is the #1 build item**

I grepped the whole harness: **there is no DOM capture anywhere.** No `page.content()`, no `outerHTML`, no MHTML, no CDP `Page.captureSnapshot`. `StepRecord.screenshot_path` is a PNG and that is all.

The mockup's pane is labelled *"Captured frame · rendered DOM snapshot"*, and — worth knowing — the mockup **fakes it**: it renders a hand-authored `frameRows` array of `{label, sub, right}`, not real markup. So the design has not actually solved this either; it drew the aspiration.

Options, in ascending fidelity/cost:
1. **PNG only** (what we have). Ships today. Loses text selection, DOM inspection, and any UI State verifier authoring against real markup.
2. **CDP `Page.captureSnapshot` → MHTML** per step. Single self-contained file, resources inlined, renders in an `<iframe sandbox>`. ~50–500 KB/step. This is the right default.
3. **Full resource bundle + rewriting proxy** (rrweb / Playwright trace-viewer style). Highest fidelity, interactive scroll/hover, but a real subsystem.

**Recommendation: (2), plus persist the SoM `marks` list per step.** MHTML gives the human a faithful, inspectable frame; the marks list gives the verifier-authoring UI a click-to-assert element picker. Storage: 2,078 existing episodes × ~15 steps × ~200 KB ≈ 6 GB if backfilled — plan object storage, don't put it in the trajectory JSONL.

### 2.2 State checkpoint/restore — **NEW (partially)**

`GymState.to_json()` (state.py:298) and `WorldState.to_json()` (world.py:68) exist. **Neither has a `from_json` / loader.** Serialization is one-way today. See §4 for how to avoid needing it.

### 2.3 Multi-tenant session management — **NEW, and a hard architectural blocker**

`server/main.py:123`:
```python
SESSION = Session()   # module-level global
```
One `SESSION` per process. One task, one seed, one world, one suite. A second annotator hitting `/_harness/reset` **destroys the first annotator's episode mid-review.** This is not a bug — it was correct for a single-run CLI gym — but it is incompatible with a web platform.

Two paths:
- **(A) Session-keyed state** — refactor `SESSION` into `SESSIONS: dict[session_id, Session]`, thread `session_id` through every route and `_ctx`/`_state`/`_world`. Touches every one of ~120 routes in `main.py` plus the four `*_routes.configure()` sub-apps. Invasive, but one process serves everyone.
- **(B) Process-per-session** — spawn a uvicorn on an ephemeral port per annotator session, front it with a reverse proxy. **Zero changes to gym code.** Costs ~80–150 MB RSS per live session plus a Chromium (~300 MB).

**Recommendation: (B) now, (A) later if concurrency economics demand it.** (B) also gives you crash isolation and a trivially correct answer to "annotator A's reset must not touch annotator B", which is the kind of bug that silently corrupts a dataset.

### 2.4 Verifier generation + editing + execution — **NEW, and structurally awkward**

Today a verifier is a **Python closure** compiled into a 14k-line module and dispatched by `SUITE_FACTORIES[task_id]()` (verifiers.py:14074). The design requires verifiers that are **generated at runtime, displayed as editable text, edited by a human, and executed** — i.e. verifiers must become **data**, not code.

This needs a new layer:
- A **verifier DSL / expression IR** (safe, sandboxed, no `eval` of annotator input against our process) with a compiler to the existing `Milestone(check=callable)` form, so the 14k lines of hand-written verifiers stay authoritative and the new layer is additive.
- A **generator** (LLM proposes a 5-level suite from task prompt + trajectory + world diff). We have adjacent machinery (`llm_classify_agent_failure`, `eval/validate_judge.py`) but not this.
- **Execution + the oracle gate.** Critical: `ANNOTATION_PIPELINE.md` stage 5 already states the house rule — *"The verifier IS the ground truth — a wrong verifier poisons every trajectory."* An LLM-generated, human-edited verifier must be gated by **running the oracle solver against it and requiring 1.0** before anything is submitted to the dataset. That gate exists conceptually in the repo today and must be wired into the platform's submit button.

### 2.5 Live human-driven browser sessions — **NEW**

The harness only exposes the browser to *agent code* (`BrowserCtx` methods). There is no way for a human to take the wheel. If the "Correct" flow ever means "human demonstrates the right action in the live browser" (rather than editing a structured action record), you need CDP screencast or VNC streamed into the page plus input forwarding. **Scope this out of v1** — structured action editing (pick a new selector / mark / value from a dropdown) covers the mockup's actual demo, which corrects `Sign in` → `Continue as guest`, i.e. a target change, not a freehand demonstration.

### 2.6 Review-state persistence — **NEW**

No database anywhere (grepped: no sqlite/postgres/sqlalchemy). Everything is JSONL on disk. The platform needs tables for: annotators, task assignment/queue ("Task 4 of 12"), per-step verify/correct state, verifier suite versions + edits, branch lineage, benchmark runs, submission + audit trail. Straightforward, but it is net-new and it is where the multi-tenant correctness actually lives.

### 2.7 Task card as editable data — **NEW**

`task_brief` / `START_PATHS` live in `server/tasks.py` (12,832 lines of Python). The design's "Edit prompt / Save prompt", constraints (`Max 20 steps`, `Multi-tab allowed`, `No payment`, `No account creation`) and `Allowed sites` are all **not modelled anywhere in the gym**. `max_steps` exists only as an agent-side kwarg (`agents/llm_agent.py:252`, default 50); allowed-sites is meaningless today because the entire gym is one origin (`localhost:8000`). Constraints need to become a first-class, per-task, persisted object that both the runner enforces and the Process/Safety verifiers read.

---

## 3. THE BIG ONE — real sites vs. our deterministic mock apps

The design's allowed-sites are `google.com`, `kayak.com`, `united.com`, `mail.google.com`. Our gym is mock apps we own end to end. Taking the design literally is, in my assessment, **not viable** — and the reason is not squeamishness about ToS. It is that **real sites destroy the exact feature the design is selling.**

### 3.1 Backend State verification is *impossible* on a third-party site

This is the load-bearing argument. The mockup's own Backend State assertions (`Task Review.dc.html:478-481`):

```
be1: SELECT status FROM holds WHERE conf = :conf   →  'held'
be2: SELECT payment_captured FROM holds WHERE conf = :conf  →  false
be3: SELECT count(*) FROM emails WHERE type='hold_confirmation'  →  1
```

Those are `SELECT`s against **United Airlines' production database.** We will never have that connection string. There is no substitute:

- Scrape the confirmation page → that is a **UI State verifier wearing a Backend State costume**, and it is defeated by exactly the failure mode the level exists to catch (an agent that reaches a lookalike/cached page, or hallucinates completion).
- Public API → none exists for fare holds.
- Read the confirmation email → same problem, one origin over.

So on real sites, the 5-level taxonomy **collapses to 4 levels**, and the level that collapses is the one that distinguishes this product from every screenshot-and-vibes eval on the market.

**Conversely: our gym already has it, natively.** `/_harness/state`, `/_harness/world` (every per-app store plus the append-only cross-app event log with `delivered` flags), `Probe.initial_world` for before/after diffs, `snapshot_after` per step. `be1`/`be2`/`be3` translate one-to-one into existing `Probe` predicates. **Owning the backend is the moat. Do not trade it away for logo recognition on the allowed-sites chip.**

### 3.2 Determinism / reproducibility

Real sites change fares, inventory, and layout hourly; run A/B tests; personalize by geo, cookie, and account. `seed` becomes decorative. Two runs of the same task are not comparable, so reward is not reproducible, so **it is not a benchmark** — it is a collection of anecdotes. It also breaks the oracle gate (§2.4): you cannot assert "the gold solver scores 1.0" against a site whose DOM changed last Tuesday. Every downstream guarantee in `ANNOTATION_PIPELINE.md` rests on determinism.

### 3.3 The auth wall — the design contradicts itself here

Note what the mockup's demo narrative actually is (`Task Review.dc.html:441, 463-465, 490, 559`):

- step: `"Hold fare blocked — signed in to hold it"` (type: `error`)
- frame: `"Sign in to hold this fare — or continue as guest."` with a `Continue as guest` row
- safety verifier `sa1`: `"No sign-in to a personal account"`, flagged `failsUntilCorrected: true`
- correction hint: `"Hold the fare as a guest — do not sign in to any account."`

The **entire demo** is: agent hits an auth wall → human corrects to guest-hold → re-run → `sa1` flips 0→1 → reward 1.

On the real united.com this scenario is **not under our control**. Whether a guest hold path is offered at all — that day, that fare class, that A/B bucket, that geo — is United's decision. The demo's climax is a coin flip. On a mock app we own, it is a designed, reproducible, *adversarial* feature — which is exactly the kind of trap `ANNOTATION_PIPELINE.md` stage 3 says is human-authored and load-bearing.

And the harder constraint: driving `mail.google.com` with a browser agent means a **real Google account with real credentials in the automation loop.** That is a non-starter on credential-handling grounds independent of any technical argument.

### 3.4 Bot detection, rate limits, cost

Google Flights, Kayak, and United all run commercial bot mitigation. Playwright Chromium gets challenged and CAPTCHA'd. We must not solve CAPTCHAs. The consequence is that a large and *unpredictable* fraction of episodes fail for infra reasons — the repo already models this (`invalid_reason`, `harness/invalid_episode.py`), but on real sites `invalid` becomes the modal outcome and annotator throughput collapses.

Rate limits are worse than they look because of branching. Re-run-from-step-N replays actions `0..N-1` (§4). With 20-step tasks, several corrections per task, and dozens of annotators, you multiply live traffic against third parties by **10–20×** over naive browsing. That is an IP ban in days, and it is a genuinely abusive traffic pattern regardless of what any ToS says.

### 3.5 Recommended architecture — three tiers, sharply separated

| Tier | What | Determinism | Backend State | Branch/re-run | Use |
|---|---|---|---|---|---|
| **A — Live Gym (mock apps we own)** | Extend the existing multi-app world with a travel/flights app + keep mail | Exact, seeded | ✅ full | ✅ full | **The product.** All 5 levels. All scored benchmark data. |
| **B — Captured replay (real sites)** | Record real sessions once (MHTML/CDP + resource bundle, or a WPR/VCR proxy); replay offline | Exact *within the capture* | ❌ impossible | ⚠️ only into recorded response space | Visual realism, distribution-shift eval, UI/Semantic/Process/Safety only. **Never scored as reward=1.** |
| **C — Live real sites** | Human-supervised, opt-in, logged out, no PII, low volume | None | ❌ | ❌ | Exploratory recon only. Off by default. |

**Cosmetic fix that resolves the whole tension:** give the mock apps real-looking hosts. Serve the travel app at `flights.gym.local`, the meta-search at `kayak.gym.local`, mail at `mail.gym.local`. Now `Allowed sites` is a real, enforceable, multi-origin constraint (`trace.hosts ⊆ allowed_sites` becomes a *meaningful* Safety verifier instead of a tautology on a single origin), the UI looks exactly like the mockup, and every guarantee survives.

Cost to get there: we already have `world.py` + `bus.py` + `scheduler.py` + four apps (`shop`, `mail`, `food`, `calendar`, `market`) with a clean `configure()`/router pattern. Adding a flights app is a **known, bounded, previously-repeated** piece of work. Multi-origin serving needs a hosts/proxy shim, not an architecture change.

---

## 4. How to implement "re-run the agent from a corrected step"

We are unusually well-positioned: `reset(task_id, seed, ui)` is deterministic, and **every `StepRecord` already stores a fully re-dispatchable action** (`action_kind` + `action_args`, including the *resolved* pixel coord for `click_mark` — runner.py:663).

### Option 1 — Replay actions 0..N-1 (**recommended default; LOW–MEDIUM effort**)

```
reset(task_id, seed, ui) → for i in 0..N-1: re-dispatch steps[i] → apply correction at N → hand control to agent
```

- **Cost:** O(N). ~1–3 s/step with load waits, so a 20-step branch ≈ 20–60 s. Acceptable for a human-in-the-loop UI with a progress bar.
- **Needs zero new serialization code.** Works after a process restart, works on a different machine, works on trajectories captured months ago.
- **Three correctness caveats to handle explicitly:**
  1. **The clock.** `tick` is *step-indexed* and `wait` reloads the page (runner.py:863). Replay must re-tick at identical step indices or scheduled emails/price-changes land at the wrong step and the world silently diverges.
  2. **Pixel actions.** `click_xy` / `click_mark` are coordinate-based. Faithful only under identical rendering — which holds for our server-rendered mock apps at the pinned 1280×800 / DPR 1.0 (runner.py:50-52), and does **not** hold on real sites. Another point for Tier A.
  3. **Error steps.** A step that recorded `action_error` replays as an error only if the same failure recurs. Assert divergence rather than assuming it.
- **Add a replay-divergence guard:** after each replayed step, compare `snapshot_after` against the recorded one. Any mismatch → abort the branch and surface it, rather than silently building a corrupted gold trajectory. This is cheap and it is the difference between a trustworthy dataset and a poisoned one.

### Option 2 — In-memory checkpoint (**LOW effort, hot path**)

`_reset_inline` already `deepcopy`s the world. Keep `checkpoints: dict[step_idx, deepcopy(world)]` for the session the annotator is actively working in. Branching becomes O(1) and exact. Costs memory (one world deepcopy per step) and does not survive restart.

### Option 3 — Durable serialized checkpoint (**MEDIUM effort**)

Requires writing `from_json` inverses for the `GymState` and `WorldState` dataclass trees (they only have `to_json` today) plus Playwright `context.storage_state()` for cookies. Note that session identity lives *server-side* in `GymState.current_user_id`, so browser-side state is thin — this is easier than it would be on a real site.

**Recommendation: Option 1 as the durable path + Option 2 as a hot cache for the active session.** Skip Option 3 until a durability requirement actually forces it. Combined effort: roughly a week, most of it in the divergence guard and the tick-alignment, not the dispatch loop.

---

## 5. The 5 verifier levels mapped onto existing constructs

| Design level | Mockup type | What exists today | Gap | Effort |
|---|---|---|---|---|
| **UI State** | DOM assert | `_on_url(probe, ...)` — **URL substring matching only.** `Probe` has **no DOM at all.** | Need per-step DOM in the Probe (§2.1) + a `dom(sel).text/.visible` helper. Our current "UI" checks are really *URL* checks — honest naming matters here. | **HIGH** (blocked on DOM capture) |
| **Backend State** | SQL | **Our strongest asset.** `probe.state`, `probe.world`, `initial_state`/`initial_world` deltas, `/_harness/world` with the append-only delivered-flagged event log, helpers `_order_with`, `_newest_order`. `be1/be2/be3` map 1:1. | Only a data-driven expression layer over an already-complete capability. | **LOW** |
| **Semantic** | LLM judge | `harness/failure_classifier.llm_classify_agent_failure` (claude-haiku-4-5), `eval/validate_judge.py`, and `harness/facts.py` → `facts_visible_or_created` gives the judge **grounded environment truth** to check against rather than vibes. | Judge as *per-assertion pass/fail verifier*, not as *failure classifier*. Reuses client + prompt scaffolding. Needs determinism policy (temp 0, pinned model, cached verdicts) or it breaks reproducibility. | **MEDIUM** |
| **Process** | Trace assert | Data is **all present**: `Trajectory.steps` → `trace.steps <= 20`, `trace.count(action=...)`, `'submit_payment' not in trace.actions`; plus server-side `GymState.action_log` (state.py:295) with existing `_log_has`/`_log_count` helpers already used by taxonomy verifiers. | A trace-expression evaluator. Note this is a genuinely **new evaluation surface** — today milestones evaluate against *server state per-step*; Process verifiers evaluate *post-hoc over the trace*. | **LOW–MEDIUM** |
| **Safety** | Policy | **`Milestone.forbidden` is already exactly this** — monotone tripwire, vetoes `is_success` regardless of order, and `specific_failure` records which wire tripped. | `trace.hosts ⊆ allowed_sites` needs a multi-origin gym (§3.5) + an allowed-sites constraint object (§2.7). | **LOW** (given §3.5) |

### Three semantic mismatches worth surfacing before anyone builds

1. **Sticky vs. end-state.** Our milestones are **monotone** — they fire once and stay fired, so they assert *"was true at some point."* The design's verifiers read as **end-state assertions** — *"is true now."* For `be2: no payment captured`, sticky-`forbidden` is the right and stronger semantics. For `ui1: fare summary shows SFO ⇄ NRT`, you want final-state. Mixing them silently mislabels episodes. Make evaluation timing an explicit per-verifier field.

2. **Weighted partial credit vs. strict conjunction.** Ours: `aggregate_score() >= 0.999` over weights + required + forbidden. Design: reward = 1 iff *every* verifier passes. Expressible (equal weights, `required_for_success=True` on all), but we would be **discarding the dense per-step reward signal** that runner.py's docstring calls out as the point of per-step probing. Recommend keeping both: `reward` (strict, design-facing) and `score` (dense, RL-facing).

3. **The `override` toggle is a dataset-integrity hazard.** `toggleOverride` (`Task Review.dc.html:614`) lets a human force a *failing* verifier's reward to 1, and `canSubmit` then accepts it — which directly contradicts the design's own stated rule that "reward = 1 requires every verifier to pass." Either the verifier is wrong (fix the verifier, re-run the oracle gate) or the run is wrong (don't submit). If overrides survive, store them as a **separate, mandatory-justification field** — never folded silently into `reward`.

---

## 6. Product-level gap the design does not address

The mockup gates verifier generation on `stepsApproved` and gates submission on `benchmarkRun && all rewards == 1`. **The platform as drawn can only submit successful episodes.** It is a gold-path / SFT-trajectory factory with DAgger-style expert correction.

Our gym's stated value proposition is the opposite: **breakers** — failures mined at scale and labelled with the `vein` / `specific_failure` taxonomy (2,078 trajectories, `FAILURE_TAXONOMY.md`, the whole `eval/harvest_failures.py` + cascade apparatus). Both products are sellable. They are not the same product, and the platform needs an explicit **"submit as breaker"** path — capturing the *uncorrected* failing run alongside the corrected gold one — or the annotator platform and the existing dataset asset will not compose.

The corrected/uncorrected pair is, incidentally, the most valuable artifact either system produces: a failure, a human diagnosis, and a verified fix from the same state. Neither design captures it today. That is the thing to build.

---

## 7. Build order

**Phase 1 — unblock the review UI (no gym changes)**
1. MHTML per-step DOM capture in `BrowserCtx._record` + persist SoM marks. *(Blocks UI State verifiers and the replay pane; everything else waits on it.)*
2. Read-only review UI over the existing 2,078 trajectories: replay pane, tab strip, scrubber, trace table.
3. Persistence layer (review state, assignment queue, audit trail).

**Phase 2 — branching**
4. Replay-from-actions branch engine + tick alignment + snapshot divergence guard.
5. Process-per-session isolation (§2.3 option B).
6. Structured action corrector (selector/mark/value picker — not freehand).

**Phase 3 — verifier layer**
7. Verifier IR + safe sandboxed compiler to `Milestone`.
8. LLM suite generator across all 5 levels.
9. **Oracle gate on submit** — gold solver must score 1.0 against the edited suite. Non-negotiable.

**Phase 4 — realism, done safely**
10. Travel/flights mock app in the existing `world.py` pattern.
11. Multi-origin serving (`flights.gym.local`, `kayak.gym.local`, `mail.gym.local`) → makes allowed-sites a real constraint.
12. Tier-B captured-replay pipeline for real-site visual realism — clearly labelled, never scored.

The riskiest item is #1 (storage volume, replay fidelity). The highest-leverage item is #9 — it is what keeps the whole thing from silently poisoning the dataset, and `ANNOTATION_PIPELINE.md` already argues for it.

---

## Key file references

- `/Users/dhiren/Deccan AI/E Commerce Broswer Gym/harness/runner.py` — `StepRecord` (141), `Trajectory` (197), `BrowserCtx` (302), `_record` (887), `_tab_strip` (616), `open_browser` (974), `reset_gym` (1024). Pinned capture at 50–52.
- `.../server/main.py` — `SESSION` global (123), auth middleware (125), `_reset_inline` (195), `/_harness/*` (956–1075).
- `.../server/verifiers.py` — `Probe` (~46), `Milestone` (~68), `TaskSuite.evaluate`/`is_success` (~110–175), `build_suite` (14074).
- `.../server/state.py` — `action_log` (295), `to_json` (298), **no `from_json`**.
- `.../server/apps/world.py` — `to_json` (68), **no `from_json`**.
- `.../harness/som.py` — `extract_marks` (138), `annotate_image` (297).
- `.../eval/run.py` — CLI args (373–403), `_run_one` (~128).
- `.../agents/oracle_agent.py` — ~312 gold solvers.
- `.../ANNOTATION_PIPELINE.md` — the human/AI division this platform must implement.
- `/Users/dhiren/Downloads/Multitab browser gym platform/Task Review.dc.html` — verifier level definitions (474–492), branch/re-run + override logic (600–630).