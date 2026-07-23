import { useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import { Button, Icon, t, weight } from "../../ds";
import {
  adjudicate,
  autogenVerifiers,
  downloadSampleBundle,
  driveForwardGym,
  fetchGymStatus,
  fetchQaSubmissions,
  fetchQaTasks,
  fetchGymTasks,
  fetchReview,
  fetchTasks,
  getPersistedGymReview,
  openSession,
  patchSession,
  rerunGymBranch,
  rerunTrajectory,
  resumeGymReview,
  runGymReview,
  runVerifiers,
  saveSuite,
  submitSession,
} from "../../lib/api";
import { parseStateEdits } from "../../lib/gymEdits";
import type { AutogenResult, QaSubmission, QaTaskRow } from "../../lib/api";
import type { ReviewData, Step, TaskListItem, Verifier } from "../../lib/types";
import {
  canSubmit,
  isResolved,
  isVerified,
  makeInitialState,
  offlineResults,
  reducer,
  reward,
  runSummary,
  sessionStatus,
  verifierPayloads,
  visibleSteps,
} from "../../lib/reviewMachine";
import { useAuth } from "../auth/AuthContext";
import { ProfilePanel } from "../auth/ProfilePanel";
import type { Annotator } from "../auth/authApi";
import { Header } from "./components/Header";
import { ReplayPane } from "./components/ReplayPane";
import { ActionTrace } from "./components/ActionTrace";
import { RightPanel } from "./components/RightPanel";
import { VerifierSuite } from "./components/VerifierSuite";

const TASK_ID = "GYM-2041";

/** Close a modal on Escape + move focus into it on open (a11y). */
function useModalA11y(onClose: () => void, ref: { current: HTMLDivElement | null }) {
  useEffect(() => {
    ref.current?.focus();
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose, ref]);
}
const DIALOG = { role: "dialog", "aria-modal": true, tabIndex: -1 } as const;

function SectionHeader({ n, title, subtitle, done, right }: { n: number; title: string; subtitle: string; done?: boolean; right?: ReactNode }) {
  const active = n === 1 || done;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "2px 4px 12px" }}>
      <span style={{ width: 22, height: 22, borderRadius: t.radiusFull, background: n === 1 ? t.primary6 : done ? t.green : t.n4, color: t.n9, display: "inline-flex", alignItems: "center", justifyContent: "center", fontFamily: t.fontMono, fontSize: "0.75rem", fontWeight: weight.bold }}>{n}</span>
      <span style={{ fontSize: "0.875rem", fontWeight: weight.bold, color: active ? t.n0 : t.n2 }}>{title}</span>
      <span style={{ fontSize: "0.78rem", color: t.n3 }}>{subtitle}</span>
      {right && <span style={{ marginLeft: "auto" }}>{right}</span>}
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft", steps_approved: "Steps approved", verifiers_generated: "Suite saved",
  benchmark_run: "Benchmarked", submitted: "Submitted",
};

function SaveBadge({ sessionId, status }: { sessionId: string | null; status: string }) {
  const saved = !!sessionId;
  const color = saved ? t.green : t.n3;
  return (
    <span title={saved ? "Your work autosaves to the platform database" : "Backend offline — changes are not being saved"}
      style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: "0.72rem", fontWeight: weight.semibold, color: t.n2 }}>
      <span style={{ width: 7, height: 7, borderRadius: t.radiusFull, background: color, boxShadow: saved ? `0 0 0 3px ${t.greenLite}` : "none" }} />
      {saved ? `Autosaved · ${STATUS_LABEL[status] ?? status}` : "Not saved (offline)"}
    </span>
  );
}

function Frame({ children }: { children: ReactNode }) {
  return (
    <div style={{ width: 1440, margin: "0 auto", minHeight: "100vh", display: "flex", flexDirection: "column", background: t.n85, border: `1px solid ${t.n7}` }}>
      {children}
    </div>
  );
}

interface TaskNav {
  index: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
  onSkip: () => void;
  onBrowseGym: () => void;
  gymTaskId?: string | null;
  onExitGym?: () => void;
  onOpenQa: () => void;
  annotator: Annotator | null;
  onOpenProfile: () => void;
  queueSet?: "breakers" | "fixtures";
  onToggleQueue?: () => void;
  gymAdhoc?: boolean;
  // Editing the prompt re-drives the WHOLE run from the initial state under the
  // new instruction (gym tasks only), then a fresh review of that run.
  onPromptRerun?: (prompt: string) => Promise<void>;
}

function ReviewScreen({ data, nav, startFresh, onStartNew }: { data: ReviewData; nav: TaskNav; startFresh: boolean; onStartNew: () => void }) {
  const [state, dispatch] = useReducer(reducer, data, makeInitialState);
  const [correcting, setCorrecting] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [promptOverride, setPromptOverride] = useState<string | null>(null);
  const [driving, setDriving] = useState<null | "queued" | "running">(null);
  const [driveError, setDriveError] = useState<string | null>(null);
  const [autogen, setAutogen] = useState<null | "queued" | "running">(null);
  const [autogenResult, setAutogenResult] = useState<AutogenResult | null>(null);
  const [editingState, setEditingState] = useState(false);
  // The LIVE resume context. Each drive-forward returns the world it ended in, and
  // we adopt it — so successive corrections COMPOUND (round N+1 continues from where
  // round N got to) instead of re-anchoring to the original run's end-state. That's
  // what lets an annotator iteratively steer the agent to the target.
  const [liveResume, setLiveResume] = useState(data.gymResume);

  useEffect(() => {
    if (!state.playing) return;
    const id = setInterval(() => dispatch({ t: "tick" }), 1100);
    return () => clearInterval(id);
  }, [state.playing]);

  // ---- M4 persistence: open/resume the session, then mirror each committed
  // transition to the backend so the annotator's work survives a refresh.
  const statusRef = useRef<string>("draft");
  const suiteSigRef = useRef<string>("");
  const submittedRef = useRef(false);
  const rerunRef = useRef<number | null>(null);
  const reviewedRef = useRef<number>(-1);

  useEffect(() => {
    let alive = true;
    openSession(data.task.id, { fresh: startFresh }).then((snap) => {
      if (!alive || !snap) return;
      setSessionId(snap.sessionId);
      const results = (snap.lastBenchmark?.results as Record<string, string>) ?? {};
      // Reconstruct the annotator's AUTHORED suite from the persisted latest
      // version: verifiers the human added, plus edits to generated ones. Without
      // this the suite silently reverts to the generated set on reload (and the
      // next Run would overwrite the DB with the reverted suite).
      const origById = new Map(data.verifiers.map((v) => [v.id, v]));
      const added: Verifier[] = [];
      const edits: Record<string, { assertion: string; code: string }> = {};
      for (const pv of snap.suite?.verifiers ?? []) {
        const orig = origById.get(pv.id);
        if (!orig || pv.addedByHuman) {
          added.push({ id: pv.id, level: pv.level as Verifier["level"], assertion: pv.assertion, code: pv.code, check: pv.check ?? undefined, placeholder: pv.placeholder, failsUntilCorrected: pv.failsUntilCorrected });
        } else if (pv.assertion !== orig.assertion || pv.code !== orig.code) {
          edits[pv.id] = { assertion: pv.assertion, code: pv.code };
        }
      }
      // Human attestations (overrides) from the last run — so reward can't drop
      // 1->0 when the next run silently omits them.
      const overrides: Record<string, boolean> = {};
      for (const id of snap.lastBenchmark?.overridden ?? []) overrides[id] = true;
      // The persisted correction branch — restores the fork's exact steps/count.
      const branchTail = snap.branch ? snap.branch.steps : null;
      const rerunMode = snap.branch ? snap.branch.mode : null;
      const hydrateAction = {
        t: "hydrate" as const,
        status: snap.status,
        rerunFrom: snap.rerunFrom,
        reviewedThrough: snap.reviewedThrough,
        results,
        branchTail,
        rerunMode,
        added,
        edits,
        overrides,
        submission: snap.submission ? { reward: snap.submission.reward, kind: snap.submission.kind } : null,
      };
      const restored = reducer(makeInitialState(data), hydrateAction);
      // Seed the sync refs to the RESTORED state so we don't echo it back.
      statusRef.current = snap.status;
      rerunRef.current = snap.rerunFrom;
      reviewedRef.current = restored.verifiedThrough;
      submittedRef.current = snap.status === "submitted";
      suiteSigRef.current = restored.verifiersGenerated
        ? JSON.stringify(verifierPayloads(restored))
        : "";
      if (snap.status !== "draft" || snap.rerunFrom != null || snap.reviewedThrough > 0 || snap.suite != null || snap.branch != null) {
        dispatch(hydrateAction);
      }
    });
    return () => {
      alive = false;
    };
  }, [data.task.id]);

  // Run the verifier suite through the backend execution engine (M5). Falls
  // back to a flag-derived result only when the backend is unreachable.
  const runBenchmark = async () => {
    // Gym tasks carry the real milestone verdict already (verifierState/reward read
    // v.gymResult / data.gymReward). Still persist a benchmark run server-side —
    // scored from the authoritative gym-engine verdict — so the session reaches
    // benchmark_run and the sample becomes SUBMITTABLE (submit requires a run).
    if (data.source === "gym") {
      const overrides = Object.keys(state.overrides);
      const corrected = state.rerunFrom != null;
      if (sessionId) {
        await saveSuite(sessionId, verifierPayloads(state)); // persist the milestones as the human suite
        const out = await runVerifiers(sessionId, { corrected, verifiers: verifierPayloads(state), overrides });
        dispatch({ t: "benchmarkComplete", results: out?.results ?? {} });
        return;
      }
      dispatch({ t: "benchmarkComplete", results: {} }); // offline — reveal only
      return;
    }
    const verifiers = verifierPayloads(state);
    const overrides = Object.keys(state.overrides);
    const corrected = state.rerunFrom != null;
    if (sessionId) {
      // Persist the current suite first — the server scores the PERSISTED suite,
      // not this request's list, so the stored reward is authoritative.
      await saveSuite(sessionId, verifiers);
      const out = await runVerifiers(sessionId, { corrected, verifiers, overrides });
      if (out) {
        dispatch({ t: "benchmarkComplete", results: out.results });
        return;
      }
    }
    dispatch({ t: "benchmarkComplete", results: offlineResults(state) });
  };

  // Gate-status transitions (draft → steps_approved → verifiers_generated).
  const status = sessionStatus(state);
  useEffect(() => {
    if (!sessionId || status === statusRef.current) return;
    statusRef.current = status;
    if (status === "steps_approved" || status === "verifiers_generated") {
      void patchSession(sessionId, { status });
    }
  }, [sessionId, status]);

  // Correction fork — persist the re-run point AND the re-lock together. A
  // correction re-locks Section 2 to 'draft'; writing both atomically means a
  // failed /rerun can't leave the DB status contradicting the persisted fork
  // (which would reload with Section 2 wrongly unlocked / submittable).
  useEffect(() => {
    if (!sessionId || state.rerunFrom === rerunRef.current) return;
    rerunRef.current = state.rerunFrom;
    if (state.rerunFrom != null) {
      statusRef.current = "draft"; // keep the status effect from firing a duplicate PATCH
      void patchSession(sessionId, { rerunFrom: state.rerunFrom, status: "draft" });
    }
  }, [sessionId, state.rerunFrom]);

  // Granular review progress — persist every verify/approve so it survives a
  // refresh (each click reflected in the DB).
  useEffect(() => {
    if (!sessionId || state.verifiedThrough === reviewedRef.current) return;
    reviewedRef.current = state.verifiedThrough;
    void patchSession(sessionId, { reviewedThrough: state.verifiedThrough });
  }, [sessionId, state.verifiedThrough]);

  // Verifier suite — save a new immutable version whenever it changes.
  const suiteSig = state.verifiersGenerated ? JSON.stringify(verifierPayloads(state)) : "";
  useEffect(() => {
    if (!sessionId || !suiteSig || suiteSig === suiteSigRef.current) return;
    suiteSigRef.current = suiteSig;
    void saveSuite(sessionId, verifierPayloads(state));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, suiteSig]);

  // Submission — await the server, reconcile from its snapshot, surface failures.
  // Never optimistically show "submitted"; the server is authoritative.
  const handleSubmit = async () => {
    if (!canSubmit(state) || submittedRef.current) return;
    if (!sessionId) { dispatch({ t: "submitFailed", error: "Not saved — the backend is offline." }); return; }
    submittedRef.current = true;
    const snap = await submitSession(sessionId, {
      reward: reward(state) ?? 0,
      override: Object.keys(state.overrides).length > 0,
      kind: reward(state) === 1 ? "golden" : "breaker",
    });
    if (snap?.submission) {
      dispatch({ t: "submitConfirmed", reward: snap.submission.reward, kind: snap.submission.kind });
    } else {
      submittedRef.current = false; // allow retry
      dispatch({ t: "submitFailed", error: "Submit failed — nothing was saved. Check the connection and retry." });
    }
  };

  const steps = visibleSteps(state);
  const current = steps[state.step];
  const remaining = steps.length - state.verifiedThrough;

  const onAddVerifier = (assertion: string, code: string) => {
    const placeholder = !code.trim() || code.includes("/* define check */");
    const v: Verifier = { id: `add-${state.added.length + 1}`, level: state.activeLevel, assertion, code, placeholder };
    dispatch({ t: "addVerifier", verifier: v });
  };

  return (
    <Frame>
      <Header {...nav} />
      {driving && <GymLoading taskId={data.task.id} phase={driving} />}
      {driveError && (
        <div onClick={() => setDriveError(null)} title="Dismiss" style={{ position: "fixed", left: "50%", bottom: 24, transform: "translateX(-50%)", background: t.redLite, color: t.redDark, border: `1px solid color-mix(in srgb, ${t.red} 42%, ${t.n9})`, padding: "10px 16px", borderRadius: t.radiusLg, fontSize: "0.84rem", fontWeight: weight.semibold, zIndex: 70, cursor: "pointer", maxWidth: 540, boxShadow: t.shadowLg }}>
          {driveError}
        </div>
      )}
      <div style={{ padding: "16px 16px 8px" }}>
        <SectionHeader n={1} title="Review & correct the agent run" subtitle="Verify each step; correct any step to re-run the agent from that state." right={
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <SaveBadge sessionId={sessionId} status={status} />
            {data.source === "gym" && data.gymResume && (
              <span onClick={() => setEditingState(true)} title="Edit the world state and re-verify against the gym"
                style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "5px 11px", borderRadius: t.radiusLg, border: `1px solid ${t.n6}`, background: t.n9, color: t.primary6, fontSize: "0.75rem", fontWeight: weight.semibold, cursor: "pointer", whiteSpace: "nowrap" }}>
                ✎ Edit state
              </span>
            )}
            {data.source === "gym" && data.gymResume && (
              <span
                onClick={driving ? undefined : async () => {
                  // Continue the task from where it stopped: drive the live agent
                  // forward from the final state and fork on the new steps.
                  setDriveError(null);
                  const fromStep = steps.length;
                  setDriving("queued");
                  const res = await driveForwardGym(
                    { taskId: data.task.id, seed: data.gymResume!.seed, worldState: data.gymResume!.worldState, resumeUrl: data.gymResume!.finalUrl || "/", resumeStep: fromStep, agent: "openai", sessionId: sessionId ?? undefined },
                    { onStatus: (s) => setDriving(s === "done" || s === "error" ? null : s) },
                  );
                  setDriving(null);
                  if (res && res.steps.length) {
                    const branch = res.steps.map((s, i) => ({ ...s, idx: fromStep + i + 1 }));
                    if (sessionId) await rerunGymBranch(sessionId, { fromStep, steps: branch, mode: "agent" });
                    dispatch({ t: "correctAndRerun", fromStep, branch, mode: "agent", gymReward: res.reward });
                  } else {
                    setDriveError("The live agent couldn't continue — the gym may be unreachable or the model unavailable.");
                  }
                }}
                title="Load the corrected state and let a live agent (gpt-5.1) continue the task in the gym (slow)"
                style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "5px 11px", borderRadius: t.radiusLg, border: `1px solid ${t.n6}`, background: t.n9, color: driving ? t.n3 : t.primary6, fontSize: "0.75rem", fontWeight: weight.semibold, cursor: driving ? "default" : "pointer", whiteSpace: "nowrap" }}>
                {driving ? (driving === "queued" ? "Queued…" : "Agent driving…") : "⚡ Drive forward (live agent)"}
              </span>
            )}
            {(state.submitted || status === "submitted") && (
              <span onClick={onStartNew} title="This session is submitted and locked — start a fresh annotation of this task"
                style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "5px 11px", borderRadius: t.radiusLg, border: `1px solid ${t.n6}`, background: t.n9, color: t.primary6, fontSize: "0.75rem", fontWeight: weight.semibold, cursor: "pointer", whiteSpace: "nowrap" }}>
                <Icon name="plus" size={13} stroke={2.2} /> New annotation
              </span>
            )}
          </div>
        } />
        {/* Section 1 fills exactly the first screen: viewport minus the header
            (56) + this block's padding (16+8) + the section header (~36) + a small
            buffer. Getting this wrong makes the page scroll, sliding the replay's
            tab-strip/URL bar up under the sticky header (clipping). minHeight kept
            modest so short viewports degrade gracefully instead of forcing overflow. */}
        <div style={{ display: "flex", gap: 16, height: "calc(100dvh - 134px)", minHeight: 440 }}>
          <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 12 }}>
            <ReplayPane
              tabs={data.tabs}
              activeTabId={state.activeTabId}
              onSelectTab={(id) => dispatch({ t: "selectTab", id })}
              step={current}
              stepNumber={current.idx}
              stepIndex={state.step}
              steps={steps}
              playing={state.playing}
              resolved={isResolved(state, current)}
              verified={isVerified(state, current)}
              correcting={correcting}
              correctionSeed={current.type === "error" ? data.correctionSeed : current.description}
              onVerify={() => dispatch({ t: "verifyStep" })}
              onStartCorrect={() => setCorrecting(true)}
              onCancelCorrect={() => setCorrecting(false)}
              onSaveCorrect={async (text) => {
                setCorrecting(false);
                setDriveError(null);
                const fromStep = current.idx;
                // Gym tasks DRIVE A LIVE AGENT FORWARD from the corrected mid-episode
                // state (gpt-5.1) and fork the trajectory with the real continuation
                // — the genuine "re-run from this step" loop. The new steps are
                // persisted on the session so the fork survives a reload, and the
                // annotator re-does the pipeline (re-approve → verifiers → run).
                if (data.source === "gym" && data.gymResume) {
                  const edits = parseStateEdits(text); // `path = value` lines → real state edits
                  // Continue from the LATEST world (previous correction's end-state),
                  // and resume at THIS step's own page — so correcting a step inside a
                  // re-run branch resumes there, not at the original run's final URL.
                  const rz = liveResume ?? data.gymResume;
                  const resumeUrl = current.url || rz.urlTrail[fromStep - 1] || rz.finalUrl || "/";
                  setDriving("queued");
                  // The free-text correction is the annotator's INSTRUCTION to the
                  // agent (e.g. "verify the price before emailing"). It's injected
                  // into the agent's context at the resume point so the re-run is
                  // actually steered — separate from any `path = value` state edits.
                  const res = await driveForwardGym(
                    {
                      taskId: data.task.id,
                      seed: rz.seed,
                      worldState: rz.worldState,
                      edits: Object.keys(edits).length ? edits : undefined,
                      correction: text.trim() || undefined, // reviewer guidance for the agent
                      resumeUrl,
                      resumeStep: fromStep,
                      agent: "openai", // gpt-5.1 — genuinely continues from the corrected state
                      sessionId: sessionId ?? undefined, // isolate the corrected verdict to THIS annotator
                    },
                    { onStatus: (s) => setDriving(s === "done" || s === "error" ? null : s) },
                  );
                  setDriving(null);
                  if (res && res.steps.length) {
                    // Adopt the world this re-run ended in, so the NEXT correction
                    // continues from here — iterations compound toward the target.
                    if (res.gymResume) setLiveResume(res.gymResume);
                    // Fork at the correction point: re-index the continuation to fromStep+1…
                    const branch = res.steps.map((s, i) => ({ ...s, idx: fromStep + i + 1 }));
                    if (sessionId) await rerunGymBranch(sessionId, { fromStep, steps: branch, mode: "agent", correction: text.trim() });
                    dispatch({ t: "correctAndRerun", fromStep, branch, mode: "agent", gymReward: res.reward });
                  } else {
                    setDriveError("The live agent couldn't continue from that state — the gym may be unreachable or the model unavailable. Try again.");
                  }
                  return;
                }
                let branch: Step[] | null = null;
                let mode: string | null = null;
                if (sessionId) {
                  const out = await rerunTrajectory(sessionId, { fromStep, correction: text, mode: "agent" });
                  if (out) { branch = out.steps; mode = out.mode; }
                }
                dispatch({ t: "correctAndRerun", fromStep, branch, mode });
              }}
              onPlayToggle={() => dispatch({ t: "playToggle" })}
              onStepTo={(i) => dispatch({ t: "stepTo", i })}
            />
          </main>
          <RightPanel
            task={promptOverride ? { ...data.task, prompt: promptOverride } : data.task}
            summary={runSummary(state)}
            // Gym: saving a new prompt re-drives the WHOLE run under it (then a
            // fresh review). Fixtures: just override the displayed prompt.
            onSavePrompt={data.source === "gym" && nav.onPromptRerun ? (text) => { void nav.onPromptRerun!(text); } : setPromptOverride}
            rerunsOnSave={data.source === "gym" && !!nav.onPromptRerun}
          />
        </div>
        {/* The action trace sits full-width UNDER the browser pane so the replay
            frame can own the full height of the row (a real tab-sized viewport). */}
        <div style={{ padding: "12px 16px 0" }}>
          <ActionTrace
            steps={steps}
            current={state.step}
            verifiedThrough={state.verifiedThrough}
            stepsApproved={state.stepsApproved}
            remaining={remaining}
            rerunFrom={state.rerunFrom}
            rerunMode={state.rerunMode}
            tabs={data.tabs}
            onStepTo={(i) => dispatch({ t: "stepTo", i })}
            onApproveRemaining={() => dispatch({ t: "approveRemaining" })}
          />
        </div>
      </div>

      <div style={{ padding: "8px 16px 24px" }}>
        <SectionHeader n={2} title="Build the verifier suite" subtitle="Generate multi-level verifiers, edit them, then run the benchmark. Reward = 1 requires every verifier to pass." done={state.submitted} right={
          data.source === "gym" ? (
            <span
              onClick={autogen ? undefined : async () => {
                setAutogenResult(null);
                setAutogen("queued");
                const res = await autogenVerifiers(data.task.id, 0, { onStatus: (s) => setAutogen(s === "done" || s === "error" ? null : s) });
                setAutogen(null);
                setAutogenResult(res);
              }}
              title="Autonomous reward agent: generate a verifier suite and validate it with the oracle gate (0 on initial, 1 on golden)"
              style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "6px 12px", borderRadius: t.radiusLg, border: `1px solid ${t.n6}`, background: t.n9, color: autogen ? t.n3 : t.primary6, fontSize: "0.75rem", fontWeight: weight.semibold, cursor: autogen ? "default" : "pointer", whiteSpace: "nowrap" }}>
              {autogen ? (autogen === "queued" ? "Reward agent queued…" : "Generating + validating…") : "🤖 Auto-generate verifiers"}
            </span>
          ) : undefined
        } />
        <VerifierSuite
          state={state}
          onGenerate={() => dispatch({ t: "generate" })}
          onSetLevel={(l) => dispatch({ t: "setLevel", level: l })}
          onAddVerifier={onAddVerifier}
          onEditVerifier={(id, assertion, code) => dispatch({ t: "editVerifier", id, assertion, code })}
          onOverride={(id) => dispatch({ t: "override", id })}
          onRun={runBenchmark}
          onSubmit={handleSubmit}
        />
      </div>

      {autogenResult && <AutogenPanel result={autogenResult} onClose={() => setAutogenResult(null)} />}
      {editingState && data.source === "gym" && data.gymResume && (
        <StateEditor
          world={(liveResume ?? data.gymResume).worldState ?? {}}
          onClose={() => setEditingState(false)}
          onApply={async (edits) => {
            const res = await resumeGymReview({
              taskId: data.task.id,
              seed: data.gymResume!.seed,
              worldState: data.gymResume!.worldState,
              urlTrail: data.gymResume!.urlTrail,
              finalUrl: data.gymResume!.finalUrl,
              edits,
            });
            if (res) dispatch({ t: "gymResumed", reward: res.reward });
            setEditingState(false);
          }}
        />
      )}
    </Frame>
  );
}

function StateEditor({ world, onClose, onApply }: { world: Record<string, unknown>; onClose: () => void; onApply: (edits: Record<string, unknown>) => Promise<void> }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useModalA11y(onClose, dialogRef);
  const shop = ((world?.shop ?? {}) as Record<string, unknown>);
  const cart = ((shop.cart ?? {}) as Record<string, unknown>);
  const nOrders = Object.keys((shop.orders ?? {}) as object).length;
  const nCart = ((cart.items ?? []) as unknown[]).length;
  const nReturns = Object.keys((shop.returns ?? {}) as object).length;
  const nSubs = Object.keys((shop.subscriptions ?? {}) as object).length;
  const [user, setUser] = useState<string>((shop.current_user_id as string) ?? "");
  const [promo, setPromo] = useState<string>((cart.applied_promo as string) ?? "");
  const [voidOrders, setVoidOrders] = useState(false);
  const [emptyCart, setEmptyCart] = useState(false);
  const [voidReturns, setVoidReturns] = useState(false);
  const [voidSubs, setVoidSubs] = useState(false);
  const [busy, setBusy] = useState(false);

  const build = (): Record<string, unknown> => {
    const e: Record<string, unknown> = {};
    if (((shop.current_user_id as string) ?? "") !== user) e["shop.current_user_id"] = user || null;
    if (((cart.applied_promo as string) ?? "") !== promo) e["shop.cart.applied_promo"] = promo || null;
    if (voidOrders) e["shop.orders"] = {};
    if (emptyCart) e["shop.cart.items"] = [];
    if (voidReturns) e["shop.returns"] = {};
    if (voidSubs) e["shop.subscriptions"] = {};
    return e;
  };
  const edits = build();
  const field = { display: "block", marginTop: 5, width: "100%", boxSizing: "border-box" as const, padding: "8px 11px", borderRadius: t.radiusLg, border: `1px solid ${t.n6}`, background: t.n85, color: t.n0, fontFamily: t.fontMono, fontSize: "0.8rem", outline: "none" };
  const label = { fontSize: "0.72rem", fontWeight: weight.semibold, color: t.n2, textTransform: "uppercase" as const, letterSpacing: "0.05em" };
  const toggle = (on: boolean, set: (v: boolean) => void, text: string, count: number) => (
    <label style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 0", cursor: "pointer", fontSize: "0.83rem", color: t.n1 }}>
      <input type="checkbox" checked={on} onChange={(e) => set(e.target.checked)} style={{ width: 15, height: 15, accentColor: t.primary6 }} />
      {text} <span style={{ color: t.n3, fontFamily: t.fontMono, fontSize: "0.74rem" }}>(now {count})</span>
    </label>
  );
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(13,13,13,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 56 }}>
      <div ref={dialogRef} {...DIALOG} aria-label="Edit the corrected state" onClick={(e) => e.stopPropagation()} style={{ width: 520, background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, display: "flex", flexDirection: "column", overflow: "hidden", outline: "none" }}>
        <div style={{ padding: "18px 22px 14px", borderBottom: `1px solid ${t.n7}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: "1rem", fontWeight: weight.bold, color: t.n0 }}>✎ Edit the corrected state</div>
            <div style={{ marginTop: 3, fontSize: "0.8rem", color: t.n2 }}>Change the world, then re-verify against the live gym for a real verdict.</div>
          </div>
          <span onClick={onClose} style={{ cursor: "pointer", color: t.n3, display: "inline-flex" }}><Icon name="close" size={18} /></span>
        </div>
        <div style={{ padding: "16px 22px", display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <span style={label}>Logged-in user</span>
            <input value={user} onChange={(e) => setUser(e.target.value)} placeholder="(none)" style={field} />
          </div>
          <div>
            <span style={label}>Applied promo</span>
            <input value={promo} onChange={(e) => setPromo(e.target.value)} placeholder="(none)" style={field} />
          </div>
          <div style={{ borderTop: `1px solid ${t.n8}`, paddingTop: 4 }}>
            {toggle(voidOrders, setVoidOrders, "Void all orders", nOrders)}
            {toggle(emptyCart, setEmptyCart, "Empty the cart", nCart)}
            {toggle(voidReturns, setVoidReturns, "Void all returns", nReturns)}
            {toggle(voidSubs, setVoidSubs, "Cancel all subscriptions", nSubs)}
          </div>
        </div>
        <div style={{ padding: "14px 22px", borderTop: `1px solid ${t.n7}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: "0.74rem", color: t.n3, fontFamily: t.fontMono }}>{Object.keys(edits).length} edit{Object.keys(edits).length === 1 ? "" : "s"}</span>
          <Button variant="primary" disabled={busy || Object.keys(edits).length === 0} onClick={async () => { setBusy(true); await onApply(edits); }} style={{ minHeight: 40 }}>
            {busy ? "Re-verifying…" : "Re-verify against gym"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function AutogenPanel({ result, onClose }: { result: AutogenResult; onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useModalA11y(onClose, dialogRef);
  const ok = result.oracle;
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(13,13,13,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 55 }}>
      <div ref={dialogRef} {...DIALOG} aria-label="Generated verifier suite" onClick={(e) => e.stopPropagation()} style={{ width: 660, maxHeight: "80vh", background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, display: "flex", flexDirection: "column", overflow: "hidden", outline: "none" }}>
        <div style={{ padding: "18px 20px 14px", borderBottom: `1px solid ${t.n7}` }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: "1rem", fontWeight: weight.bold, color: t.n0 }}>🤖 Reward agent — generated verifier suite</span>
            <span onClick={onClose} style={{ cursor: "pointer", color: t.n3, display: "inline-flex" }}><Icon name="close" size={18} /></span>
          </div>
          <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ padding: "3px 9px", borderRadius: 6, fontSize: "0.72rem", fontWeight: weight.bold, background: ok ? t.greenLite : t.redLite, color: ok ? t.greenDark : t.redDark }}>
              {ok ? "✓ Oracle-valid (0 on initial · 1 on golden)" : "Not oracle-valid"}
            </span>
            <span style={{ fontSize: "0.75rem", color: t.n2 }}>
              {result.stateChecks} state · {result.policyChecks} policy · {result.iterations} iteration{result.iterations === 1 ? "" : "s"}
              {result.gate ? ` · gate ${result.gate.initialReward}/${result.gate.goldenReward}` : ""}
            </span>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
          {result.suite.map((v) => {
            const isPolicy = (v.check as { kind?: string }).kind === "trace_policy";
            return (
              <div key={v.id} style={{ padding: "9px 20px", borderBottom: `1px solid ${t.n8}`, display: "flex", gap: 10, alignItems: "flex-start" }}>
                <span style={{ marginTop: 1, padding: "2px 7px", borderRadius: 5, fontSize: "0.64rem", fontWeight: weight.bold, textTransform: "uppercase", background: isPolicy ? "color-mix(in srgb, #a855f7 15%, transparent)" : t.surfaceTint, color: isPolicy ? "#7c3aed" : t.n2, whiteSpace: "nowrap" }}>{isPolicy ? "policy" : v.level}</span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: "0.83rem", color: t.n1 }}>{v.assertion}</div>
                  <div style={{ marginTop: 2, fontFamily: t.fontMono, fontSize: "0.7rem", color: t.n3, wordBreak: "break-word" }}>{JSON.stringify(v.check)}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function QaPanel({ onClose, reviewer }: { onClose: () => void; reviewer: string }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useModalA11y(onClose, dialogRef);
  const [tasks, setTasks] = useState<QaTaskRow[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [subs, setSubs] = useState<QaSubmission[] | null>(null);
  const [busy, setBusy] = useState(false);
  const reload = () => fetchQaTasks().then(setTasks);
  useEffect(() => { void reload(); }, []);
  const openTask = async (id: string) => { setSelected(id); setSubs(null); const r = await fetchQaSubmissions(id); setSubs(r?.submissions ?? []); };
  const accept = async (sessionId: string) => {
    if (!selected) return;
    setBusy(true);
    await adjudicate(selected, sessionId, reviewer);
    await openTask(selected);
    await reload();
    setBusy(false);
  };
  const badge = (row: QaTaskRow) => {
    if (row.adjudicated) return { txt: "adjudicated", bg: t.greenLite, fg: t.greenDark };
    if (row.disputed) return { txt: `disputed · ${Math.round((row.agreement ?? 0) * 100)}%`, bg: t.redLite, fg: t.redDark };
    return { txt: "unanimous", bg: t.surfaceTint, fg: t.n2 };
  };
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(13,13,13,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 55 }}>
      <div ref={dialogRef} {...DIALOG} aria-label="Multi-annotator QA" onClick={(e) => e.stopPropagation()} style={{ width: 840, height: "78vh", background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, display: "flex", flexDirection: "column", overflow: "hidden", outline: "none" }}>
        <div style={{ padding: "18px 22px 14px", borderBottom: `1px solid ${t.n7}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: "1rem", fontWeight: weight.bold, color: t.n0 }}>⚖ Multi-annotator QA</div>
            <div style={{ marginTop: 3, fontSize: "0.8rem", color: t.n2 }}>Agreement across annotators; accept one submission as the golden. Reviewing as <span style={{ fontFamily: t.fontMono, fontSize: "0.74rem" }}>{reviewer}</span>.</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <a href="/api/export/dataset.jsonl?accepted=true" download style={{ fontSize: "0.74rem", fontWeight: weight.semibold, color: t.primary6, textDecoration: "none", whiteSpace: "nowrap" }} title="Download the accepted golden samples as JSONL (the deliverable dataset)">⬇ Export golden dataset</a>
            <span onClick={onClose} style={{ cursor: "pointer", color: t.n3, display: "inline-flex" }}><Icon name="close" size={18} /></span>
          </div>
        </div>
        <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
          <div style={{ width: 320, borderRight: `1px solid ${t.n7}`, overflowY: "auto" }}>
            {tasks == null ? (
              <div style={{ padding: 24, color: t.n3, fontSize: "0.85rem" }}>Loading…</div>
            ) : tasks.length === 0 ? (
              <div style={{ padding: 24, color: t.n3, fontSize: "0.85rem" }}>No submissions yet. Submit a task as a couple of annotators (change the identity in the header) to see agreement here.</div>
            ) : tasks.map((row) => {
              const b = badge(row);
              return (
                <div key={row.taskExternalId} onClick={() => openTask(row.taskExternalId)} style={{ padding: "11px 18px", cursor: "pointer", borderBottom: `1px solid ${t.n8}`, background: selected === row.taskExternalId ? t.surfaceTint : "transparent" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <span style={{ fontFamily: t.fontMono, fontSize: "0.76rem", color: t.n1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.taskExternalId}</span>
                    <span style={{ fontSize: "0.64rem", fontWeight: weight.bold, padding: "2px 7px", borderRadius: 5, background: b.bg, color: b.fg, whiteSpace: "nowrap" }}>{b.txt}</span>
                  </div>
                  <div style={{ marginTop: 3, fontSize: "0.72rem", color: t.n3 }}>{row.submissions} submissions · {row.annotators} annotators · majority reward {row.majorityReward}</div>
                </div>
              );
            })}
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
            {selected == null ? (
              <div style={{ padding: 28, color: t.n3, fontSize: "0.85rem", textAlign: "center" }}>Select a task to see each annotator's submission.</div>
            ) : subs == null ? (
              <div style={{ padding: 24, color: t.n3, fontSize: "0.85rem" }}>Loading submissions…</div>
            ) : subs.map((s) => (
              <div key={s.sessionId} style={{ padding: "12px 22px", borderBottom: `1px solid ${t.n8}`, display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ width: 30, height: 30, borderRadius: t.radiusFull, background: t.primary7, color: t.n9, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "0.78rem", fontWeight: weight.bold, flexShrink: 0 }}>{s.annotator.charAt(0).toUpperCase()}</span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: "0.82rem", color: t.n1, fontFamily: t.fontMono }}>{s.annotator}</div>
                  <div style={{ fontSize: "0.72rem", color: t.n3, marginTop: 1 }}>{s.kind}{s.override ? " · overridden" : ""} · {new Date(s.at).toLocaleString()}</div>
                </div>
                <span style={{ fontFamily: t.fontMono, fontSize: "0.78rem", fontWeight: weight.bold, padding: "3px 10px", borderRadius: 6, background: s.reward === 1 ? t.greenLite : t.redLite, color: s.reward === 1 ? t.greenDark : t.redDark }}>reward {s.reward}</span>
                {s.accepted ? (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: "0.72rem", fontWeight: weight.bold, color: t.greenDark }}><Icon name="check" size={14} stroke={2.4} color={t.greenDark} /> accepted</span>
                ) : (
                  <span onClick={busy ? undefined : () => accept(s.sessionId)} style={{ fontSize: "0.72rem", fontWeight: weight.semibold, color: busy ? t.n4 : t.primary6, cursor: busy ? "default" : "pointer", padding: "5px 11px", border: `1px solid ${t.n6}`, borderRadius: t.radiusLg, whiteSpace: "nowrap" }}>Accept as golden</span>
                )}
                <span onClick={() => downloadSampleBundle(s.sessionId)} title="Download this sample's golden bundle (JSON)" style={{ fontSize: "0.72rem", fontWeight: weight.semibold, color: t.n2, cursor: "pointer", whiteSpace: "nowrap" }}>⬇ bundle</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function GymPicker({ onClose, onPick }: { onClose: () => void; onPick: (id: string) => void }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useModalA11y(onClose, dialogRef);
  const [all, setAll] = useState<string[] | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    fetchGymStatus().then((st) => {
      setConnected(st.connected);
      if (st.connected) fetchGymTasks().then((ts) => setAll(ts ? ts.map((x) => x.id) : []));
      else setAll([]);
    });
  }, []);
  const list = (all ?? []).filter((id) => id.toLowerCase().includes(q.toLowerCase())).slice(0, 200);
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(13,13,13,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50 }}>
      <div ref={dialogRef} {...DIALOG} aria-label="Load a gym task" onClick={(e) => e.stopPropagation()} style={{ width: 620, maxHeight: "76vh", background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, display: "flex", flexDirection: "column", overflow: "hidden", outline: "none" }}>
        <div style={{ padding: "18px 20px 12px", borderBottom: `1px solid ${t.n7}` }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: "1rem", fontWeight: weight.bold, color: t.n0 }}>Load a real gym task</span>
            <span onClick={onClose} style={{ cursor: "pointer", color: t.n3, display: "inline-flex" }}><Icon name="close" size={18} /></span>
          </div>
          <div style={{ marginTop: 4, fontSize: "0.8125rem", color: t.n2 }}>Runs the oracle agent live in the gym, then loads the real run + its milestones to review. {connected === false ? "" : all == null ? "Loading catalog…" : `${all.length} tasks.`}</div>
          {connected !== false && (
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter tasks — e.g. buy, refund, subscription…" style={{ marginTop: 12, width: "100%", boxSizing: "border-box", padding: "9px 12px", borderRadius: t.radiusLg, border: `1px solid ${t.n6}`, fontFamily: t.fontPrimary, fontSize: "0.875rem", color: t.n0, outline: "none" }} />
          )}
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
          {connected === false ? (
            <div style={{ padding: "28px 24px", textAlign: "center" }}>
              <div style={{ fontSize: "0.9rem", fontWeight: weight.bold, color: t.n0 }}>Live gym not connected</div>
              <div style={{ margin: "8px auto 0", maxWidth: 440, fontSize: "0.82rem", color: t.n2, lineHeight: 1.55 }}>
                The 312 live gym tasks need a running gym server (set <span style={{ fontFamily: t.fontMono, fontSize: "0.76rem" }}>GYM_URL</span> for a hosted deploy). Everything else — the sample tasks, the correction &amp; re-run flow, the 5-level verifier suite, scoring, and persistence — works without it.
              </div>
              <span onClick={onClose} style={{ display: "inline-block", marginTop: 16, padding: "8px 16px", borderRadius: t.radiusLg, background: t.primary6, color: t.n9, fontSize: "0.82rem", fontWeight: weight.semibold, cursor: "pointer" }}>Back to the sample tasks</span>
            </div>
          ) : all == null ? (
            <div style={{ padding: 24, textAlign: "center", color: t.n3, fontSize: "0.85rem" }}>Fetching the gym catalog…</div>
          ) : list.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: t.n3, fontSize: "0.85rem" }}>{all.length === 0 ? "No gym tasks available." : "No tasks match."}</div>
          ) : (
            list.map((id) => (
              <div key={id} onClick={() => onPick(id)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 20px", cursor: "pointer", fontSize: "0.84rem", color: t.n1, borderBottom: `1px solid ${t.n8}` }}
                onMouseEnter={(e) => (e.currentTarget.style.background = t.surfaceTint)} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                <span style={{ fontFamily: t.fontMono, fontSize: "0.8rem" }}>{id}</span>
                <Icon name="chevronRight" size={15} color={t.n4} />
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function GymLoading({ taskId, phase }: { taskId: string; phase: "queued" | "running" | "done" | "error" }) {
  const heading = phase === "queued" ? "Queued — waiting for the gym…" : "Running the agent in the gym…";
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(13,13,13,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 60 }}>
      <div style={{ width: 420, background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, padding: 26, textAlign: "center" }}>
        <div style={{ fontSize: "1rem", fontWeight: weight.bold, color: t.n0 }}>{heading}</div>
        <div style={{ marginTop: 8, fontSize: "0.84rem", color: t.n2, lineHeight: 1.5 }}>Driving a real browser through <span style={{ fontFamily: t.fontMono, fontSize: "0.78rem" }}>{taskId}</span> and scoring it with the real milestone verifiers. This takes a few seconds.</div>
        <div style={{ marginTop: 16, height: 4, background: t.n7, borderRadius: 3, overflow: "hidden" }}>
          <div style={{ height: "100%", width: "40%", background: t.primary6, borderRadius: 3, animation: "gymbar 1.1s ease-in-out infinite" }} />
        </div>
        <style>{"@keyframes gymbar{0%{margin-left:-40%}100%{margin-left:100%}}"}</style>
      </div>
    </div>
  );
}

export function TaskReview() {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [index, setIndex] = useState(0);
  const [data, setData] = useState<ReviewData | null>(null);
  const [gymData, setGymData] = useState<ReviewData | null>(null);
  const [gymLoading, setGymLoading] = useState<string | null>(null);
  const [gymPhase, setGymPhase] = useState<"queued" | "running" | "done" | "error">("queued");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [gymError, setGymError] = useState<string | null>(null);
  const [freshNonce, setFreshNonce] = useState(0); // >0 forces a new session on remount ("New annotation")
  const [qaOpen, setQaOpen] = useState(false);
  const [queueSet, setQueueSet] = useState<"breakers" | "fixtures">("breakers");
  const [gymAdhoc, setGymAdhoc] = useState(false); // true = loaded off-queue via the Gym picker (not the main queue)
  const { annotator } = useAuth(); // the signed-in identity — replaces the old free-text "AS" field
  const [profileOpen, setProfileOpen] = useState(false);

  // The review queue: the 85 breakers by default, or the demo fixtures.
  useEffect(() => {
    let alive = true;
    fetchTasks(queueSet).then((ts) => { if (alive) { setTasks(ts); setIndex(0); } });
    return () => { alive = false; };
  }, [queueSet]);

  const loadGym = async (id: string, adhoc = false) => {
    setPickerOpen(false);
    setGymError(null);
    setGymAdhoc(adhoc);
    setGymLoading(id);
    // Reopen the SAME persisted run if this task was already reviewed — so the
    // trajectory (and any saved correction fork) is stable across opens instead of
    // re-driving a fresh, stochastic agent every time.
    const cached = await getPersistedGymReview(id);
    if (cached) {
      setGymLoading(null); // dismiss the loader — replaying from the DB is instant
      setGymData(cached);
      return;
    }
    // First time: run the model LIVE (gpt-5.5) — the annotator reviews the model's
    // actual (often breaking) attempt, finds the bad step, corrects it, and the
    // model re-drives from there. The run is persisted, so the next open replays it.
    setGymPhase("queued");
    const rv = await runGymReview(id, "openai", 0, { onStatus: setGymPhase });
    setGymLoading(null);
    if (rv) setGymData(rv);
    else setGymError(id);
  };

  const currentTask = tasks[index];
  const taskId = currentTask?.id ?? TASK_ID;
  // A new task (or entering/exiting the gym) resets the fresh-start intent.
  useEffect(() => { setFreshNonce(0); }, [taskId, gymData?.task.id]);
  // Load the selected task. Breakers (source "gym") run the agent LIVE in the gym
  // and load the real trajectory; demo fixtures load a baked review payload.
  useEffect(() => {
    let alive = true;
    setData(null);
    setGymData(null);
    if (!tasks.length) return;
    if (currentTask?.source === "gym") {
      void loadGym(taskId, false); // a QUEUE breaker — keep the Task N/M pager
    } else {
      fetchReview(taskId).then((r) => {
        if (!alive) return;
        setData(r.data);
        // eslint-disable-next-line no-console
        console.info(`[annotator] review ${taskId} loaded from ${r.source}`);
      });
    }
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, tasks.length]);

  const total = tasks.length || 1;
  const effective = gymData ?? data;
  const nav: TaskNav = {
    index: Math.min(index, total - 1),
    total,
    onPrev: () => { setGymData(null); setIndex((i) => Math.max(0, i - 1)); },
    onNext: () => { setGymData(null); setIndex((i) => Math.min(total - 1, i + 1)); },
    onSkip: () => { setGymData(null); setIndex((i) => (i + 1) % total); },
    onBrowseGym: () => setPickerOpen(true),
    gymTaskId: gymData?.task.id ?? null,
    gymAdhoc,
    // Exiting an off-queue pick returns to the current queue task (reloading it
    // if it's a breaker); it does not leave the queue.
    onExitGym: () => {
      setGymAdhoc(false);
      setGymData(null);
      if (currentTask?.source === "gym") void loadGym(taskId, false);
    },
    onOpenQa: () => setQaOpen(true),
    annotator,
    onOpenProfile: () => setProfileOpen(true),
    queueSet,
    onToggleQueue: () => { setGymData(null); setQueueSet((q) => (q === "breakers" ? "fixtures" : "breakers")); },
    // Prompt edit → re-drive the WHOLE run from the initial state under the new
    // brief (a live gpt-5.5 run), then remount a FRESH review of that new run.
    // Re-drives the DISPLAYED task (an off-queue picker task, else the queue task)
    // — defined whenever a gym task is on screen, not only when the queue task is gym.
    onPromptRerun: (gymData || currentTask?.source === "gym") ? async (prompt: string) => {
      const rid = gymData?.task.id ?? taskId; // the task actually shown, not always the queue task
      setGymError(null);
      setGymPhase("queued");
      setGymLoading(rid);
      const rv = await runGymReview(rid, "openai", 0, { onStatus: setGymPhase, brief: prompt });
      setGymLoading(null);
      if (rv) { setGymData(rv); setFreshNonce((n) => n + 1); } // new trajectory + fresh session
      else setGymError(rid);
    } : undefined,
  };

  return (
    <>
      {effective ? (
        <ReviewScreen
          key={`${gymData ? `gym:${gymData.task.id}` : taskId}#${freshNonce}#${annotator?.email ?? ""}`}
          data={effective}
          nav={nav}
          startFresh={freshNonce > 0}
          onStartNew={() => setFreshNonce((n) => n + 1)}
        />
      ) : (
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: t.n3, fontFamily: t.fontPrimary }}>Loading task…</div>
      )}
      {pickerOpen && <GymPicker onClose={() => setPickerOpen(false)} onPick={(id) => loadGym(id, true)} />}
      {qaOpen && <QaPanel onClose={() => setQaOpen(false)} reviewer={annotator?.email ?? ""} />}
      {profileOpen && <ProfilePanel onClose={() => setProfileOpen(false)} />}
      {gymLoading && <GymLoading taskId={gymLoading} phase={gymPhase} />}
      {gymError && (
        <div style={{ position: "fixed", left: "50%", bottom: 24, transform: "translateX(-50%)", display: "flex", alignItems: "center", gap: 16, background: t.redLite, color: t.redDark, border: `1px solid color-mix(in srgb, ${t.red} 42%, ${t.n9})`, padding: "10px 16px", borderRadius: t.radiusLg, fontSize: "0.84rem", fontWeight: weight.semibold, zIndex: 70, fontFamily: t.fontPrimary, boxShadow: t.shadowLg }}>
          <span>Couldn't run <span style={{ fontFamily: t.fontMono }}>{gymError}</span> — the model produced no run (it may be rate-limited, or the gym is down).</span>
          <span onClick={() => { const id = gymError; setGymError(null); if (id) void loadGym(id, gymAdhoc); }} style={{ cursor: "pointer", textDecoration: "underline", whiteSpace: "nowrap" }}>Retry</span>
          <span onClick={() => setGymError(null)} style={{ cursor: "pointer", opacity: 0.7 }}>✕</span>
        </div>
      )}
    </>
  );
}
