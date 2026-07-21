import type { ActionType, VerifierLevel } from "../ds/tokens";

export type AppKey = "shop" | "market" | "calendar" | "mail";

/** One recorded agent step. */
export interface Step {
  idx: number;
  type: ActionType;
  tabId: string;
  description: string;
  /** captured-snapshot key for this step's page (served at /api/snapshots/{key}). */
  snapshot?: string;
}

export interface Metric {
  value: string;
  label: string;
  tone?: "default" | "error" | "success";
}

/** A verifier check. */
export interface Verifier {
  id: string;
  level: VerifierLevel;
  assertion: string;
  code: string;
  failsUntilCorrected?: boolean;
  placeholder?: boolean;
}

// ---- API shape (returned by the backend) ----------------------------------

export interface ApiTab {
  id: string;
  app: AppKey;
  title: string;
  host: string;
}
export interface ApiSite {
  host: string;
  app: AppKey;
}
export interface ApiTask {
  id: string;
  priority: "High" | "Medium" | "Low";
  title: string;
  meta: string;
  prompt: string;
  startState: { summary: string; url: string };
  constraints: string[];
  allowedSites: ApiSite[];
  runSummary: Metric[];
}
export interface ReviewPayload {
  task: ApiTask;
  tabs: ApiTab[];
  steps: Step[];
  correctionSeed: string;
  correctedTail: Step[];
  verifiers: Verifier[];
}

// ---- Domain shape (API mapped → colors resolved for rendering) ------------

export interface Tab {
  id: string;
  title: string;
  host: string;
  color: string;
}
export interface Task {
  id: string;
  priority: "High" | "Medium" | "Low";
  title: string;
  meta: string;
  prompt: string;
  startState: { summary: string; url: string };
  constraints: string[];
  allowedSites: { host: string; color: string }[];
  runSummary: Metric[];
}
export interface ReviewData {
  task: Task;
  tabs: Tab[];
  steps: Step[];
  correctionSeed: string;
  correctedTail: Step[];
  verifiers: Verifier[];
}

/** Review-flow state machine (mirrors the design's linear gate chain). */
export interface ReviewState {
  data: ReviewData;
  step: number;
  activeTabId: string;
  playing: boolean;
  verifiedThrough: number;
  stepsApproved: boolean;
  verifiersGenerated: boolean;
  benchmarkRun: boolean;
  submitted: boolean;
  rerunFrom: number | null;
  overrides: Record<string, boolean>;
  activeLevel: VerifierLevel;
  added: Verifier[];
  /** in-place edits to any verifier (generated or added), keyed by id. */
  edits: Record<string, { assertion: string; code: string }>;
}
