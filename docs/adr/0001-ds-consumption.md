# ADR 0001 — How we consume the Deccan Vault Design System

**Status:** accepted · **Date:** 2026-07-20

## Context
The team mandated building on the Deccan Vault Design System. The export gives us
tokens (`tokens/*.css`), a compiled component bundle (`_ds_bundle.js`, exposing
`window.DeccanAIDesignSystem_ffd752`), fonts, and an oxlint adherence config. The
JSX component **sources** were not exported — only the transpiled IIFE.

## Decision
1. **Consume the tokens verbatim** (vendored into `packages/ds` and mirrored into
   `frontend/src/styles/tokens`). Tokens are the source of truth for color, type,
   spacing, radius, shadow, motion.
2. **Re-implement the handful of needed primitives from the documented spec**
   (`FocusBadge`, `Button`, `Tag`, `Meter`, `Icon`) against those tokens — rather
   than loading or extracting `_ds_bundle.js`.

## Why not load the compiled bundle
- It contains **three unconditional top-level `ReactDOM.createRoot(#root/#td-root)`
  mounts** — loading it hijacks the host app and renders the DS demo over our screen.
- The **JSX sources are absent**; extracting primitives from a minified/transpiled
  IIFE is brittle and unreviewable.
- The design itself imports only 4 DS components and **hand-rolls everything else**
  as inline-styled divs, so a small re-implemented primitive set is sufficient and
  higher-fidelity.

## Consequences
- Our primitives live in `frontend/src/ds/`; `packages/ds` + `docs/design-reference`
  remain the untouched reference.
- **Fonts:** self-hosted Inter Display + JetBrains Mono (both SIL OFL 1.1). The
  **Season Mix TRIAL** cut is dropped — its license forbids serving, and no
  component uses `--font-display` (it falls back to Inter Display).
- **Adherence lint:** kept the no-raw-hex and font-allowlist rules (colors always
  via `t.*` → `var(--…)`). Dropped the no-raw-px rule: the design is fixed-pixel with
  many off-scale values and the DS bundle itself fails that rule 112×; enforcing it
  would fight the design rather than aid it.
