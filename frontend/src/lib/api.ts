import { APP_COLOR } from "./appColors";
import { reviewFixture } from "../fixtures/reviewPayload";
import type { ReviewData, ReviewPayload } from "./types";

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
