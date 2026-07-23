import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyVerdict,
  buildLineage,
  continuingAfter,
  createFork,
  DECIDED_ELSEWHERE,
  FORK_COPY,
  MOVED_ON,
  rejecting,
  selectHeadOrReload,
  setStatusOrReload,
  startAgentRun,
  withVerdicts,
  type VersionGraphData,
  type VersionNode,
  type VersionStep,
} from "../../lib/versionsApi";
import { VersionGraph } from "./VersionGraph";
import { VersionSteps } from "./VersionSteps";

// --------------------------------------------------------------------------- harness
interface Call {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
}

/** Records every request and answers from `reply`, so a test can assert what the
 *  client did NOT send as easily as what it did. */
function stubFetch(reply: (call: Call) => { status: number; body?: unknown }): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const call: Call = {
      url: String(url),
      method: init?.method ?? "GET",
      body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null,
    };
    calls.push(call);
    const { status, body } = reply(call);
    return { ok: status >= 200 && status < 300, status, json: async () => body ?? {} } as Response;
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const version = (over: Partial<VersionNode> & { id: string; versionNo: number }): VersionNode => ({
  parentId: null,
  kind: "agent_correction",
  status: "candidate",
  revision: 0,
  producer: "",
  forkBeforeStepId: null,
  forkCheckpointId: null,
  isHead: false,
  stepCount: 0,
  createdAt: "2026-07-23T00:00:00",
  ...over,
});

const step = (over: Partial<VersionStep> & { stepId: string; displayIdx: number }): VersionStep => ({
  versionId: "V1",
  inherited: false,
  actor: "agent",
  type: "click",
  description: "click something",
  url: "",
  image: "",
  reasoning: "",
  humanIntent: "",
  guidance: "",
  verdict: "pending",
  ...over,
});

const graph = (over: Partial<VersionGraphData> = {}): VersionGraphData => ({
  attemptId: "A",
  revision: 4,
  headVersionId: "V1",
  agentCallCount: 1,
  versions: [
    version({ id: "V1", versionNo: 1, kind: "agent_run", isHead: true, stepCount: 3, producer: "gpt-5.5" }),
    version({ id: "V2", versionNo: 2, parentId: "V1", stepCount: 5 }),
  ],
  verdicts: {},
  ...over,
});

// --------------------------------------------------------------------------- stale revisions
describe("a lost compare-and-swap", () => {
  it("reloads the lineage instead of resending the write", async () => {
    // Two annotators on one attempt: ours read revision 4, theirs already moved
    // it to 5. Resending with 5 would overwrite a decision we never saw.
    const calls = stubFetch((c) =>
      c.method === "POST"
        ? { status: 409, body: { detail: "the attempt moved on; reload before selecting a version" } }
        : { status: 200, body: graph({ revision: 5, headVersionId: "V2" }) },
    );

    const out = await selectHeadOrReload("S1", "V2", 4);

    expect(out.ok).toBe(false);
    expect(out.notice).toBe(MOVED_ON);
    expect(out.reloaded?.revision, "the caller must render the revision it just re-read").toBe(5);
    expect(calls.map((c) => c.method)).toEqual(["POST", "GET"]);
    expect(calls.filter((c) => c.method === "POST"), "a silent retry is the clobber we are guarding against").toHaveLength(1);
  });

  it("carries the same rule into a QC status change", async () => {
    const calls = stubFetch((c) => (c.method === "POST" ? { status: 409, body: { detail: "decided by someone else" } } : { status: 200, body: graph() }));

    const out = await setStatusOrReload("S1", "V2", "approved", 0);

    expect(out.ok).toBe(false);
    expect(out.notice).toBe(DECIDED_ELSEWHERE);
    expect(out.reloaded).not.toBeNull();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });

  it("selects against the ATTEMPT revision, not the version's", async () => {
    // They are separate counters; mixing them 409s on every second call for no
    // reason and trains the annotator to ignore the banner.
    const calls = stubFetch(() => ({ status: 200, body: { headVersionId: "V2", revision: 5 } }));
    await selectHeadOrReload("S1", "V2", graph().revision);
    expect(calls[0].body).toEqual({ versionId: "V2", expectedRevision: 4 });
  });

  it("does not blame another annotator when the server is simply unreachable", async () => {
    // An offline blip must not claim somebody moved the attempt, and must not
    // trigger a reload that would also fail.
    const calls = stubFetch(() => {
      throw new Error("network down");
    });

    const out = await selectHeadOrReload("S1", "V2", 4);

    expect(out.notice).not.toBe(MOVED_ON);
    expect(out.reloaded).toBeNull();
    expect(calls).toHaveLength(1);
  });

  it("surfaces the server's own words for a conflict that is not a stale revision", async () => {
    const out = await (async () => {
      stubFetch(() => ({ status: 409, body: { detail: "the fork step is not in the parent's chain" } }));
      return createFork("S1", rejecting("V1", "STEP-9"));
    })();
    expect(out.ok).toBe(false);
    if (!out.ok) {
      expect(out.kind).toBe("conflict");
      expect(out.message).toBe("the fork step is not in the parent's chain");
    }
  });
});

// --------------------------------------------------------------------------- fork semantics
describe("fork before vs continue after", () => {
  it("rejecting a step forks BEFORE it, so the bad action cannot reach the child", async () => {
    const calls = stubFetch(() => ({ status: 200, body: version({ id: "V3", versionNo: 3 }) }));
    await createFork("S1", rejecting("V1", "STEP-7"));
    expect(calls[0].body).toEqual({ parentVersionId: "V1", stepId: "STEP-7", mode: "before" });
  });

  it("continuing after a step keeps it", async () => {
    const calls = stubFetch(() => ({ status: 200, body: version({ id: "V3", versionNo: 3 }) }));
    await createFork("S1", continuingAfter("V1", "STEP-7"));
    expect(calls[0].body).toEqual({ parentVersionId: "V1", stepId: "STEP-7", mode: "after" });
  });

  it("the two modes are described as different operations, not as a setting", () => {
    expect(FORK_COPY.before.action).not.toBe(FORK_COPY.after.action);
    expect(FORK_COPY.before.hint).toMatch(/will not appear/i);
    expect(FORK_COPY.after.hint).toMatch(/keeps this step/i);
  });

  it("offers both as separately worded commands on the step row", () => {
    // One control with a before/after toggle is exactly how a rejected action
    // ends up kept in a golden trajectory — the row must never present one.
    const html = renderToStaticMarkup(
      <VersionSteps
        version={version({ id: "V1", versionNo: 1, isHead: true })}
        steps={[step({ stepId: "S-1", displayIdx: 0 })]}
        selectedStepId="S-1"
        onSelectStep={() => {}}
        onVerdict={() => {}}
        onRejectStep={() => {}}
        onContinueAfter={() => {}}
      />,
    );
    expect(html).toContain(FORK_COPY.before.action);
    expect(html).toContain(FORK_COPY.after.action);
    expect(html).toContain(FORK_COPY.before.hint);
    expect(html).toContain(FORK_COPY.after.hint);
  });

  it("hands the agent the same fork point the human would have taken", async () => {
    const calls = stubFetch(() => ({ status: 200, body: { jobId: "J", versionId: "V4", status: "queued" } }));
    await startAgentRun("S1", rejecting("V1", "STEP-7"), { correction: "use the returns flow" });
    expect(calls[0].body).toMatchObject({ parentVersionId: "V1", stepId: "STEP-7", mode: "before", correction: "use the returns flow" });
  });
});

// --------------------------------------------------------------------------- candidates
describe("an agent run produces a candidate", () => {
  it("never selects a head on the annotator's behalf", async () => {
    const calls = stubFetch(() => ({ status: 200, body: { jobId: "J", runId: "R", versionId: "V4", status: "queued" } }));

    await startAgentRun("S1", continuingAfter("V1", "STEP-7"));

    expect(calls).toHaveLength(1);
    expect(calls.some((c) => c.url.includes("/versions/select")), "a run that selects itself resurrects branches the annotator moved past").toBe(false);
  });

  it("reports the run cap as its own outcome rather than a generic failure", async () => {
    stubFetch(() => ({ status: 429, body: { detail: "this attempt is out of agent runs" } }));
    const res = await startAgentRun("S1", rejecting("V1", "STEP-7"));
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.kind).toBe("capped");
  });

  it("renders a finished candidate as something still to be chosen", () => {
    const html = renderToStaticMarkup(
      <VersionGraph
        graph={graph()}
        viewingId="V2"
        notice={null}
        onView={() => {}}
        onSelectHead={() => {}}
        onSetStatus={() => {}}
        onDismissNotice={() => {}}
      />,
    );
    expect(html).toContain("not the answer until you select it");
    expect(html).toContain("Make v2 the head");
  });
});

// --------------------------------------------------------------------------- head legibility
describe("the head version", () => {
  it("is badged once and is never offered as something to select again", () => {
    const html = renderToStaticMarkup(
      <VersionGraph
        graph={graph()}
        viewingId="V2"
        notice={null}
        onView={() => {}}
        onSelectHead={() => {}}
        onSetStatus={() => {}}
        onDismissNotice={() => {}}
      />,
    );
    expect(html.match(/>HEAD</g) ?? []).toHaveLength(1);
    expect(html).toContain("current answer."); // the apostrophe is HTML-escaped
    expect(html).not.toContain("Make v1 the head");
  });

  it("still offers QC on the head, because finalize refuses an unapproved version", () => {
    const html = renderToStaticMarkup(
      <VersionGraph
        graph={graph({ versions: [version({ id: "V1", versionNo: 1, kind: "agent_run", isHead: true })] })}
        viewingId="V1"
        notice={null}
        onView={() => {}}
        onSelectHead={() => {}}
        onSetStatus={() => {}}
        onDismissNotice={() => {}}
      />,
    );
    expect(html).toContain("Approve");
  });

  it("shows the stale-revision notice in the panel rather than swallowing it", () => {
    const html = renderToStaticMarkup(
      <VersionGraph
        graph={graph()}
        viewingId="V2"
        notice={MOVED_ON}
        onView={() => {}}
        onSelectHead={() => {}}
        onSetStatus={() => {}}
        onDismissNotice={() => {}}
      />,
    );
    expect(html).toContain("moved on while you were looking at it");
  });
});

// --------------------------------------------------------------------------- lineage shape
describe("lineage ordering", () => {
  it("puts every child under its parent, siblings in version order", () => {
    const rows = buildLineage([
      version({ id: "V3", versionNo: 3, parentId: "V1" }),
      version({ id: "V1", versionNo: 1 }),
      version({ id: "V4", versionNo: 4, parentId: "V2" }),
      version({ id: "V2", versionNo: 2, parentId: "V1" }),
    ]);
    expect(rows.map((r) => r.version.versionNo)).toEqual([1, 2, 4, 3]);
    expect(rows.map((r) => r.depth)).toEqual([0, 1, 2, 1]);
    expect(rows[1].isLast, "v2 has a later sibling (v3), so the rail draws a tee").toBe(false);
    expect(rows[3].isLast).toBe(true);
  });

  it("still renders a version whose parent is missing from the payload", () => {
    // Hiding it would show the annotator fewer branches than the attempt has,
    // and they cannot reason about a lineage that is quietly incomplete.
    const rows = buildLineage([version({ id: "V9", versionNo: 9, parentId: "GONE" })]);
    expect(rows.map((r) => r.version.id)).toEqual(["V9"]);
    expect(rows[0].depth).toBe(0);
  });
});

// --------------------------------------------------------------------------- inherited steps
describe("inherited steps", () => {
  const parentSteps = [
    step({ stepId: "S-1", displayIdx: 0, versionId: "V1" }),
    step({ stepId: "S-2", displayIdx: 1, versionId: "V1" }),
  ];
  const childSteps = [
    step({ stepId: "S-1", displayIdx: 0, versionId: "V1", inherited: true }),
    step({ stepId: "S-2", displayIdx: 1, versionId: "V1", inherited: true }),
    step({ stepId: "S-7", displayIdx: 2, versionId: "V2" }),
  ];

  it("carries a verdict into every branch that keeps the step", () => {
    // The verdict map is attempt-wide and keyed by the step's stable id, so
    // reviewing the prefix once is enough — this is the point of the design.
    const verdicts = { "S-2": { verdict: "verified" as const, note: "" } };
    const inParent = withVerdicts(parentSteps, verdicts);
    const inChild = withVerdicts(childSteps, verdicts);
    expect(inParent[1].verdict).toBe("verified");
    expect(inChild[1].verdict).toBe("verified");
    expect(inChild[2].verdict, "the child's own new step starts unreviewed").toBe("pending");
  });

  it("updates by step id, not by row position", () => {
    const updated = applyVerdict(childSteps, "S-7", "rejected");
    expect(updated[2].verdict).toBe("rejected");
    expect(updated.filter((s) => s.verdict === "rejected")).toHaveLength(1);
  });

  it("labels an inherited row with the version it is shared with", () => {
    const html = renderToStaticMarkup(
      <VersionSteps
        version={version({ id: "V2", versionNo: 2 })}
        steps={childSteps}
        versionNos={{ V1: 1, V2: 2 }}
        selectedStepId={null}
        onSelectStep={() => {}}
        onVerdict={() => {}}
        onRejectStep={() => {}}
        onContinueAfter={() => {}}
      />,
    );
    expect(html).toContain("inherited · v1");
    expect(html.match(/inherited · v1/g) ?? [], "both shared rows are marked, not just the first").toHaveLength(2);
    expect(html).toContain("follows that step into every branch");
  });
});
