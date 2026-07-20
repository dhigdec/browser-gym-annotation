# Deccan AI — Browser-Use Gym Annotator Platform — Build Plan

## Context

Deccan AI (data company) will annotate the browser-use gym tasks internally. In the Tencent-prioritisation call, JP/Nav asked to turn model runs into human-reviewed, verifier-gated golden trajectories. The team shared a design — **"Task Review / Tasking"** — a two-stage annotator screen. We are building that platform for real: professional, pixel-accurate to the design, in a new repo we keep working in.

The shared files (`Task Review.dc.html` + `support.js`) are a **design-tool prototype export** (a template-DSL runtime + hardcoded fixtures, zero backend) — a pixel-and-behavior **spec**, not a starter codebase. We rebuild fresh, consuming the **Deccan Vault Design System** (`_ds/…`), which is the one thing the team mandated we use (tokens + compiled React component library + an oxlint adherence config + Inter Display / JetBrains Mono fonts).

**Adaptation:** the mockup demos a flight task (Google Flights / Kayak / United / Gmail). We keep the exact UI/UX and swap the content to **our gym apps** — ShopGym · ShopMail · ShopGym Calendar · ShopGym Eats (food) · ValueMart — and gym tasks (the M-series). Allowed sites become our app hosts; the seeded "error + correction" narrative maps to a gym breaker (e.g. an expired-card checkout or forbidden action the reviewer corrects).

## Decisions locked (from user)
- **Environment:** our own mock apps (ShopGym / ShopMail / Calendar / food / ValueMart). Not real travel sites. **Use a database.**
- **Repo:** new standalone platform repo.
- **v1 milestone:** pixel-perfect Task Review screen on fixtures (no live backend yet).
- **Stack:** React (Vite SPA + TypeScript) consuming the Deccan DS · Python FastAPI backend · Postgres.

## Why this is feasible (~60% already exists in the gym)
`ecommerce-browser-gym` (branch `feat/multi-app`) already provides: the `StepRecord`/`Trajectory` schema with `tab_strip`/`active_tab`/`action_kind`/`reasoning`/`snapshot_after`, **2,078 real trajectories on disk**, deterministic `reset(task_id, seed)`, end-state verifiers (`Milestone`/`TaskSuite`, weighted/required/forbidden), ~312 oracle gold-solvers, and the token-gated `/_harness` control plane. The platform wraps these; the DS skins them.

---

## Architecture (3 layers)

1. **Frontend** — Vite + React + TS SPA. Consumes the Deccan Vault DS (tokens via `styles.css`; the 21 primitives extracted from `_ds_bundle.js`). Rebuilds the Task Review screen exactly.
2. **Platform API (Python / FastAPI)** — Python so it can *directly import and run* the gym, the 14k-line verifier module, and the oracle solvers. Owns: session orchestration, per-step DOM capture + replay, branch-from-step-N re-run, verifiers-as-data (generate/edit/execute), the oracle-gate on submit, and the "submit as breaker" path.
3. **Data**
   - **Platform Postgres** — operational data (tasks, queue/assignment, review verdicts, forks, verifier suites + versions, benchmark runs, submissions, annotator identity, audit).
   - **Gym Backend-State SQL surface** — to make the design's SQL "Backend State" verifier level literal: at verify-time, materialize the gym's in-memory `world.to_json()` into an **ephemeral SQLite** (tables: `orders`, `subscriptions`, `emails`, `events`, `cart_items`, …). Backend-State verifiers run real `SELECT`s against it. Keeps the fast deterministic in-memory gym unchanged. *(Recommended over giving the gym a persistent per-session DB, which is a large rewrite that risks determinism.)*

### Environment tier
Single tier: **our mock apps served at real-looking hosts** (e.g. `shop.gym.local`, `mail.gym.local`, `calendar.gym.local`, `eats.gym.local`, `valuemart.gym.local`). This (a) preserves the design's realistic look, (b) makes all 5 verifier levels work, (c) turns the Safety check `trace.hosts ⊆ allowed_sites` from a tautology into a real assertion.

---

## Repo structure (new standalone repo)

Proposed name: **`browser-gym-annotator`** (adjustable).

```
browser-gym-annotator/
├─ frontend/                 # Vite + React + TS SPA
│  ├─ src/
│  │  ├─ ds/                 # thin wrappers around extracted Deccan DS primitives
│  │  ├─ features/task-review/   # the screen: header, ReplayPane, Scrubber,
│  │  │                          # ActionTrace, RightPanel, VerifierSuite, BenchmarkDock
│  │  ├─ fixtures/           # M1 mock data (adapted gym task)
│  │  └─ lib/                # types, state machine, tokens helper
│  ├─ .oxlintrc.json         # DS adherence lint (ignore vendored bundle)
│  └─ index.html
├─ backend/                  # FastAPI platform API (M2+)
│  ├─ app/{api,sessions,verifiers,capture,db,oracle}/
│  └─ pyproject.toml
├─ packages/ds/              # vendored + cleaned Deccan Vault DS
├─ infra/                    # docker-compose (frontend, backend, postgres, gym pool)
├─ docs/                     # this plan, design spec, data model, ADRs
└─ README.md
```

The gym is consumed as a dependency (git submodule or pinned path) — not copied.

---

## Milestone 1 — pixel-perfect Task Review screen on fixtures (the immediate deliverable)

Rebuild the design **exactly** with the DS + mock data. No live backend. This captures every detail and is demo-able.

**Design-system setup**
- Vendor `_ds/` into `packages/ds/`; **extract the 21 primitives** from `_ds_bundle.js` (delimited by `// components/<group>/<Name>.jsx`). **Do not load the whole bundle** — it has three unconditional top-level `ReactDOM.createRoot(#root/#td-root)` mounts that hijack the host app. Ensure `window.React` (18+) exists first.
- Fonts: keep **Inter Display** (OFL — add `OFL.txt`); **self-host JetBrains Mono** (drop the Google `@import` — fails under CSP); **delete the Season Mix token** (TRIAL license forbids serving; no component uses it).
- Tokens via `styles.css` single entry. Add `.oxlintrc.json` (the DS adherence rules) with an ignore pattern for the vendored bundle. Write CSS-in-JS numbers as `width: 120` not `"120px"`, colors as `var(--token)` not hex — to pass the lint.
- Fidelity traps to honor: `--weight-semibold: 600` resolves to Bold 700 (only 400/500/700/900 ship); spacing grid is 4px; `--tracking-heading -1.12px` only at 24px; `--neutrals-85 #f5f5f5` is the page bg; `--primary-6 #1279f7` (interactive) ≠ `--accent-blue #0d74ce` (info).

**Screen build (component → DS mapping)** — reference the extracted spec in `docs/design-spec.md`:
- **Header** (56px sticky): wordmark · breadcrumb `Browser-Use Gym › Tasking` · task pager `Task 4 of 12` · `Skip` · **FocusBadge** `Multitab · Web Navigation` · `QA` avatar chip.
- **Stage 1 — Review & correct:** ReplayPane (tab strip with our 5 apps + colored dots, URL bar, "Captured frame · rendered DOM snapshot" viewport, per-step overlay card with **Verify**/**Correct**) · timeline Scrubber (transport, `12 / 15`, action-type-colored segments) · **ActionTrace** table (index, status circle, action-type chip [navigate/type/click/submit/extract/error/tab], description, app column, `Reviewed N/M`, `Approve remaining N`).
- **Right panel (360px):** task card — id badge, priority, title, meta, **TASK PROMPT + Edit**, START STATE, CONSTRAINTS chips, ALLOWED SITES chips (our app hosts), RUN SUMMARY 2×2 metric tiles.
- **Stage 2 — Build verifier suite:** locked empty state → unlocked 5-level tab bar (**UI State/DOM · Backend State/SQL · Semantic/LLM · Process/Trace · Safety/Policy**) with group cards, editable verifier rows (assertion + mono code + **Meter** score slot + edit), "Add a verifier", and the **Benchmark dock** (reward numeral, three sub-copy states, Run/Re-run, Approve & submit).
- Reproduce all states via fixture toggles: locked ↔ unlocked, pre-run ↔ reward 0 (Safety fails) ↔ reward 1, the correct-and-rerun fork, and the override path.

**Fixtures** — adapt a real multi-tab gym task (recommend **M207** cross-app or **M20** errand so the tab strip spans several apps), with one seeded forbidden/error step so the "correct → re-run → safety verifier flips" narrative is faithful to the design. Fixture shape mirrors the eventual API contract (task, run/steps, verifierSuite) so M2 is a data-source swap, not a rewrite.

**Two scoring rules baked in from day one** (prototype bugs we must not ship): an empty/unparseable/non-executing verifier scores **0/error, never 1** (the mockup's `assert /* define check */` wrongly scored 1); and "override to submit" is role-gated, requires a reason, stamps `submitted_with_override`, and is excluded from the scored set by default.

**M1 acceptance:** visually matches the three design screenshots at 1440px; DS-adherence oxlint passes; Inter Display + JetBrains Mono render; every state reachable via fixtures.

---

## Milestones 2+ (roadmap — built after M1, each its own PR series)

- **M2 — Real data read-only:** load a trajectory `.jsonl` → render the trace, tabs, scrubber, right panel from real gym data (2,078 available). Backend read endpoints.
- **M3 — DOM capture + real replay:** add per-step **CDP `Page.captureSnapshot` (MHTML) + persisted SoM marks** to the gym harness (the #1 net-new gym item; blocks the replay pane and all UI-State verifiers). Replay pane renders captured frames.
- **M4 — Sessions + branch re-run:** process-per-session orchestrator behind a reverse proxy (fixes the `SESSION` module-global that lets two annotators clobber each other). Branch-from-step-N via deterministic reset + replay actions 0..N-1 (with a `snapshot_after` divergence guard).
- **M5 — Verifiers as data:** generate → edit → execute. A sandboxed IR compiling to the existing `Milestone(check=callable)`; the 5-level mapping (Backend-State/Safety = LOW effort, Process = LOW-MED, Semantic = MED, UI-State = HIGH/needs M3); materialized SQLite for Backend-State SQL.
- **M6 — Integrity gates:** oracle-gate wired into submit (oracle must score 1.0 against the human/LLM verifier suite); "submit as breaker" path; capture the **corrected+uncorrected pair from the same seed** (highest-value artifact — preference pairs).
- **M7 — Platform ops:** Postgres schema live; task queue + assignment; annotator auth/SSO; multi-user; metrics (human unaided pass rate).

---

## Platform DB schema (Postgres) — initial tables
`task` · `task_assignment` · `review_session` · `step_verdict` · `trace_fork` · `verifier_suite` · `verifier` · `benchmark_run` · `submission` · `annotator` · `audit_log`. Keyed by `session_id`; verifier suites versioned; overrides and breaker-submissions first-class.

---

## Infra
- **Dev:** `docker-compose` — frontend, backend, Postgres, and a small pool of gym server processes.
- **Sessions:** process-per-session gym pool behind a reverse proxy (no OS VM needed, unlike CUA — matches JP's "pre-warmed tab group via API").
- **Artifacts:** MHTML snapshots + PNGs + video per step (~1–5 MB/episode) — local FS in dev, S3/GCS + CDN in prod.
- **Secrets/keys:** env-only; never committed.

---

## Git discipline
- Conventional Commits; small, logical, self-contained commits; feature branches → PRs; `.gitignore` for `node_modules`, `.venv`, build output, artifacts, secrets.
- **Remote:** I'll create the **local** repo and scaffold; the Deccan/GitHub org remote is created by you (I can't create org repos or auth as Deccan). Push once you give me the target.

---

## Verification
- **M1:** `vite dev` → compare against the three design screenshots at 1440px width; run oxlint (DS adherence passes, zero new warnings outside the ignored bundle); confirm fonts and all fixture-toggled states; check the two scoring rules (empty verifier scores 0; override is gated/stamped).
- **M2+:** load a known trajectory and confirm the trace matches the `.jsonl`; branch re-run reproduces deterministically; oracle scores 1.0 against a generated suite; two concurrent sessions stay isolated; Backend-State SQL returns correct rows from materialized SQLite.

---

## Open items to confirm at/after approval
1. Repo name (`browser-gym-annotator` proposed) + the Git remote/org to push to.
2. "Database" scope confirmation: **Platform Postgres** (definite) + **materialized-SQLite** for SQL Backend-State verifiers (recommended) — vs a heavier persistent gym DB.
3. Which gym task to feature in the M1 fixtures (recommend a multi-tab one — M207 or M20).
4. Annotator auth/SSO provider (M7) — align to Deccan's standard.
