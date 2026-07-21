import { APP_COLOR } from "./appColors";
import { reviewFixture } from "../fixtures/reviewPayload";
import type { ReviewData, ReviewPayload, Step, TaskListItem } from "./types";

/** The task queue (falls back to a single synthetic row offline). */
export async function fetchTasks(): Promise<TaskListItem[]> {
  try {
    const res = await fetch("/api/tasks");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const list = (await res.json()) as TaskListItem[];
    return list.length ? list : fallbackTasks();
  } catch {
    return fallbackTasks();
  }
}

function fallbackTasks(): TaskListItem[] {
  const t = reviewFixture.task;
  return [{ id: t.id, title: t.title, priority: t.priority, meta: t.meta, index: 0, total: 1 }];
}

export type SessionStatus =
  | "draft"
  | "steps_approved"
  | "verifiers_generated"
  | "benchmark_run"
  | "submitted";

export interface SessionSnapshot {
  sessionId: string;
  taskExternalId: string;
  status: SessionStatus;
  rerunFrom: number | null;
  suite: { suiteId: string; version: number; verifiers: unknown[] } | null;
  lastBenchmark: { reward: number; results: Record<string, unknown>; at: string } | null;
  submission: { reward: number; kind: string; override: boolean; at: string } | null;
}

/** A persisted-verifier payload for the suite-save endpoint. */
export interface VerifierPayload {
  id: string;
  level: string;
  assertion: string;
  code: string;
  check?: unknown; // executable IR — persisted so the server recomputes reward authoritatively
  failsUntilCorrected: boolean;
  placeholder: boolean;
  addedByHuman: boolean;
}

/** Resolve app keys → colors so the render layer stays token-driven. */
function mapPayload(p: ReviewPayload): ReviewData {
  return {
    task: {
      ...p.task,
      allowedSites: p.task.allowedSites.map((s) => ({ host: s.host, color: APP_COLOR[s.app] })),
    },
    tabs: p.tabs.map((tb) => ({ id: tb.id, title: tb.title, host: tb.host, color: APP_COLOR[tb.app] })),
    steps: p.steps,
    correctionSeed: p.correctionSeed,
    correctedTail: p.correctedTail,
    verifiers: p.verifiers,
    source: p.source ?? "fixture",
    gymReward: p.gymReward,
    gymResume: p.gymResume,
  };
}

export interface LoadResult {
  data: ReviewData;
  source: "api" | "fallback";
}

/** Fetch a task's review payload from the backend; fall back to the bundled
 *  fixture if the API is unreachable (so the app runs standalone). */
export async function fetchReview(taskId: string): Promise<LoadResult> {
  try {
    const res = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/review`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = (await res.json()) as ReviewPayload;
    return { data: mapPayload(payload), source: "api" };
  } catch {
    return { data: mapPayload(reviewFixture), source: "fallback" };
  }
}

// ---- session persistence (M4) ---------------------------------------------
// Every call is best-effort: if the backend is down the app still runs from
// memory (offline fixture mode), it just won't persist.

async function post<T>(url: string, body: unknown): Promise<T | null> {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function send(url: string, method: "PATCH" | "PUT", body: unknown): Promise<void> {
  try {
    await fetch(url, {
      method,
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    /* offline — ignore */
  }
}

/** Resume (or create) this annotator's session for a task. `fresh` forces a new
 *  session — used to re-annotate a task whose latest session is submitted. */
export function openSession(taskId: string, opts?: { fresh?: boolean }): Promise<SessionSnapshot | null> {
  return post<SessionSnapshot>(`/api/tasks/${encodeURIComponent(taskId)}/sessions`, { fresh: opts?.fresh ?? false });
}

export function patchSession(
  sid: string,
  patch: { status?: SessionStatus; rerunFrom?: number },
): Promise<void> {
  return send(`/api/sessions/${sid}`, "PATCH", patch);
}

export function saveSuite(sid: string, verifiers: VerifierPayload[]): Promise<void> {
  return send(`/api/sessions/${sid}/suite`, "PUT", { verifiers });
}

export interface RunResult {
  results: Record<string, string>;
  reward: number;
  executed: number;
  overridden: number;
}

/** Execute the verifier suite server-side against the real DOM + state + trace. */
export function runVerifiers(
  sid: string,
  body: { corrected: boolean; verifiers: unknown[]; overrides: string[] },
): Promise<RunResult | null> {
  return post<RunResult>(`/api/sessions/${sid}/run`, body);
}

/** Re-run from a corrected step — persists an immutable branch, returns its steps. */
export function rerunTrajectory(
  sid: string,
  body: { fromStep: number; correction: string; mode?: string },
): Promise<{ fromStep: number; mode: string; steps: Step[] } | null> {
  return post<{ fromStep: number; mode: string; steps: Step[] }>(`/api/sessions/${sid}/rerun`, body);
}

export function submitSession(
  sid: string,
  body: { reward: number; override: boolean; overrideReason?: string; kind?: string },
): Promise<SessionSnapshot | null> {
  return post<SessionSnapshot>(`/api/sessions/${sid}/submit`, body);
}

// ---- real gym tasks (M8) ---------------------------------------------------

export interface GymTaskItem { id: string; category?: string; difficulty?: string }

export interface GymStatus { connected: boolean; url: string }

/** Whether a live gym is reachable. In a hosted deploy with no GYM_URL this is
 *  false, and the UI gates the 312-task features while the fixture flow works. */
export async function fetchGymStatus(): Promise<GymStatus> {
  try {
    const res = await fetch("/api/gym/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as GymStatus;
  } catch {
    return { connected: false, url: "" };
  }
}

/** The catalog of real gym tasks (312), or null if the gym is unreachable. */
export async function fetchGymTasks(): Promise<GymTaskItem[] | null> {
  try {
    const res = await fetch("/api/gym/tasks");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = (await res.json()) as { tasks: string[] };
    return body.tasks.map((id) => ({ id }));
  } catch {
    return null;
  }
}

export interface GymJob {
  jobId: string;
  status: "queued" | "running" | "done" | "error";
  review?: ReviewPayload;
  error?: string;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export interface ResumeResult { score: number; success: boolean; reward: number }

/** Drive-forward resume (async): load the corrected world (+ edits) and drive a
 *  LIVE agent FORWARD from the mid-episode URL in the gym, then verify. Slow +
 *  (for LLM agents) stochastic. Submits to the job queue and polls to the driven
 *  verdict. onStatus fires on each phase change. */
export async function driveForwardGym(
  body: {
    taskId: string;
    seed: number;
    worldState?: Record<string, unknown>;
    edits?: Record<string, unknown>;
    resumeUrl: string;
    resumeStep?: number;
    agent?: string;
  },
  opts?: { onStatus?: (s: GymJob["status"]) => void; intervalMs?: number; timeoutMs?: number },
): Promise<{ reward: number } | null> {
  const out = await post<{ jobId: string }>("/api/gym/resume-run", body);
  const jobId = out?.jobId;
  if (!jobId) return null;
  const interval = opts?.intervalMs ?? 2000;
  const deadline = Date.now() + (opts?.timeoutMs ?? 320_000);
  let last: GymJob["status"] | null = null;
  while (Date.now() < deadline) {
    await sleep(interval);
    const j = await pollGymJob(jobId);
    if (!j) continue;
    if (j.status !== last) { last = j.status; opts?.onStatus?.(j.status); }
    if (j.status === "done") return { reward: (j.review as { gymReward?: number } | undefined)?.gymReward ?? 0 };
    if (j.status === "error") return null;
  }
  return null;
}

/** Resume a gym task from its corrected state: load the captured world (+ optional
 *  dot-path edits) into the gym and replay the trajectory → REAL milestone verdict. */
export async function resumeGymReview(body: {
  taskId: string;
  seed: number;
  worldState?: Record<string, unknown>;
  urlTrail: string[];
  finalUrl: string;
  edits?: Record<string, unknown>;
}): Promise<ResumeResult | null> {
  return post<ResumeResult>("/api/gym/resume", body);
}

/** Enqueue a real gym run; returns the jobId to poll, or null if unreachable. */
export async function startGymReview(taskId: string, agent = "oracle", seed = 0): Promise<string | null> {
  const out = await post<{ jobId: string }>(`/api/gym/tasks/${taskId}/run-review`, { agent, seed });
  return out?.jobId ?? null;
}

/** One poll of a gym job. */
export async function pollGymJob(jobId: string): Promise<GymJob | null> {
  try {
    const res = await fetch(`/api/gym/jobs/${encodeURIComponent(jobId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as GymJob;
  } catch {
    return null;
  }
}

/** Start a real gym run and poll to completion (the run is now OFF the request
 *  path, so a slow browser run can't time out the POST). onStatus fires on each
 *  phase change for the loading UI. */
export async function runGymReview(
  taskId: string,
  agent = "oracle",
  seed = 0,
  opts?: { onStatus?: (s: GymJob["status"]) => void; intervalMs?: number; timeoutMs?: number },
): Promise<ReviewData | null> {
  const jobId = await startGymReview(taskId, agent, seed);
  if (!jobId) return null;
  const interval = opts?.intervalMs ?? 1500;
  const deadline = Date.now() + (opts?.timeoutMs ?? 300_000);
  let last: GymJob["status"] | null = null;
  while (Date.now() < deadline) {
    await sleep(interval);
    const j = await pollGymJob(jobId);
    if (!j) continue; // transient blip — keep polling
    if (j.status !== last) { last = j.status; opts?.onStatus?.(j.status); }
    if (j.status === "done") return j.review ? mapPayload(j.review) : null;
    if (j.status === "error") return null;
  }
  return null; // client-side timeout guard
}
