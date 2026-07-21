import { useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import { Button, t, weight } from "../../ds";
import {
  fetchReview,
  openSession,
  patchSession,
  recordBenchmark,
  saveSuite,
  submitSession,
} from "../../lib/api";
import type { ReviewData, Verifier } from "../../lib/types";
import {
  benchmarkResults,
  makeInitialState,
  reducer,
  reward,
  runSummary,
  sessionStatus,
  verifierPayloads,
  visibleSteps,
} from "../../lib/reviewMachine";
import { Header } from "./components/Header";
import { ReplayPane } from "./components/ReplayPane";
import { Scrubber } from "./components/Scrubber";
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

function CorrectModal({ seed, onCancel, onSave }: { seed: string; onCancel: () => void; onSave: () => void }) {
  const [text, setText] = useState(seed);
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(13,13,13,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }} onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 560, background: t.n9, borderRadius: t.radius2xl, boxShadow: t.shadowXl, padding: 22 }}>
        <div style={{ fontSize: "1rem", fontWeight: weight.bold, color: t.n0 }}>Correct this step</div>
        <div style={{ marginTop: 4, fontSize: "0.8125rem", color: t.n2 }}>Describe the correct action. The agent re-runs from this state.</div>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} style={{ marginTop: 14, width: "100%", boxSizing: "border-box", padding: "10px 12px", borderRadius: t.radiusLg, border: `1px solid ${t.n6}`, fontFamily: t.fontPrimary, fontSize: "0.875rem", color: t.n0, resize: "vertical", outline: "none" }} />
        <div style={{ marginTop: 8, fontSize: "0.72rem", color: t.n3 }}>Steps after this point are discarded and re-generated.</div>
        <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button onClick={onSave}>Save &amp; re-run</Button>
        </div>
      </div>
    </div>
  );
}

function Frame({ children }: { children: ReactNode }) {
  return (
    <div style={{ width: 1440, margin: "0 auto", minHeight: "100vh", display: "flex", flexDirection: "column", background: t.n85, border: `1px solid ${t.n7}` }}>
      {children}
    </div>
  );
}

function ReviewScreen({ data }: { data: ReviewData }) {
  const [state, dispatch] = useReducer(reducer, data, makeInitialState);
  const [correcting, setCorrecting] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  useEffect(() => {
    if (!state.playing) return;
    const id = setInterval(() => dispatch({ t: "tick" }), 1100);
    return () => clearInterval(id);
  }, [state.playing]);

  // ---- M4 persistence: open/resume the session, then mirror each committed
  // transition to the backend so the annotator's work survives a refresh.
  const statusRef = useRef<string>("draft");
  const suiteSigRef = useRef<string>("");
  const benchPostedRef = useRef(false);
  const submittedRef = useRef(false);
  const rerunRef = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    openSession(data.task.id).then((snap) => {
      if (!alive || !snap) return;
      setSessionId(snap.sessionId);
      // Seed the sync refs to the restored state so we don't echo it back.
      statusRef.current = snap.status;
      rerunRef.current = snap.rerunFrom;
      benchPostedRef.current = snap.status === "benchmark_run" || snap.status === "submitted";
      submittedRef.current = snap.status === "submitted";
      const restored = reducer(makeInitialState(data), {
        t: "hydrate",
        status: snap.status,
        rerunFrom: snap.rerunFrom,
      });
      suiteSigRef.current = restored.verifiersGenerated
        ? JSON.stringify(verifierPayloads(restored))
        : "";
      if (snap.status !== "draft" || snap.rerunFrom != null) {
        dispatch({ t: "hydrate", status: snap.status, rerunFrom: snap.rerunFrom });
      }
    });
    return () => {
      alive = false;
    };
  }, [data.task.id]);

  // Gate-status transitions (draft → steps_approved → verifiers_generated).
  const status = sessionStatus(state);
  useEffect(() => {
    if (!sessionId || status === statusRef.current) return;
    statusRef.current = status;
    if (status === "steps_approved" || status === "verifiers_generated") {
      void patchSession(sessionId, { status });
    }
  }, [sessionId, status]);

  // Correction fork — persist the re-run point.
  useEffect(() => {
    if (!sessionId || state.rerunFrom === rerunRef.current) return;
    rerunRef.current = state.rerunFrom;
    if (state.rerunFrom != null) {
      void patchSession(sessionId, { rerunFrom: state.rerunFrom, status: "steps_approved" });
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

  // Benchmark — record one run on each false→true edge (each re-run).
  useEffect(() => {
    if (!sessionId) return;
    if (state.benchmarkRun && !benchPostedRef.current) {
      benchPostedRef.current = true;
      void recordBenchmark(sessionId, reward(state) ?? 0, benchmarkResults(state));
    } else if (!state.benchmarkRun) {
      benchPostedRef.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, state.benchmarkRun]);

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
      <Header />
      <div style={{ padding: "16px 16px 8px" }}>
        <SectionHeader n={1} title="Review & correct the agent run" subtitle="Verify each step; correct any step to re-run the agent from that state." right={<SaveBadge sessionId={sessionId} status={status} />} />
        <div style={{ display: "flex", gap: 16, height: 632 }}>
          <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 12 }}>
            <ReplayPane
              tabs={data.tabs}
              activeTabId={state.activeTabId}
              onSelectTab={(id) => dispatch({ t: "selectTab", id })}
              step={current}
              stepNumber={current.idx}
              corrected={state.rerunFrom != null}
              onVerify={() => dispatch({ t: "verifyStep" })}
              onCorrect={() => setCorrecting(true)}
            />
            <Scrubber steps={steps} step={state.step} playing={state.playing} onPlayToggle={() => dispatch({ t: "playToggle" })} onStepTo={(i) => dispatch({ t: "stepTo", i })} />
            <ActionTrace
              steps={steps}
              current={state.step}
              verifiedThrough={state.verifiedThrough}
              stepsApproved={state.stepsApproved}
              remaining={remaining}
              tabs={data.tabs}
              onStepTo={(i) => dispatch({ t: "stepTo", i })}
              onApproveRemaining={() => dispatch({ t: "approveRemaining" })}
            />
          </main>
          <RightPanel task={data.task} summary={runSummary(state)} />
        </div>
      </div>

      <div style={{ padding: "8px 16px 24px" }}>
        <SectionHeader n={2} title="Build the verifier suite" subtitle="Generate multi-level verifiers, edit them, then run the benchmark. Reward = 1 requires every verifier to pass." done={state.submitted} />
        <VerifierSuite
          state={state}
          onGenerate={() => dispatch({ t: "generate" })}
          onSetLevel={(l) => dispatch({ t: "setLevel", level: l })}
          onAddVerifier={onAddVerifier}
          onEditVerifier={(id, assertion, code) => dispatch({ t: "editVerifier", id, assertion, code })}
          onOverride={(id) => dispatch({ t: "override", id })}
          onRun={() => dispatch({ t: "runBenchmark" })}
          onSubmit={() => dispatch({ t: "submit" })}
        />
      </div>

      {correcting && (
        <CorrectModal
          seed={data.correctionSeed}
          onCancel={() => setCorrecting(false)}
          onSave={() => { dispatch({ t: "correctAndRerun", fromStep: current.idx }); setCorrecting(false); }}
        />
      )}
    </Frame>
  );
}

export function TaskReview() {
  const [data, setData] = useState<ReviewData | null>(null);

  useEffect(() => {
    let alive = true;
    fetchReview(TASK_ID).then((r) => {
      if (!alive) return;
      setData(r.data);
      // eslint-disable-next-line no-console
      console.info(`[annotator] review loaded from ${r.source}`);
    });
    return () => { alive = false; };
  }, []);

  if (!data) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: t.n3, fontFamily: t.fontPrimary }}>
        Loading task…
      </div>
    );
  }
  return <ReviewScreen data={data} />;
}
