import { describe, expect, it } from "vitest";
import {
  allVerifiers,
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
  it("opens at step 1 with nothing reviewed, unapproved", () => {
    const s = makeInitialState(data);
    expect(s.step).toBe(0); // always start at the first step
    expect(s.verifiedThrough).toBe(0);
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

  it("forks at the correction point (not the error) and never overruns the playhead", () => {
    // Correct a LATE step with a SHORT branch — used to crash (step past array end).
    const branch = [{ idx: 2, type: "click" as const, tabId: "shop", description: "b" }];
    const s = reducer(makeInitialState(data), { t: "correctAndRerun", fromStep: 1, branch, mode: "agent" });
    const steps = visibleSteps(s);
    expect(steps.length).toBe(2); // first 1 original step + 1 branch step (fork at rerunFrom, not errorIndex)
    expect(s.step).toBeLessThan(steps.length); // clamped — current is always defined
    expect(steps[s.step]).toBeDefined();
    // idx values stay unique + contiguous (no duplicate React keys)
    expect(steps.map((x) => x.idx)).toEqual([1, 2]);
  });
});

describe("hydrate restores the full persisted state (DB round-trip)", () => {
  it("restores the correction branch, mode, added/edited verifiers, and overrides", () => {
    const branchTail = [{ idx: 4, type: "submit" as const, tabId: "shop", description: "restored branch step" }];
    const added = [{ id: "add-9", level: "safety" as const, assertion: "human", code: "c" }];
    const s = reducer(makeInitialState(data), {
      t: "hydrate",
      status: "benchmark_run",
      rerunFrom: 3,
      reviewedThrough: 4,
      results: { v1: "fail" },
      branchTail,
      rerunMode: "agent",
      added,
      edits: { v1: { assertion: "edited", code: "c1" } },
      overrides: { v1: true },
    });
    // branch restored -> visibleSteps uses the persisted branch, not correctedTail
    const steps = visibleSteps(s);
    expect(steps[steps.length - 1].description).toBe("restored branch step");
    expect(s.rerunMode).toBe("agent");
    // added + edited verifiers restored
    expect(allVerifiers(s).some((v) => v.id === "add-9")).toBe(true);
    expect(allVerifiers(s).find((v) => v.id === "v1")?.assertion).toBe("edited");
    // override restored -> the failing v1 reads as pass (human-attested)
    expect(verifierState(s, allVerifiers(s).find((v) => v.id === "v1")!)).toBe("pass");
    // reviewed count agrees with the restored branch length (no 13/15 desync)
    expect(s.verifiedThrough).toBe(steps.length);
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
    const s = reducer(makeInitialState(data), { t: "hydrate", status: "benchmark_run", rerunFrom: null, reviewedThrough: 0, results: { v1: "pass", v2: "pass" } });
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
