import type { MeterState } from "../ds/Meter";
import type { VerifierLevel } from "../ds/tokens";
import type { Metric, ReviewData, ReviewState, Step, Verifier } from "./types";

/** Seed the review state from a loaded payload — start at step 1, with nothing
 *  reviewed yet, so the annotator walks the run from the beginning. */
export function makeInitialState(data: ReviewData): ReviewState {
  return {
    data,
    step: 0,
    activeTabId: data.steps[0]?.tabId ?? data.tabs[0]?.id ?? "",
    playing: false,
    verifiedThrough: 0,
    stepsApproved: false,
    verifiersGenerated: false,
    benchmarkRun: false,
    submitted: false,
    rerunFrom: null,
    overrides: {},
    activeLevel: "ui",
    added: [],
    edits: {},
    results: {},
    branchTail: null,
    rerunMode: null,
    gymResumeReward: null,
    serverSubmission: null,
    submitError: null,
  };
}

/** An empty or placeholder check never passes. */
export function isPlaceholder(code: string): boolean {
  return !code.trim() || code.includes("/* define check */");
}

export type Action =
  | { t: "stepTo"; i: number }
  | { t: "playToggle" }
  | { t: "tick" }
  | { t: "selectTab"; id: string }
  | { t: "verifyStep" }
  | { t: "approveRemaining" }
  | { t: "generate" }
  | { t: "benchmarkComplete"; results: Record<string, string> }
  | { t: "correctAndRerun"; fromStep: number; branch: Step[] | null; mode: string | null }
  | { t: "gymResumed"; reward: number }
  | { t: "setLevel"; level: VerifierLevel }
  | { t: "addVerifier"; verifier: Verifier }
  | { t: "removeVerifier"; id: string }
  | { t: "editVerifier"; id: string; assertion: string; code: string }
  | { t: "override"; id: string }
  | { t: "submit" }
  | { t: "submitConfirmed"; reward: number; kind: string }
  | { t: "submitFailed"; error: string }
  | {
      t: "hydrate";
      status: PersistStatus;
      rerunFrom: number | null;
      reviewedThrough: number;
      results: Record<string, string>;
      // Restored from the DB so the fork + suite + attestations survive a refresh.
      branchTail?: Step[] | null;
      rerunMode?: string | null;
      added?: Verifier[];
      edits?: Record<string, { assertion: string; code: string }>;
      overrides?: Record<string, boolean>;
    };

export type PersistStatus =
  | "draft"
  | "steps_approved"
  | "verifiers_generated"
  | "benchmark_run"
  | "submitted";

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
      return s.stepsApproved ? { ...s, verifiersGenerated: true, benchmarkRun: false, results: {} } : s;
    case "benchmarkComplete":
      return s.verifiersGenerated ? { ...s, benchmarkRun: true, results: a.results } : s;
    case "gymResumed":
      // A gym task re-verified against the LIVE gym after a correction — the
      // real milestone verdict on the resumed corrected state is the reward.
      return { ...s, gymResumeReward: a.reward, benchmarkRun: true };
    case "correctAndRerun": {
      // Correcting a step re-forks the trace and RE-LOCKS Section 2 entirely
      // (spec §3.25): the annotator must re-approve, re-generate, and re-run.
      // The re-run steps are auto-marked reviewed (Reviewed N/N, spec §2.3).
      // Fork at the ACTUAL correction point: keep the first `fromStep` steps and
      // append the branch (the backend re-indexes it contiguously from
      // fromStep+1), so the count/total agree and the playhead can never overrun
      // the rebuilt array (which crashed the reviewer when correcting a late step).
      const tail = a.branch ?? s.data.correctedTail;
      const newTotal = a.fromStep + tail.length;
      return {
        ...s,
        rerunFrom: a.fromStep,
        branchTail: a.branch,
        rerunMode: a.mode,
        verifiedThrough: newTotal,
        stepsApproved: false,
        verifiersGenerated: false,
        benchmarkRun: false,
        results: {},
        overrides: {},
        submitted: false,
        step: Math.min(Math.max(a.fromStep - 1, 0), newTotal - 1),
      };
    }
    case "setLevel":
      return { ...s, activeLevel: a.level };
    case "addVerifier":
      return { ...s, added: [...s.added, a.verifier], benchmarkRun: false, results: {}, submitted: false };
    case "removeVerifier":
      return { ...s, added: s.added.filter((v) => v.id !== a.id), benchmarkRun: false, results: {} };
    case "editVerifier":
      return { ...s, edits: { ...s.edits, [a.id]: { assertion: a.assertion, code: a.code } }, benchmarkRun: false, results: {}, submitted: false };
    case "override": {
      // Toggle: clicking the "1 override" pill removes the override (spec §3.2).
      // Overriding invalidates the last run — force a re-benchmark so the override
      // actually reaches a real server run (which records the overridden ids).
      const next = { ...s.overrides };
      if (next[a.id]) delete next[a.id];
      else next[a.id] = true;
      return { ...s, overrides: next, benchmarkRun: false, results: {}, submitted: false };
    }
    case "submit":
      return s; // no-op: submission is server-confirmed via submitConfirmed/submitFailed
    case "submitConfirmed":
      // Only NOW is it submitted — with the SERVER's authoritative reward/kind.
      return { ...s, submitted: true, submitError: null, serverSubmission: { reward: a.reward, kind: a.kind } };
    case "submitFailed":
      return { ...s, submitted: false, submitError: a.error };
    case "hydrate": {
      // Restore the gate chain, correction fork, authored suite, and human
      // attestations from a persisted session so the annotator's work survives a
      // refresh EXACTLY as they left it. branchTail must be applied before
      // visibleSteps is read (it determines the fork's step count).
      const base = {
        ...s,
        rerunFrom: a.rerunFrom,
        branchTail: a.branchTail ?? s.branchTail,
        rerunMode: a.rerunMode ?? s.rerunMode,
        added: a.added ?? s.added,
        edits: a.edits ?? s.edits,
        overrides: a.overrides ?? s.overrides,
      };
      const vs = visibleSteps(base);
      const approved = a.status !== "draft";
      return {
        ...base,
        stepsApproved: approved,
        verifiersGenerated: ["verifiers_generated", "benchmark_run", "submitted"].includes(a.status),
        benchmarkRun: ["benchmark_run", "submitted"].includes(a.status),
        submitted: a.status === "submitted",
        // Restore the granular review progress from the DB (everything once the
        // steps were approved). With branchTail restored, vs.length equals the
        // count reviewed_through was written against, so they can't disagree.
        verifiedThrough: Math.max(s.verifiedThrough, a.reviewedThrough, approved ? vs.length : 0),
        // Always open at step 1 (never re-park on the error step).
        step: 0,
        activeTabId: vs[0]?.tabId ?? s.activeTabId,
        results: a.results,
      };
    }
    default:
      return s;
  }
}

// ---- selectors -------------------------------------------------------------

export function visibleSteps(s: ReviewState): Step[] {
  if (s.rerunFrom == null) return s.data.steps;
  // Prefer the server-computed branch (M6); fall back to the offline fixture tail.
  const tail = s.branchTail ?? s.data.correctedTail;
  // Fork at the ACTUAL correction point (rerunFrom), not the error step: keep the
  // first `rerunFrom` original steps, then the branch (which the backend
  // re-indexes contiguously from rerunFrom+1). This keeps idx values unique and
  // makes the slice, fork divider, status circles, and React keys all agree.
  return [...s.data.steps.slice(0, s.rerunFrom), ...tail];
}

export function runSummary(s: ReviewState): Metric[] {
  if (s.rerunFrom == null) return s.data.task.runSummary;
  const total = visibleSteps(s).length;
  return s.data.task.runSummary.map((m) => {
    if (m.label === "Errors") return { value: "0", label: "Errors (resolved)", tone: "success" };
    if (m.label === "Steps used") return { ...m, value: `${total}/20` };
    return m;
  });
}

export function allVerifiers(s: ReviewState): Verifier[] {
  return [...s.data.verifiers, ...s.added].map((v) => {
    const e = s.edits[v.id];
    return e ? { ...v, assertion: e.assertion, code: e.code, placeholder: isPlaceholder(e.code) } : v;
  });
}

export function verifierState(s: ReviewState, v: Verifier): MeterState {
  if (!s.benchmarkRun) return "pending";
  if (s.overrides[v.id]) return "pass"; // human-attested (stamped)
  if (v.gymResult === "pass" || v.gymResult === "fail") return v.gymResult; // real gym milestone (M8)
  if (v.placeholder) return "fail"; // empty/placeholder never passes
  const r = s.results[v.id]; // real result from the execution engine
  if (r === "pass" || r === "fail" || r === "pending") return r as MeterState;
  return "fail"; // ran, but no result for this check → unproven, fails closed
}

export function reward(s: ReviewState): number | null {
  if (s.serverSubmission) return s.serverSubmission.reward; // authoritative once submitted
  if (!s.benchmarkRun) return null;
  // Gym tasks carry the authoritative real milestone verdict (M8).
  if (s.data.source === "gym") return s.gymResumeReward ?? s.data.gymReward ?? 0;
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

// ---- per-step review status (spec §2.3 / §2.1) ----------------------------

export type StepStatus = "verified" | "corrected" | "rerun" | "pending";

/** The trace status-circle variant for a step. */
export function stepStatus(s: ReviewState, step: Step): StepStatus {
  if (s.rerunFrom != null) {
    if (step.idx === s.rerunFrom) return "corrected";
    if (step.idx > s.rerunFrom) return "rerun";
  }
  return step.idx <= s.verifiedThrough ? "verified" : "pending";
}

/** A corrected or re-run step — its overlay shows the "Re-run branch" pill
 *  instead of Verify/Correct, and it can't be re-verified. */
export function isResolved(s: ReviewState, step: Step): boolean {
  return s.rerunFrom != null && step.idx >= s.rerunFrom;
}

/** Whether a step has already been reviewed (drives the Verify → Verified flip). */
export function isVerified(s: ReviewState, step: Step): boolean {
  return step.idx <= s.verifiedThrough;
}

/** The index of the first re-run step, for placing the fork divider. */
export function forkIndex(s: ReviewState, steps: Step[]): number {
  if (s.rerunFrom == null) return -1;
  return steps.findIndex((st) => st.idx > s.rerunFrom!);
}

// ---- persistence projections (M4) -----------------------------------------

/** The gate-chain status persisted to the backend. */
export function sessionStatus(s: ReviewState): PersistStatus {
  if (s.submitted) return "submitted";
  if (s.benchmarkRun) return "benchmark_run";
  if (s.verifiersGenerated) return "verifiers_generated";
  if (s.stepsApproved) return "steps_approved";
  return "draft";
}

/** The current suite flattened for the save-suite / run endpoints. */
export function verifierPayloads(s: ReviewState) {
  return allVerifiers(s).map((v) => ({
    id: v.id,
    level: v.level as string,
    assertion: v.assertion,
    code: v.code,
    check: v.check ?? null,
    failsUntilCorrected: !!v.failsUntilCorrected,
    placeholder: !!v.placeholder,
    addedByHuman: v.id.startsWith("add-"),
  }));
}

/** Offline fallback when the execution engine is unreachable — flag-derived
 *  pass/fail (no real evaluation). The API path uses the backend executor. */
export function offlineResults(s: ReviewState): Record<string, string> {
  const out: Record<string, string> = {};
  for (const v of allVerifiers(s)) {
    if (v.placeholder) out[v.id] = "fail";
    else if (s.overrides[v.id]) out[v.id] = "pass";
    else if (v.failsUntilCorrected && s.rerunFrom == null) out[v.id] = "fail";
    else out[v.id] = "pass";
  }
  return out;
}
