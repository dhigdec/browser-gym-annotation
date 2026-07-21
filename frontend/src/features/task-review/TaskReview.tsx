import { useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import { t, weight } from "../../ds";
import {
  fetchReview,
  openSession,
  patchSession,
  runVerifiers,
  saveSuite,
  submitSession,
} from "../../lib/api";
import type { ReviewData, Verifier } from "../../lib/types";
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
  const [promptOverride, setPromptOverride] = useState<string | null>(null);

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
    openSession(data.task.id).then((snap) => {
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
    const verifiers = verifierPayloads(state);
    const overrides = Object.keys(state.overrides);
    const corrected = state.rerunFrom != null;
    if (sessionId) {
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
              resolved={isResolved(state, current)}
              verified={isVerified(state, current)}
              correcting={correcting}
              correctionSeed={current.type === "error" ? data.correctionSeed : current.description}
              onVerify={() => dispatch({ t: "verifyStep" })}
              onStartCorrect={() => setCorrecting(true)}
              onCancelCorrect={() => setCorrecting(false)}
              onSaveCorrect={() => { dispatch({ t: "correctAndRerun", fromStep: current.idx }); setCorrecting(false); }}
            />
            <Scrubber steps={steps} step={state.step} playing={state.playing} onPlayToggle={() => dispatch({ t: "playToggle" })} onStepTo={(i) => dispatch({ t: "stepTo", i })} />
            <ActionTrace
              steps={steps}
              current={state.step}
              verifiedThrough={state.verifiedThrough}
              stepsApproved={state.stepsApproved}
              remaining={remaining}
              rerunFrom={state.rerunFrom}
              tabs={data.tabs}
              onStepTo={(i) => dispatch({ t: "stepTo", i })}
              onApproveRemaining={() => dispatch({ t: "approveRemaining" })}
            />
          </main>
          <RightPanel task={promptOverride ? { ...data.task, prompt: promptOverride } : data.task} summary={runSummary(state)} onSavePrompt={setPromptOverride} />
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
          onRun={runBenchmark}
          onSubmit={() => dispatch({ t: "submit" })}
        />
      </div>

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
