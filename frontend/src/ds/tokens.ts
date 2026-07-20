/**
 * Typed references to the Deccan Vault design tokens.
 * Components read colors/spacing/etc. through `t` (CSS `var(--…)` strings)
 * so we never hardcode hex and stay adherence-clean. Values live in
 * src/styles/tokens/*.css (the vendored DS).
 */
export const t = {
  // Primary (blue) — every interactive action
  primary0: "var(--primary-0)",
  primary6: "var(--primary-6)",
  primary7: "var(--primary-7)",
  primary8: "var(--primary-8)",

  // Neutrals: 0=text … 9=white
  n0: "var(--neutrals-0)",
  n1: "var(--neutrals-1)",
  n2: "var(--neutrals-2)",
  n3: "var(--neutrals-3)",
  n4: "var(--neutrals-4)",
  n5: "var(--neutrals-5)",
  n6: "var(--neutrals-6)",
  n7: "var(--neutrals-7)",
  n8: "var(--neutrals-8)",
  n85: "var(--neutrals-85)",
  n9: "var(--neutrals-9)",

  // Semantic accents (base + lite/dark used for chips)
  red: "var(--accent-red)",
  redLite: "var(--accent-red-lite)",
  redDark: "var(--accent-red-dark)",
  green: "var(--accent-green)",
  greenLite: "var(--accent-green-lite)",
  greenDark: "var(--accent-green-dark)",
  yellow: "var(--accent-yellow)",
  yellowDark: "var(--accent-yellow-dark)",
  purple: "var(--accent-purple)",

  // Delta / categorical hues (timeline + tags)
  deltaPink: "var(--delta-pink)",
  deltaCyan: "var(--delta-cyan)",
  deltaViolet: "var(--delta-violet)",
  deltaBlue: "var(--delta-blue)",
  deltaEmerald: "var(--delta-emerald)",
  deltaAmber: "var(--delta-amber)",
  deltaRose: "var(--delta-rose)",
  deltaTagId: "var(--delta-tag-id)",

  // Surfaces / borders / text (semantic aliases)
  surfacePage: "var(--surface-page)",
  surfaceCard: "var(--surface-card)",
  surfaceAlt: "var(--surface-alt)",
  surfaceTint: "var(--surface-tint)",
  borderCard: "var(--border-card)",
  borderHairline: "var(--border-hairline)",
  textPrimary: "var(--text-primary)",
  textSecondary: "var(--text-secondary)",
  textMuted: "var(--text-muted)",

  // Type
  fontPrimary: "var(--font-primary)",
  fontMono: "var(--font-mono)",

  // Spacing / radius / shadows / motion
  radiusSm: "var(--radius-sm)",
  radiusMd: "var(--radius-md)",
  radiusLg: "var(--radius-lg)",
  radiusXl: "var(--radius-xl)",
  radius2xl: "var(--radius-2xl)",
  radiusPill: "var(--radius-pill)",
  radiusFull: "var(--radius-full)",
  shadowSm: "var(--shadow-sm)",
  shadowMd: "var(--shadow-md)",
  shadowLg: "var(--shadow-lg)",
  shadowXl: "var(--shadow-xl)",
  shadowElevated: "var(--shadow-elevated)",
  transitionUi: "var(--transition-ui)",
} as const;

/** Weights — 600 resolves to Bold (700) since SemiBold isn't shipped. */
export const weight = {
  regular: 400,
  medium: 500,
  semibold: 600,
  bold: 700,
  black: 900,
} as const;

/** The 7 agent action types → their categorical hue (matches the design). */
export const ACTION_COLOR = {
  navigate: t.deltaBlue,
  type: t.deltaCyan,
  click: t.deltaViolet,
  submit: t.deltaEmerald,
  extract: t.deltaAmber,
  error: t.deltaRose,
  tab: t.deltaPink,
} as const;
export type ActionType = keyof typeof ACTION_COLOR;

/** The 5 verifier levels → dot hue + the type-chip label shown in the group card. */
export const VERIFIER_LEVEL = {
  ui: { label: "UI State", chip: "DOM", color: t.deltaCyan },
  backend: { label: "Backend State", chip: "SQL", color: t.deltaViolet },
  semantic: { label: "Semantic", chip: "LLM judge", color: t.primary6 },
  process: { label: "Process", chip: "Trace", color: t.deltaAmber },
  safety: { label: "Safety", chip: "Policy", color: t.deltaRose },
} as const;
export type VerifierLevel = keyof typeof VERIFIER_LEVEL;

/**
 * `color-mix` tint used by chips/badges (e.g. a 12%-of-hue fill).
 * A helper so components don't hand-write color-mix strings.
 */
export function tint(color: string, pct: number): string {
  return `color-mix(in srgb, ${color} ${pct}%, transparent)`;
}
