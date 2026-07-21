import { describe, expect, it } from "vitest";
import {
  isResolved,
  isVerified,
  makeInitialState,
  reducer,
  reward,
  sessionStatus,
  stepStatus,
  verifierPayloads,
  verifierState,
  visibleSteps,
} from "./reviewMachine";
import type { ReviewData, ReviewState, Verifier } from "./types";

const data: ReviewData = {
  task: { id: "T", priority: "High", title: "t", meta: "m", prompt: "p", startState: { summary: "", url: "" }, constraints: [], allowedSites: [], runSummary: [] },
  tabs: [{ id: "shop", title: "Shop", host: "h", color: "#000" }],
  steps: [
    { idx: 1, type: "navigate", tabId: "shop", description: "a" },
    { idx: 2, type: "click", tabId: "shop", description: "b" },
    { idx: 3, type: "error", tabId: "shop", description: "err" },
  ],
  correctionSeed: "fix",
  correctedTail: [
    { idx: 4, type: "submit", tabId: "shop", description: "c" },
    { idx: 5, type: "tab", tabId: "shop", description: "d" },
  ],
  verifiers: [
    { id: "v1", level: "ui", assertion: "a1", code: "c1" },
    { id: "v2", level: "safety", assertion: "a2", code: "c2" },
  ],
};

const generated = (): ReviewState => {
  let s = makeInitialState(data);
  s = reducer(s, { t: "approveRemaining" });
  return reducer(s, { t: "generate" });
};

describe("submit reconciliation (server-authoritative)", () => {
  it("is 'submitted' only after the server confirms, with the SERVER's reward", () => {
    let s = generated();
    s = reducer(s, { t: "benchmarkComplete", results: { v1: "pass", v2: "pass" } });
    // client would compute reward 1; the server says 0 / breaker — that must win.
    s = reducer(s, { t: "submitConfirmed", reward: 0, kind: "breaker" });
    expect(s.submitted).toBe(true);
    expect(reward(s)).toBe(0);
  });

  it("submitFailed surfaces an error and does NOT mark submitted", () => {
    let s = generated();
    s = reducer(s, { t: "submitFailed", error: "boom" });
    expect(s.submitted).toBe(false);
    expect(s.submitError).toBe("boom");
  });

  it("overriding forces a re-benchmark so the override reaches a real run", () => {
    let s = generated();
    s = reducer(s, { t: "benchmarkComplete", results: {} });
    expect(s.benchmarkRun).toBe(true);
    s = reducer(s, { t: "override", id: "v1" });
    expect(s.benchmarkRun).toBe(false);
  });
});

describe("gym resume", () => {
  it("re-verifying a gym task overrides the reward with the real verdict", () => {
    const gymData: ReviewData = { ...data, source: "gym", gymReward: 0, gymResume: { seed: 0, urlTrail: [], finalUrl: "" } };
    let s = makeInitialState(gymData);
    s = reducer(s, { t: "gymResumed", reward: 1 });
    expect(s.benchmarkRun).toBe(true);
    expect(reward(s)).toBe(1); // resumed verdict wins over the stale gymReward 0
  });
});

describe("gate chain", () => {
  it("parks on the error step, unapproved", () => {
    const s = makeInitialState(data);
    expect(s.step).toBe(2); // error at index 2
    expect(s.stepsApproved).toBe(false);
    expect(sessionStatus(s)).toBe("draft");
  });

  it("approveRemaining approves and advances status", () => {
    const s = reducer(makeInitialState(data), { t: "approveRemaining" });
    expect(s.stepsApproved).toBe(true);
    expect(sessionStatus(s)).toBe("steps_approved");
  });

  it("generate is gated on approval", () => {
    expect(reducer(makeInitialState(data), { t: "generate" }).verifiersGenerated).toBe(false);
    expect(generated().verifiersGenerated).toBe(true);
  });

  it("benchmarkComplete is gated on generation and stores results", () => {
    expect(reducer(makeInitialState(data), { t: "benchmarkComplete", results: { v1: "pass" } }).benchmarkRun).toBe(false);
    const s = reducer(generated(), { t: "benchmarkComplete", results: { v1: "pass", v2: "pass" } });
    expect(s.benchmarkRun).toBe(true);
    expect(s.results.v1).toBe("pass");
  });
});

describe("correction", () => {
  it("re-locks section 2 entirely (spec §3.25) and forks the trace", () => {
    let s = reducer(generated(), { t: "benchmarkComplete", results: { v1: "pass", v2: "pass" } });
    s = reducer(s, { t: "correctAndRerun", fromStep: 3, branch: null, mode: "deterministic" });
    expect(s.stepsApproved).toBe(false);
    expect(s.verifiersGenerated).toBe(false);
    expect(s.benchmarkRun).toBe(false);
    expect(s.rerunFrom).toBe(3);
  });

  it("uses the agent branch when supplied", () => {
    const branch = [{ idx: 4, type: "click" as const, tabId: "shop", description: "agent step" }];
    const s = reducer(makeInitialState(data), { t: "correctAndRerun", fromStep: 3, branch, mode: "agent" });
    expect(s.rerunMode).toBe("agent");
    const steps = visibleSteps(s);
    expect(steps[steps.length - 1].description).toBe("agent step");
  });
});

describe("verifierState + reward", () => {
  const run = (results: Record<string, string>): ReviewState => ({ ...makeInitialState(data), benchmarkRun: true, results });

  it("is pending before a run", () => {
    expect(verifierState(makeInitialState(data), data.verifiers[0])).toBe("pending");
  });

  it("placeholder never passes", () => {
    const v: Verifier = { id: "x", level: "ui", assertion: "", code: "", placeholder: true };
    expect(verifierState(run({ x: "pass" }), v)).toBe("fail");
  });

  it("reads real server results", () => {
    expect(verifierState(run({ v1: "pass" }), data.verifiers[0])).toBe("pass");
    expect(verifierState(run({ v1: "fail" }), data.verifiers[0])).toBe("fail");
  });

  it("override attests a failing check", () => {
    const s = { ...run({ v1: "fail" }), overrides: { v1: true } };
    expect(verifierState(s, data.verifiers[0])).toBe("pass");
  });

  it("reward is 1 only when every verifier passes", () => {
    expect(reward(run({ v1: "pass", v2: "pass" }))).toBe(1);
    expect(reward(run({ v1: "pass", v2: "fail" }))).toBe(0);
    expect(reward(makeInitialState(data))).toBeNull(); // not run
  });
});

describe("step status (spec §2.3)", () => {
  it("classifies corrected / re-run / verified / pending after a fork", () => {
    const s: ReviewState = { ...makeInitialState(data), rerunFrom: 3, verifiedThrough: 5 };
    expect(stepStatus(s, { idx: 3, type: "error", tabId: "shop", description: "" })).toBe("corrected");
    expect(stepStatus(s, { idx: 4, type: "submit", tabId: "shop", description: "" })).toBe("rerun");
    expect(stepStatus(s, { idx: 2, type: "click", tabId: "shop", description: "" })).toBe("verified");
    const fresh = makeInitialState(data);
    expect(stepStatus(fresh, { idx: 3, type: "error", tabId: "shop", description: "" })).toBe("pending");
  });

  it("resolves overlay state for corrected/re-run steps", () => {
    const s: ReviewState = { ...makeInitialState(data), rerunFrom: 3 };
    expect(isResolved(s, { idx: 4, type: "submit", tabId: "shop", description: "" })).toBe(true);
    expect(isResolved(s, { idx: 2, type: "click", tabId: "shop", description: "" })).toBe(false);
    expect(isVerified({ ...makeInitialState(data), verifiedThrough: 3 }, { idx: 2, type: "click", tabId: "shop", description: "" })).toBe(true);
  });
});

describe("hydrate + persistence projections", () => {
  it("restores the gate chain and results from a persisted session", () => {
    const s = reducer(makeInitialState(data), { t: "hydrate", status: "benchmark_run", rerunFrom: null, results: { v1: "pass", v2: "pass" } });
    expect(s.stepsApproved).toBe(true);
    expect(s.verifiersGenerated).toBe(true);
    expect(s.benchmarkRun).toBe(true);
    expect(reward(s)).toBe(1);
  });

  it("verifierPayloads carries the check IR", () => {
    const withCheck: ReviewData = { ...data, verifiers: [{ id: "v1", level: "ui", assertion: "a", code: "c", check: { kind: "state_true", path: "x" } }] };
    const payloads = verifierPayloads(makeInitialState(withCheck));
    expect(payloads[0].check).toEqual({ kind: "state_true", path: "x" });
  });
});
