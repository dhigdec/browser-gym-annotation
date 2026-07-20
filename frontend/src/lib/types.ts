import type { ActionType, VerifierLevel } from "../ds/tokens";

/** A browser tab in the replay pane — one of our gym apps. */
export interface Tab {
  id: string;
  title: string; // e.g. "ShopGym"
  host: string; // e.g. "shop.gym.local/cart"
  color: string; // token var — dot + active border
}

/** One recorded agent step in the action trace. */
export interface Step {
  idx: number; // 1-based display index
  type: ActionType;
  tabId: string; // which app/tab it happened on
  description: string;
}

export interface Metric {
  value: string;
  label: string;
  tone?: "default" | "error" | "success";
}

export interface Task {
  id: string; // "GYM-2041"
  priority: "High" | "Medium" | "Low";
  title: string;
  meta: string; // "E-commerce · Multi-tab · nav-agent-v4"
  prompt: string;
  startState: { summary: string; url: string };
  constraints: string[];
  allowedSites: { host: string; color: string }[];
  runSummary: Metric[];
}

/** A single verifier check within a level group. */
export interface Verifier {
  id: string;
  level: VerifierLevel;
  assertion: string; // plain-English title
  code: string; // the mono assertion line
  /** true => this check scores 0 until the trace is corrected + re-run. */
  failsUntilCorrected?: boolean;
  /** true => empty/placeholder check (scores 0/error, never 1). */
  placeholder?: boolean;
}

/** Review-flow state machine (mirrors the design's linear gate chain). */
export interface ReviewState {
  step: number; // 0-based current step in the scrubber
  activeTabId: string;
  playing: boolean;
  verifiedThrough: number; // count of steps marked verified
  stepsApproved: boolean;
  verifiersGenerated: boolean;
  benchmarkRun: boolean;
  submitted: boolean;
  /** step index the trace was corrected from (fork), or null. */
  rerunFrom: number | null;
  /** verifier ids the reviewer force-overrode to pass. */
  overrides: Record<string, boolean>;
  activeLevel: VerifierLevel;
  /** extra verifiers the reviewer added, per level. */
  added: Verifier[];
}
