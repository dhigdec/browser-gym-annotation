import { useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import { Button, Icon, t, weight } from "../../ds";
import {
  adjudicate,
  autogenVerifiers,
  driveForwardGym,
  fetchGymStatus,
  fetchQaSubmissions,
  fetchQaTasks,
  fetchGymTasks,
  fetchReview,
  fetchTasks,
  openSession,
  patchSession,
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
import { Header } from "./components/Header";
import { ReplayPane } from "./components/ReplayPane";
import { ActionTrace } from "./components/ActionTrace";
import { RightPanel } from "./components/RightPanel";
import { VerifierSuite } from "./components/VerifierSuite";

const TASK_ID = "GYM-2041";

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
  annotatorEmail: string;
  onSetAnnotator: (email: string) => void;
}

function ReviewScreen({ data, nav, startFresh, onStartNew }: { data: ReviewData; nav: TaskNav; startFresh: boolean; onStartNew: () => void }) {
  const [state, dispatch] = useReducer(reducer, data, makeInitialState);
  const [correcting, setCorrecting] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [promptOverride, setPromptOverride] = useState<string | null>(null);
  const [driving, setDriving] = useState<null | "queued" | "running">(null);
  const [autogen, setAutogen] = useState<null | "queued" | "running">(null);
  const [autogenResult, setAutogenResult] = useState<AutogenResult | null>(null);
  const [editingState, setEditingState] = useState(false);

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

  useEffect(() => {
    let alive = true;
    openSession(data.task.id, { fresh: startFresh, annotatorEmail: nav.annotatorEmail }).then((snap) => {
      if (!alive || !snap) return;
      setSessionId(snap.sessionId);
      // Seed the sync refs to the restored state so we don't echo it back.
      statusRef.current = snap.status;
      rerunRef.current = snap.rerunFrom;
      submittedRef.current = snap.status === "submitted";
      const results = (snap.lastBenchmark?.results as Record<string, string>) ?? {};
      const restored = reducer(makeInitialState(data), {
        t: "hydrate",
        status: snap.status,
        rerunFrom: snap.rerunFrom,
        results,
      });
      suiteSigRef.current = restored.verifiersGenerated
        ? JSON.stringify(verifierPayloads(restored))
        : "";
      if (snap.status !== "draft" || snap.rerunFrom != null) {
        dispatch({ t: "hydrate", status: snap.status, rerunFrom: snap.rerunFrom, results });
      }
    });
    return () => {
      alive = false;
    };
  }, [data.task.id]);

  // Run the verifier suite through the backend execution engine (M5). Falls
  // back to a flag-derived result only when the backend is unreachable.
  const runBenchmark = async () => {
    // Gym tasks carry the real milestone verdict already (verifierState/reward
    // read v.gymResult / data.gymReward) — just reveal it.
    if (data.source === "gym") {
      dispatch({ t: "benchmarkComplete", results: {} });
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

  // Correction fork — persist the re-run point (correcting re-locks Section 2).
  useEffect(() => {
    if (!sessionId || state.rerunFrom === rerunRef.current) return;
    rerunRef.current = state.rerunFrom;
    if (state.rerunFrom != null) {
      void patchSession(sessionId, { rerunFrom: state.rerunFrom });
    }
  }, [sessionId, state.rerunFrom]);

  // Verifier suite — save a new immutable version whenever it changes.
  const suiteSig = state.verifiersGenerated ? JSON.stringify(verifierPayloads(state)) : "";
  useEffect(() => {
    if (!sessionId || !suiteSig || suiteSig === suiteSigRef.current) return;
    suiteSigRef.current = suiteSig;
    void saveSuite(sessionId, verifierPayloads(state));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, suiteSig]);

  // Submission — write the dataset row once.
  useEffect(() => {
    if (!sessionId) return;
    if (state.submitted && !submittedRef.current) {
      submittedRef.current = true;
      void submitSession(sessionId, {
        reward: reward(state) ?? 0,
        override: Object.keys(state.overrides).length > 0,
        kind: reward(state) === 1 ? "golden" : "breaker",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, state.submitted]);

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
                  setDriving("queued");
                  const res = await driveForwardGym(
                    { taskId: data.task.id, seed: data.gymResume!.seed, worldState: data.gymResume!.worldState, resumeUrl: data.gymResume!.finalUrl || "/", agent: "llm" },
                    { onStatus: (s) => setDriving(s === "done" || s === "error" ? null : s) },
                  );
                  setDriving(null);
                  if (res) dispatch({ t: "gymResumed", reward: res.reward });
                }}
                title="Load the corrected state and let a live agent continue the task in the gym (slow)"
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
        <div style={{ display: "flex", gap: 16, height: 632 }}>
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
                // Gym tasks resume from the corrected state IN THE LIVE GYM: load
                // the captured world, replay the trajectory, and read the REAL
                // milestone verdict — not a canned tail. (Fixture tasks below use
                // the deterministic/agent branch.)
                if (data.source === "gym" && data.gymResume) {
                  const edits = parseStateEdits(text); // `path = value` lines → real state edits
                  const res = await resumeGymReview({
                    taskId: data.task.id,
                    seed: data.gymResume.seed,
                    worldState: data.gymResume.worldState,
                    urlTrail: data.gymResume.urlTrail,
                    finalUrl: data.gymResume.finalUrl,
                    edits: Object.keys(edits).length ? edits : undefined,
                  });
                  if (res) dispatch({ t: "gymResumed", reward: res.reward });
                  return;
                }
                let branch: Step[] | null = null;
                let mode: string | null = null;
                if (sessionId) {
                  const out = await rerunTrajectory(sessionId, { fromStep: current.idx, correction: text, mode: "agent" });
                  if (out) { branch = out.steps; mode = out.mode; }
                }
                dispatch({ t: "correctAndRerun", fromStep: current.idx, branch, mode });
              }}
              onPlayToggle={() => dispatch({ t: "playToggle" })}
              onStepTo={(i) => dispatch({ t: "stepTo", i })}
            />
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
          </main>
          <RightPanel task={promptOverride ? { ...data.task, prompt: promptOverride } : data.task} summary={runSummary(state)} onSavePrompt={setPromptOverride} />
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
          onSubmit={() => dispatch({ t: "submit" })}
        />
      </div>

      {autogenResult && <AutogenPanel result={autogenResult} onClose={() => setAutogenResult(null)} />}
      {editingState && data.source === "gym" && data.gymResume && (
        <StateEditor
          world={data.gymResume.worldState ?? {}}
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
      <div onClick={(e) => e.stopPropagation()} style={{ width: 520, background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, display: "flex", flexDirection: "column", overflow: "hidden" }}>
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
  const ok = result.oracle;
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(13,13,13,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 55 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 660, maxHeight: "80vh", background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, display: "flex", flexDirection: "column", overflow: "hidden" }}>
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
      <div onClick={(e) => e.stopPropagation()} style={{ width: 840, height: "78vh", background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "18px 22px 14px", borderBottom: `1px solid ${t.n7}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: "1rem", fontWeight: weight.bold, color: t.n0 }}>⚖ Multi-annotator QA</div>
            <div style={{ marginTop: 3, fontSize: "0.8rem", color: t.n2 }}>Agreement across annotators; accept one submission as the golden. Reviewing as <span style={{ fontFamily: t.fontMono, fontSize: "0.74rem" }}>{reviewer}</span>.</div>
          </div>
          <span onClick={onClose} style={{ cursor: "pointer", color: t.n3, display: "inline-flex" }}><Icon name="close" size={18} /></span>
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
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function GymPicker({ onClose, onPick }: { onClose: () => void; onPick: (id: string) => void }) {
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
      <div onClick={(e) => e.stopPropagation()} style={{ width: 620, maxHeight: "76vh", background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, display: "flex", flexDirection: "column", overflow: "hidden" }}>
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
  const [annotatorEmail, setAnnotatorEmail] = useState(() => localStorage.getItem("annotatorEmail") || "annotator@deccan.ai");

  useEffect(() => {
    let alive = true;
    fetchTasks().then((ts) => { if (alive) setTasks(ts); });
    return () => { alive = false; };
  }, []);

  const taskId = tasks[index]?.id ?? TASK_ID;
  // A new task (or entering/exiting the gym) resets the fresh-start intent.
  useEffect(() => { setFreshNonce(0); }, [taskId, gymData?.task.id]);
  useEffect(() => {
    let alive = true;
    setData(null);
    fetchReview(taskId).then((r) => {
      if (!alive) return;
      setData(r.data);
      // eslint-disable-next-line no-console
      console.info(`[annotator] review ${taskId} loaded from ${r.source}`);
    });
    return () => { alive = false; };
  }, [taskId]);

  const loadGym = async (id: string) => {
    setPickerOpen(false);
    setGymError(null);
    setGymPhase("queued");
    setGymLoading(id);
    const rv = await runGymReview(id, "oracle", 0, { onStatus: setGymPhase });
    setGymLoading(null);
    if (rv) setGymData(rv);
    else setGymError(id);
  };

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
    onExitGym: () => setGymData(null),
    onOpenQa: () => setQaOpen(true),
    annotatorEmail,
    onSetAnnotator: (email) => { setAnnotatorEmail(email); localStorage.setItem("annotatorEmail", email); },
  };

  return (
    <>
      {effective ? (
        <ReviewScreen
          key={`${gymData ? `gym:${gymData.task.id}` : taskId}#${freshNonce}#${annotatorEmail}`}
          data={effective}
          nav={nav}
          startFresh={freshNonce > 0}
          onStartNew={() => setFreshNonce((n) => n + 1)}
        />
      ) : (
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: t.n3, fontFamily: t.fontPrimary }}>Loading task…</div>
      )}
      {pickerOpen && <GymPicker onClose={() => setPickerOpen(false)} onPick={loadGym} />}
      {qaOpen && <QaPanel onClose={() => setQaOpen(false)} reviewer={annotatorEmail} />}
      {gymLoading && <GymLoading taskId={gymLoading} phase={gymPhase} />}
      {gymError && (
        <div onClick={() => setGymError(null)} style={{ position: "fixed", left: "50%", bottom: 24, transform: "translateX(-50%)", background: t.redLite, color: t.redDark, border: `1px solid color-mix(in srgb, ${t.red} 42%, ${t.n9})`, padding: "10px 16px", borderRadius: t.radiusLg, fontSize: "0.84rem", fontWeight: weight.semibold, zIndex: 70, cursor: "pointer", fontFamily: t.fontPrimary }}>
          Couldn't run <span style={{ fontFamily: t.fontMono }}>{gymError}</span> — the gym may be down or the task has no oracle solver. Tap to dismiss.
        </div>
      )}
    </>
  );
}
