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

/** Resume (or create) this annotator's session for a task. */
export function openSession(taskId: string): Promise<SessionSnapshot | null> {
  return post<SessionSnapshot>(`/api/tasks/${encodeURIComponent(taskId)}/sessions`, {});
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
