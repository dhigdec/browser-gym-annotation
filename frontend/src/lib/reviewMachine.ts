import type { MeterState } from "../ds/Meter";
import type { Metric, ReviewState, Step, Verifier } from "./types";
import { STEPS, TASK, generateVerifierSuite } from "../fixtures/task";
import type { VerifierLevel } from "../ds/tokens";

/** Steps 13–15 after the reviewer corrects the corporate-card step. */
const CORRECTED_TAIL: Step[] = [
  { idx: 13, type: "navigate", tabId: "shop", description: "Paid with the personal PayPal" },
  { idx: 14, type: "submit", tabId: "shop", description: "Order placed · confirmation #SG8842" },
  { idx: 15, type: "tab", tabId: "mail", description: "Emailed the total in ShopMail" },
];

export const TOTAL_STEPS = STEPS.length; // 15
const INITIAL_VERIFIED = 11; // parked mid-review on the error step, like the design

export const initialState: ReviewState = {
  step: 11, // 0-based → display step 12 (the ERROR)
  activeTabId: STEPS[11].tabId,
  playing: false,
  verifiedThrough: INITIAL_VERIFIED,
  stepsApproved: false,
  verifiersGenerated: false,
  benchmarkRun: false,
  submitted: false,
  rerunFrom: null,
  overrides: {},
  activeLevel: "ui",
  added: [],
};

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
  switch (a.t) {
    case "stepTo":
      return { ...s, step: a.i, activeTabId: visibleSteps(s)[a.i]?.tabId ?? s.activeTabId, playing: false };
    case "playToggle":
      return { ...s, playing: !s.playing };
    case "tick": {
      const next = Math.min(s.step + 1, TOTAL_STEPS - 1);
      const playing = next < TOTAL_STEPS - 1;
      return { ...s, step: next, activeTabId: visibleSteps(s)[next]?.tabId ?? s.activeTabId, playing };
    }
    case "selectTab":
      return { ...s, activeTabId: a.id };
    case "verifyStep": {
      const verifiedThrough = Math.max(s.verifiedThrough, s.step + 1);
      const step = Math.min(s.step + 1, TOTAL_STEPS - 1);
      return {
        ...s,
        verifiedThrough,
        step,
        activeTabId: visibleSteps(s)[step]?.tabId ?? s.activeTabId,
        stepsApproved: verifiedThrough >= TOTAL_STEPS,
      };
    }
    case "approveRemaining":
      return { ...s, verifiedThrough: TOTAL_STEPS, stepsApproved: true };
    case "generate":
      return s.stepsApproved ? { ...s, verifiersGenerated: true, benchmarkRun: false } : s;
    case "runBenchmark":
      return s.verifiersGenerated ? { ...s, benchmarkRun: true } : s;
    case "correctAndRerun":
      // Correct the trace from `fromStep` and re-run the agent from that state.
      // The re-run trace is auto-approved; the verifier suite must be re-run
      // because the end-state changed. (Cleaner than the prototype's full reset.)
      return {
        ...s,
        rerunFrom: a.fromStep,
        verifiedThrough: TOTAL_STEPS,
        stepsApproved: true,
        benchmarkRun: false,
        overrides: {},
        submitted: false,
        step: fromStepIndex(a.fromStep),
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

const fromStepIndex = (display: number) => display - 1;

// ---- selectors -------------------------------------------------------------

/** The trace shown — base, or the corrected tail after a re-run. */
export function visibleSteps(s: ReviewState): Step[] {
  if (s.rerunFrom == null) return STEPS;
  return [...STEPS.slice(0, 12), ...CORRECTED_TAIL];
}

export function runSummary(s: ReviewState): Metric[] {
  if (s.rerunFrom == null) return TASK.runSummary;
  return TASK.runSummary.map((m) =>
    m.label === "Errors" ? { value: "0", label: "Errors (resolved)", tone: "success" } : m,
  );
}

export function allVerifiers(s: ReviewState): Verifier[] {
  return [...generateVerifierSuite(), ...s.added];
}

/** Per-verifier score state given the current review state. */
export function verifierState(s: ReviewState, v: Verifier): MeterState {
  if (!s.benchmarkRun) return "pending";
  // Rule: an empty/placeholder check never passes.
  if (v.placeholder) return "fail";
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
