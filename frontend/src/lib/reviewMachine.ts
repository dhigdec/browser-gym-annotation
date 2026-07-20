import type { MeterState } from "../ds/Meter";
import type { VerifierLevel } from "../ds/tokens";
import type { Metric, ReviewData, ReviewState, Step, Verifier } from "./types";

function errorIndex(steps: Step[]): number {
  const i = steps.findIndex((s) => s.type === "error");
  return i >= 0 ? i : Math.max(0, steps.length - 1);
}

/** Seed the review state from a loaded payload — parked on the error step,
 *  with the steps before it already reviewed (mirrors the design). */
export function makeInitialState(data: ReviewData): ReviewState {
  const ei = errorIndex(data.steps);
  return {
    data,
    step: ei,
    activeTabId: data.steps[ei]?.tabId ?? data.tabs[0]?.id ?? "",
    playing: false,
    verifiedThrough: ei,
    stepsApproved: false,
    verifiersGenerated: false,
    benchmarkRun: false,
    submitted: false,
    rerunFrom: null,
    overrides: {},
    activeLevel: "ui",
    added: [],
  };
}

export type Action =
  | { t: "stepTo"; i: number }
  | { t: "playToggle" }
  | { t: "tick" }
  | { t: "selectTab"; id: string }
  | { t: "verifyStep" }
  | { t: "approveRemaining" }
  | { t: "generate" }
  | { t: "runBenchmark" }
  | { t: "correctAndRerun"; fromStep: number }
  | { t: "setLevel"; level: VerifierLevel }
  | { t: "addVerifier"; verifier: Verifier }
  | { t: "removeVerifier"; id: string }
  | { t: "override"; id: string }
  | { t: "submit" };

export function reducer(s: ReviewState, a: Action): ReviewState {
  const steps = visibleSteps(s);
  const total = steps.length;
  switch (a.t) {
    case "stepTo":
      return { ...s, step: a.i, activeTabId: steps[a.i]?.tabId ?? s.activeTabId, playing: false };
    case "playToggle":
      return { ...s, playing: !s.playing };
    case "tick": {
      const next = Math.min(s.step + 1, total - 1);
      return { ...s, step: next, activeTabId: steps[next]?.tabId ?? s.activeTabId, playing: next < total - 1 };
    }
    case "selectTab":
      return { ...s, activeTabId: a.id };
    case "verifyStep": {
      const verifiedThrough = Math.max(s.verifiedThrough, s.step + 1);
      const step = Math.min(s.step + 1, total - 1);
      return { ...s, verifiedThrough, step, activeTabId: steps[step]?.tabId ?? s.activeTabId, stepsApproved: verifiedThrough >= total };
    }
    case "approveRemaining":
      return { ...s, verifiedThrough: total, stepsApproved: true };
    case "generate":
      return s.stepsApproved ? { ...s, verifiersGenerated: true, benchmarkRun: false } : s;
    case "runBenchmark":
      return s.verifiersGenerated ? { ...s, benchmarkRun: true } : s;
    case "correctAndRerun":
      return {
        ...s,
        rerunFrom: a.fromStep,
        verifiedThrough: total,
        stepsApproved: true,
        benchmarkRun: false,
        overrides: {},
        submitted: false,
        step: a.fromStep - 1,
      };
    case "setLevel":
      return { ...s, activeLevel: a.level };
    case "addVerifier":
      return { ...s, added: [...s.added, a.verifier], benchmarkRun: false, submitted: false };
    case "removeVerifier":
      return { ...s, added: s.added.filter((v) => v.id !== a.id), benchmarkRun: false };
    case "override":
      return { ...s, overrides: { ...s.overrides, [a.id]: true }, submitted: false };
    case "submit":
      return canSubmit(s) ? { ...s, submitted: true } : s;
    default:
      return s;
  }
}

// ---- selectors -------------------------------------------------------------

export function visibleSteps(s: ReviewState): Step[] {
  if (s.rerunFrom == null) return s.data.steps;
  const ei = errorIndex(s.data.steps);
  return [...s.data.steps.slice(0, ei + 1), ...s.data.correctedTail];
}

export function runSummary(s: ReviewState): Metric[] {
  if (s.rerunFrom == null) return s.data.task.runSummary;
  return s.data.task.runSummary.map((m) =>
    m.label === "Errors" ? { value: "0", label: "Errors (resolved)", tone: "success" } : m,
  );
}

export function allVerifiers(s: ReviewState): Verifier[] {
  return [...s.data.verifiers, ...s.added];
}

export function verifierState(s: ReviewState, v: Verifier): MeterState {
  if (!s.benchmarkRun) return "pending";
  if (v.placeholder) return "fail"; // empty/placeholder never passes
  if (v.failsUntilCorrected && s.rerunFrom == null && !s.overrides[v.id]) return "fail";
  return "pass";
}

export function reward(s: ReviewState): number | null {
  if (!s.benchmarkRun) return null;
  return allVerifiers(s).every((v) => verifierState(s, v) === "pass") ? 1 : 0;
}

export function levelVerifiers(s: ReviewState, level: VerifierLevel): Verifier[] {
  return allVerifiers(s).filter((v) => v.level === level);
}

export function levelScore(s: ReviewState, level: VerifierLevel): { pass: number; total: number } {
  const vs = levelVerifiers(s, level);
  return { pass: vs.filter((v) => verifierState(s, v) === "pass").length, total: vs.length };
}

export function failingCount(s: ReviewState): number {
  return allVerifiers(s).filter((v) => verifierState(s, v) === "fail").length;
}

export function canSubmit(s: ReviewState): boolean {
  return s.benchmarkRun && reward(s) === 1;
}
