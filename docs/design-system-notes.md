# Deccan AI Design System — Rebuild & Adherence Analysis

Root: `/Users/dhiren/Downloads/Multitab browser gym platform/_ds/deccan-vault-design-system-ffd7528b-75b6-42e1-b745-aee0a280af96`

**What actually ships (17 files, 2.2 MB):** `readme.md`, `styles.css`, `_ds_manifest.json`, `_adherence.oxlintrc.json`, `_ds_bundle.js` (371 KB), `tokens/*.css` (7 files), `assets/fonts/*.ttf` (5 files).

**What the readme documents but is NOT in the export:** `components/**/*.jsx` sources, `.d.ts` files, `.prompt.md` usage docs, `guidelines/cards/`, `ui_kits/` HTML, `assets/logo/` (the three wordmark SVGs), `assets/icons/`, `index.js`, `SKILL.md`. Only the compiled bundle + tokens exist. Plan the rebuild against the bundle, not the readme's file tree.

---

## 1 · How to consume it in a real app

### The two entry points

```html
<!-- 1. Styles: single entry, imports-only -->
<link rel="stylesheet" href="styles.css">

<!-- 2. React + ReactDOM MUST be globals BEFORE the bundle -->
<script src="react.production.min.js"></script>
<script src="react-dom.production.min.js"></script>

<!-- 3. Components -->
<script src="_ds_bundle.js"></script>
<script type="text/babel">
  const { Button, Table, Badge, Tag, Drawer } = window.DeccanAIDesignSystem_ffd752;
</script>
```

`styles.css` is 597 bytes and contains **zero rules** — it is seven `@import url("tokens/*.css")` lines in fixed order (fonts → colors → typography → spacing → radius → shadows → effects). It defines only `:root` custom properties plus five `@font-face` blocks. **There is no reset, no base/element styling, no `body` defaults, no utility classes.** Everything visual comes from either the JS components' inline styles or CSS you write yourself against the tokens.

### The bundle: format, globals, and its landmines

- **Namespace:** `window.DeccanAIDesignSystem_ffd752` (the `ffd752` suffix is the first 6 chars of the project UUID). Not UMD, not ESM, no `module.exports` — a bare IIFE that assigns onto `window`.
- **Components are React** — plain function components, Babel-transpiled to `React.createElement` (992 call sites). They reference a **bare global `React`** (and `ReactDOM` for portals). React is *not* bundled and *not* `require`d. **If `window.React` is undefined at script-eval time, every component silently fails** — each file is wrapped in `try { … } catch (e) { __ds_ns.__errors.push({path, error}) }`, so failures are swallowed into `window.DeccanAIDesignSystem_ffd752.__errors`. **Check that array during bring-up.**
- **React version floor:** `Input` uses `React.useId()` → **React ≥ 18**. Portals + `createRoot` also imply 18+.
- **Styling model:** 100% **inline style objects** referencing `var(--token)`. No CSS classes, no `className` API on any component, no CSS-in-JS runtime. This means components are unstyleable except via the `style` prop (which shallow-merges last and therefore wins).

**Three side-effectful top-level mounts are baked into the bundle:**

| Line | Call |
|---|---|
| 2585 | `ReactDOM.createRoot(document.getElementById("root")).render(<App/>)` |
| 3387 | `ReactDOM.createRoot(document.getElementById("root")).render(<DatasetDetail/>)` |
| 8213 | `ReactDOM.createRoot(document.getElementById("td-root")).render(<DirectionD .../>)` |

If your host app has a `#root` div (nearly every React app does), **loading `_ds_bundle.js` will hijack it** — twice, the second overwriting the first — and render the Deccan dataset-explorer demo over your app. The DS's own authors hit this: a comment inside `task-detail-parts.jsx` reads *"The compiled bundle has side-effectful mounts and load-order fragility that broke the standalone export."* Their fix was to inline a private copy of `Badge` and drop the bundle dependency entirely.

**Additional global pollution:** five `Object.assign(window, {...})` calls dump ~40 unnamespaced identifiers onto `window` (`RichHtml`, `RatingPill`, `TagChip`, `Badge`, `TopBar`, `DirectionA/B/C/D`, `DesignCanvas`, …). Note a bare `window.Badge` that is a *different* implementation from `DeccanAIDesignSystem_ffd752.Badge`. Also `window.DRA_DATASET` and `window.TASK_L12`.

**Undeclared external runtime deps:**
- `window.renderMathInElement` + `window.KATEX_OPTS` — **KaTeX auto-render**, used by `RichHtml`. Guarded (`if (window.renderMathInElement)`), so absence degrades to raw `$…$` text rather than crashing.
- `https://fonts.googleapis.com/css2?family=JetBrains+Mono` — `@import` at the top of `tokens/fonts.css`.
- `https://digpbmme8jwkp.cloudfront.net/Images/.../l12_vdag.png` — a hardcoded CloudFront image in the task-detail data.

> **Recommendation for an exact rebuild:** do **not** `<script src>` the whole bundle. Extract the 21 primitives (they're ~2–4 KB each, cleanly delimited by `// components/<group>/<Name>.jsx` comments) into your own module, or load the bundle in a sandboxed context. The demo-app segments (`ui_kits/**`, `argo-report/**`, `task-detail/**` = ~85% of the file) are the fragile part.

---

## 2 · Component inventory — all 21

Namespace exports, verified against `_ds_manifest.json` and the bundle's tail assignments.

### Data display (6)
| Component | Purpose | Key props | Task Review |
|---|---|---|---|
| **Table** | The workhorse. `--neutrals-85` header, uppercase 13px/600 `--neutrals-3` headers w/ 0.4px tracking, hairline `--neutrals-7` row rules, `--radius-lg` frame w/ `--shadow-md`, `tableLayout: fixed`, cells `0.875rem 1rem`, row hover = `color-mix(in srgb, var(--primary-6) 4%, var(--neutrals-9))` | `columns[{key,header,render,align,width}]`, `data`, `rowKey`, `onRowClick`, `emptyText`, `headerStyle`, `cellStyle` | ✅ **core** |
| **Tag** | Removable filter/keyword chip. `--neutrals-8` fill, `--radius-sm` (4px), optional 7px leading color dot for categorical/delta tagging, optional `×` | `color`, `onRemove` | ✅ data tags |
| **Meter** | Compact score/progress bar — **built for exactly this screen** (docstring: *"rubric scores (0–3) and verifier pass rates"*). 6px-tall pill track on `--neutrals-7`. Auto threshold color: ≥0.67 green, ≥0.34 yellow, else red. Value label renders in `--font-mono`. | `value`, `max`, `label`, `valueLabel`, `color`, `thresholds{low,mid}`, `width` (default 120) | ✅ **core** |
| **Card** | White surface, `--radius-xl` (12px), `--border-card`, `--shadow-md`. `interactive` → hover `--primary-6` border + `--shadow-lg`. `selected` → `--shadow-elevated`. Default padding `1.5rem 1.25rem`. | `interactive`, `selected`, `padding`, `onClick` | ✅ panels |
| **CardTitle** | Optional title row: `--text-card-title` / `--weight-bold` / `--neutrals-0`, 0.5rem bottom margin | — | ✅ |
| **Avatar** | Circular identity chip. Image when `src`, else initials on a **deterministic delta-palette tint** hashed from the name (palette: delta-blue, delta-violet, delta-cyan, delta-emerald, delta-pink, accent-purple). Font size = `max(10, size × 0.4)`. | `name`, `src`, `size` (32) | ✅ reviewer identity |

### Feedback (5)
| Component | Purpose | Key props | Task Review |
|---|---|---|---|
| **Badge** | Pill status chip, 7 variants → status token pairs. `tag` variant = `--delta-tag-id` bg + mono + `--neutrals-6` border (the ID-tag treatment). `dot` adds a 6px `currentColor` dot. | `variant: success\|warning\|error\|info\|neutral\|primary\|tag`, `dot` | ✅ **core** |
| **FocusBadge** | Page-level context flag. `--text-focus-badge` (18.4px), `--primary-7` text, 12% primary-7 tint bg, **2px** `--primary-7` border, `--radius-xl`, padding `4px 16px` | `children` only | ✅ active task |
| **AlertBanner** | Inline status message; variant tints bg/border/text + accent stripe | `variant: error\|success\|warning\|info`, `title`, `icon`, `onDismiss` | ✅ |
| **Toast** | Transient card. White, `--shadow-xl`, **3px left accent stripe** by variant (info = `--primary-6`, not accent-blue), min 280 / max 420px | `variant: success\|warning\|error\|info`, `title`, `onDismiss` | ✅ |
| **Tooltip** | Dark-neutral hover/focus bubble, `--radius-md`, rendered via `ReactDOM.createPortal`. Wraps one trigger child. | `content`, `placement: top\|bottom\|left\|right` | ✅ metric defs |

### Forms (7)
| Component | Notes |
|---|---|
| **Button** | `primary` (6→7 on hover) / `secondary` (white→`--neutrals-85`, `--accent-blue-lite` border) / `ghost` / `destructive` (`--accent-red`→`--accent-red-dark`). Sizes: `sm` 32px·13px, `md` 40px·`--text-button`, `lg` 48px·16px. Pressed → `translateY(1px)`. |
| **IconButton** | 32px square (`--icon-button-size`), `--radius-md`, `ghost`\|`solid`, press → `scale(0.95)` |
| **Input** | `--radius-lg`, rest border `--accent-blue-lite`, focus `2px solid var(--primary-6)` + 1px offset, error `--accent-red` + `--shadow-error` glow on focus. Uses `React.useId()`. Note the extra `containerStyle` prop. |
| **Select** | Styled native `<select>` w/ custom chevron; takes `options[{value,label}]` |
| **Checkbox** | Checked fills `--primary-6`, 4px radius box |
| **Radio** | `--primary-6` dot in a ring; group via shared `name` |
| **Switch** | On → `--primary-6`, thumb `translateX(19px)` |

### Navigation (1)
**Tabs** — underlined bar; active = `--primary-6` text + 2px underline, track carries `--shadow-inset`. Controlled (`value`) or uncontrolled (`defaultValue`). Items: `{value, label, count, disabled}`; `count` renders as a pill (active: 12% primary tint).

### Overlay (2)
**Dialog** — centered modal over `--overlay-backdrop`, `--radius-2xl`, `--shadow-xl`, default width 480, Esc/backdrop close.
**Drawer** — right-anchored, default width **800** (`--drawer-max-width`), `maxWidth: 100%`, slides `transform 0.3s ease`, backdrop `opacity 0.3s ease`, `zIndex: 1000`, Esc closes, header 20px/24px padding + 18px/700 title. ✅ **core for Task Review detail panes.**

### 🎯 A Task Review screen already exists in the bundle

`ui_kits/dataset-explorer/task-detail/` — ~220 KB across 6 files, and the adherence config's `no-restricted-imports` explicitly names `ui_kits/dataset-explorer/task-detail/**`. **Read these before rebuilding; they are the reference implementation.**

- `task-detail-parts.jsx` — shared atoms: `RatingPill`, `ScoreSegments`, `TagChip`, `ReasonChip`, `CodeChip`, `HeldChip`, `InfoTip`, `TopBar`, `TitleBlock`, `ScorecardStrip`, `ScoreRailItem`, `DeliverablesCard`, `DirectionNote`, `SectionCaption`, `JustificationsPanel`, plus a **private inlined `Badge`**.
- `task-detail-combined.jsx` — `DirectionD`, the shipped "collapsed thread" unified view (`DAvatar`, `QuietScore`, `AltConsidered`, `NavTurn`, `NavJump`, `ScoreDimRow`, `TurnDetail`, `TurnRow`, `MetaSection`).
- `task-detail-directions.jsx` — three alternate layouts A/B/C (thread / split-rail / ledger).
- `task-data.js` — real content: STEM eval task `l12` (stormwater tank draining), KaTeX-delimited math.
- `design-canvas.jsx` — internal design tooling, **not part of the DS** (see §6 warning).

**The rating color contract** (`RATE_COLORS`, scores 0–4) is fully tokenized and is what a Task Review scorecard must match:

| Score | bg | fg | dot | border |
|---|---|---|---|---|
| 4 | `--status-success-bg` | `--accent-green-dark` | `--accent-green` | `--accent-green-dull` |
| 3 | `--status-info-bg` | `--accent-blue-dark` | `--accent-blue` | `--accent-blue-dull` |
| 2 | `--status-warning-bg` | `--accent-yellow-dark` | `--accent-yellow` | `--accent-yellow-dull` |
| 1, 0 | `--status-error-bg` | `--accent-red-dark` | `--accent-red` | `--accent-red-dull` |

`REASON_META` (intervention chips): Correction → warning pair · Scope_Change → info pair · New_Requirement → `--accent-purple-lite`/`--accent-purple-dark` · Hand-off → success pair.

---

## 3 · Token system

**140 tokens** indexed in the manifest across 7 files. Base scale steps + semantic aliases; the readme instructs: *"Use the semantic aliases in product code; reach for raw scale steps only when no alias fits."*

### Primary blue (11 steps)
`--primary-6: #1279f7` is **the** interactive color — CTA, links, active, focus ring.

| Token | Hex | Role |
|---|---|---|
| `--primary-0` | `#eef8ff` | tinted surface bg (`--surface-tint`, scrollbar track) |
| `--primary-1` | `#d9eeff` | hover surfaces, light fills |
| `--primary-2` | `#bbe3ff` | borders on light primary elements |
| `--primary-3` | `#8cd2ff` | decorative glows |
| `--primary-4` | `#56b9ff` | decorative, non-interactive |
| `--primary-5` | `#2f9aff` | background glow |
| **`--primary-6`** | **`#1279f7`** | **CTA / links / active / focus ring** |
| `--primary-7` | `#1165e4` | button hover, FocusBadge |
| `--primary-8` | `#1551b8` | pressed |
| `--primary-9` | `#174791` | dark emphasis |
| `--primary-10` | `#132c58` | deep — avoid in chrome |

`--primary-0…5` are **surface washes only, never text.**

### Neutrals (12 steps — note the half-step)
| Token | Hex | Role |
|---|---|---|
| `--neutrals-0` | `#0d0d0d` | body text, headings (`--text-primary`) |
| `--neutrals-1` | `#3b3b3b` | secondary/strong UI text |
| `--neutrals-2` | `#666666` | muted text, descriptions |
| `--neutrals-3` | `#808080` | placeholders, disabled, icons, **table header text** |
| `--neutrals-4` | `#b3b3b3` | dividers (`--border-divider`) |
| `--neutrals-5` | `#cccccc` | input borders (`--border-strong`) |
| `--neutrals-6` | `#d9d9d9` | hairlines, table rules (`--border-hairline`) |
| `--neutrals-7` | `#e6e6e6` | card borders (`--border-card`), meter track |
| `--neutrals-8` | `#f2f2f2` | alt rows, chip bg (`--surface-alt`) |
| **`--neutrals-85`** | **`#f5f5f5`** | **page + sidebar + table-header bg** |
| `--neutrals-9` | `#ffffff` | cards, inputs (`--surface-card`) |

⚠️ `--neutrals-85` is a *half-step between 8 and 9*, not "85". Easy to mis-type as `--neutrals-8`.

### Semantic accents — lite / dull / base / dark
| Family | lite | dull | base | dark | Meaning |
|---|---|---|---|---|---|
| Red | `#eedcda` | `#eaaca5` | `#ce2c31` | `#641818` | error, destructive |
| Green | `#d7e6dd` | `#a1c9b2` | `#218358` | `#006d43` | success, positive |
| Yellow | `#fde1b1` | `#efbd61` | `#e7a300` | `#8a5c00` | warning, caution |
| Purple | `#b9beed` | `#6b71cf` | `#45478d` | `#303063` | annotations, **metadata** |
| Blue | `#cbddef` | `#8db1dd` | `#0d74ce` | `#0062bb` | informational, links |

**Status pairs (chips + banners): always `lite` bg + `dark` fg** — `--status-{success,warning,error,info}-{bg,fg}`. Note `--accent-blue #0d74ce` is a *different* blue from `--primary-6 #1279f7`: accent-blue = "info" semantics, primary-6 = "interactive". Don't conflate.

### Delta / categorical hues (timeline chips, data tags)
| Token | Value |
|---|---|
| `--delta-pink` | `#d6006e` |
| `--delta-cyan` | `#0097a7` |
| `--delta-violet` | `#8b3fd9` |
| `--delta-blue` | → `var(--accent-blue)` `#0d74ce` |
| `--delta-emerald` | → `var(--accent-green)` `#218358` |
| `--delta-amber` | → `var(--accent-yellow)` `#e7a300` |
| `--delta-rose` | → `var(--accent-red)` `#ce2c31` |
| **`--delta-tag-id`** | **`#f5ebdc`** — warm sand, the **ID/code chip background** |

Only 3 are truly new hues; 4 alias back to accents. `--delta-tag-id` is the odd one out — the only warm color in the system, used by `Badge variant="tag"` and `CodeChip` for monospace identifiers (`0xA3F9`). Bundle usage counts: `--delta-tag-id` ×5, `--delta-blue`/`--delta-emerald`/`--delta-violet` ×3, `--delta-cyan` ×2, `--delta-pink` ×1.

### Overlays
`--overlay-subtle: rgba(13,13,13,0.05)` (hover) · `--overlay-medium: rgba(13,13,13,0.10)` (pressed, also the Meter's empty segment) · `--overlay-backdrop: rgba(13,13,13,0.50)` (modal/drawer scrim).

---

## 4 · Typography

### Families (3)
| Token | Stack | Use |
|---|---|---|
| `--font-primary` / `--font-family-sans` | `"Inter Display", system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif` | **All** UI chrome, body, headings |
| `--font-display` | `"Season Mix", "Inter Display", system-ui, sans-serif` | Brand/display only ⚠ trial |
| `--font-mono` | `"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace` | IDs, hashes, code, counts, data values, meter value labels |

`--font-primary` and `--font-family-sans` are byte-identical duplicates; both are indexed and lint-allowed.

⚠️ The readme flags that the source guidelines named **Instrument Sans**, but the shipped binaries and the live product use **Inter Display**. Tokens follow the product.

### Weights — 4 files shipped, 4 tokens declared, **and they don't line up**
Shipped `@font-face`: **400, 500, 700, 900.**
Declared tokens: `--weight-regular: 400`, `--weight-medium: 500`, `--weight-semibold: 600`, `--weight-bold: 700`.

**No 600 file exists.** Per CSS font matching, requested 600 resolves upward to **700**. This matters a lot, because `--weight-semibold` is what `Button`, `Badge`, `Tag`, `FocusBadge`, `Avatar`, `Tabs`, `Input` labels, and **table headers** all use — every one of them renders at Bold 700. Reproduce the exact look by writing `--weight-semibold` (not 600 literal, not 700) so the substitution stays identical. 900/Black is shipped but has **no token** pointing at it.

### Sizes — role-based, not a numeric ramp
| Token | rem | px | Documented spec |
|---|---|---|---|
| `--text-page-heading` | 1.5rem | 24 | / 600 |
| `--text-card-title` | 1.25rem | 20 | / 700 |
| `--text-focus-badge` | 1.15rem | 18.4 | / 600 |
| `--text-body` | 1rem | 16 | / 400 |
| `--text-button` | 0.875rem | 14 | / 600 |
| `--text-label` | 0.875rem | 14 | / 400 |
| `--text-table-header` | 0.8125rem | 13 | / 600 |
| `--text-caption` | 0.75rem | 12 | / 700 |
| `--text-micro` | 0.65rem | 10.4 | / 600 — domain pill |

⚠️ Named by **role**, not size. There is no `--text-sm` / `--text-lg`. Pick by what the element *is*.

### Leading & tracking
- `--leading-heading: 1.23` (123%) · `--leading-body: 1.5` · `--leading-tight: 1` (buttons/labels)
- `--tracking-heading: -1.12px` · `--tracking-normal: 0`

⚠️ **`-1.12px` is an absolute px value, not an em.** It's tuned for the 24px page heading (≈ −0.047em). Applied to 14px text it becomes a crushing −0.08em. **Use `--tracking-heading` only on `--text-page-heading`-scale type.** Table headers get their own hardcoded `letterSpacing: "0.4px"` + `textTransform: uppercase` — a *positive* tracking that has no token.

---

## 5 · Spacing, radius, shadows, motion

### Spacing — "8px base" is a misnomer
```
--space-1:  0.25rem   4px    tight chip padding, icon gap
--space-2:  0.5rem    8px    inner icon/text gap
--space-3:  0.75rem  12px    compact list items
--space-4:  1rem     16px    DEFAULT card / section padding
--space-5:  1.25rem  20px    component internal padding
--space-6:  1.5rem   24px    section padding, button padding
--space-8:  2rem     32px    page-level vertical rhythm
--space-12: 3rem     48px    empty-state padding
```
⚠️ **Only 8 steps. There is no `--space-7`, `-9`, `-10`, `-11`** — the readme's "`--space-1…12`" implies a continuous ramp that doesn't exist. And despite "strict 8px base," the actual grid is **4px** (`--space-N` = N × 0.25rem); the readme's own body text concedes *"every gap/pad is a 0.25rem multiple."* Treat it as a 4px grid with 8px rhythm.

**Layout dimensions:** `--sidebar-width: 240px` · `--sidebar-width-collapsed: 48px` · `--drawer-max-width: 800px` · `--control-min-height: 40px` (min touch target) · `--icon-button-size: 32px`.

### Radius
```
--radius-none:  0          tables, code blocks
--radius-sm:    0.25rem    4px   inline chips, Tag, CodeChip
--radius-md:    0.375rem   6px   small buttons, tooltips, IconButton
--radius-lg:    0.5rem     8px   ★ DEFAULT: inputs, buttons, cards-of-record
--radius-xl:    0.75rem   12px   panels, Card, FocusBadge
--radius-2xl:   1rem      16px   modals, drawers
--radius-pill:  9999px           status chips, Badge, meter track
--radius-full:  50%              avatars, circular icon buttons
```
Note the split: **`Card` uses `--radius-xl` (12px)** while the default for buttons/inputs is `--radius-lg` (8px). Tables use the `--radius-lg` frame but sharp interior cells.

### Shadows — soft, near-black `rgba(13,13,13,·)`, low spread
```
--shadow-sm:       0 1px 2px  rgba(13,13,13,0.05)
--shadow-md:       0 1px 3px  rgba(13,13,13,0.08)    ★ cards at rest
--shadow-lg:       0 4px 12px rgba(13,13,13,0.10)    hover / floating
--shadow-xl:       0 10px 25px rgba(13,13,13,0.12)   drawers, dropdowns, Toast
--shadow-focus:    0 0 0 2px rgba(13,116,206,0.30)   ← accent-blue, NOT primary-6
--shadow-inset:    inset 0 -1px 0 var(--neutrals-7)  tab track
--shadow-error:    0 0 10px rgba(206,44,49,0.50)     error focus glow
--shadow-elevated: 0 4px 12px rgba(18,121,247,0.12),
                   0 1px 3px rgba(13,13,13,0.08)     selected card (blue-tinted, 2-layer)
```
⚠️ `--shadow-focus` is built from `#0d74ce` (accent-blue) while `--focus-outline` is `2px solid var(--primary-6)` (`#1279f7`). Two different blues for the same conceptual state — a real inconsistency in the source. Match whichever the target screenshot uses.

Escalation ladder: rest `md` → hover `lg` → overlay `xl`; selected → `elevated`. Readme: *"a single sheet of paper lifting — never deep or dramatic."*

### Motion
`--transition-ui: 0.2s ease-in-out` · `--transition-layout: 380ms cubic-bezier(0.4,0,0.2,1)` · `--transition-mount: 0.35s cubic-bezier(0.4,0,0.2,1)` · `--ease-standard: cubic-bezier(0.4,0,0.2,1)`. A `@media (prefers-reduced-motion: reduce)` block collapses the first three to `0.01ms`.

⚠️ **Manifest bug:** the indexer captured the *reduced-motion* values — `_ds_manifest.json` records `--transition-ui: "0.01ms"`, not `"0.2s ease-in-out"`. Trust `tokens/effects.css`, not the manifest, for these three.

Also note `Drawer` hardcodes `transform 0.3s ease` / `opacity 0.3s ease` rather than using a token, so **drawer animation does not respect reduced-motion.**

### Other rules
- **Borders:** 1px `--neutrals-7` cards, `--neutrals-6` table rules, inputs rest on `--accent-blue-lite`.
- **Backgrounds:** flat fills only — no gradients, patterns, textures, illustrations. No glassmorphism.
- **States:** hover = one step darker or `--neutrals-85` wash · focus = `2px --primary-6` outline, offset 2px · pressed = `translateY(1px)` buttons / `scale(0.95)` icon buttons · **disabled = `opacity: 0.6`, color never changes** · error = red border + `--shadow-error`.
- **Scrollbar:** 8px, track `--primary-0`, thumb `--accent-blue-lite` → `--neutrals-3` on hover.
- **Iconography:** ~1.5px stroke line icons on a 16px grid, single-color via `currentColor`. **No emoji, ever.** Lucide is the flagged substitute; the real set was never supplied.

---

## 6 · `_adherence.oxlintrc.json` — what gets flagged

**oxlint** config, plugins `react` + `import`, **every rule at `"warn"`** (not `error`). 34 `no-restricted-syntax` selectors + 2 others. Plus an `x-omelette` metadata block (140 token names + `tokenKinds` + `fontFamilies`) that the linter ignores but tooling reads.

### The three global rules

**A. Raw hex colors**
```
Literal[value=/#[0-9a-fA-F]{3,8}\b/]
→ "Raw hex color — use a design-system color token via var()."
```

**B. Raw px values**
```
Literal[value=/\b\d+px\b/]
→ "Raw px value — use a design-system spacing token via var()."
```

**C. Non-DS fonts**
```
Literal[value=/font-family\s*:\s*(?!['"]?(?:Inter Display|Season Mix|JetBrains Mono))/i]
→ "Font not provided by the design system."
```

**D. `no-restricted-imports`** — blocks deep imports into `argo-report/**`, `components/{data-display,feedback,forms,navigation,overlay}/**`, `ui_kits/dataset-explorer/**`, `ui_kits/dataset-explorer/task-detail/**`; message: *"Import design-system components from 'index.js', not component internals."* Overridden off for `**/index.js`. **Moot in practice** — no `index.js` ships and the bundle is consumed via `window`, so there are no imports to restrict.

**E. `react/forbid-elements`** with `forbid: []` — a **no-op**.

### How the matchers actually behave (this determines how you write code)

These selectors match **`Literal` AST nodes only** — string and numeric literals. Consequences:

1. **Numeric JSX values are invisible to the px rule.** `style={{ width: 120, height: 6 }}` → numeric literals, value `120`, no `px` substring, **passes**. The DS's own components do exactly this everywhere. **So: express dimensions as unitless numbers, not `"120px"` strings.**
2. **Template literals are not `Literal` nodes.** `` border: `1px solid ${c}` `` is a `TemplateLiteral` → **not matched**. Card, Input, Toast, Tabs all use this form. A plain `border: "1px solid var(--neutrals-7)"` (Table.jsx) **is** matched.
3. **The px rule has no token-awareness.** `"1px solid var(--border-card)"` gets flagged even though it's fully tokenized — there is no 1px border token to satisfy it. Same for `"2px"`, `"0.4px"` (table-header tracking), `"translateY(1px)"`, `"translateX(19px)"`.
4. **Rule C is a font false-positive trap.** It fires on `font-family:` in a *string*, and the negative lookahead only accepts the three literal family names. `<style>{"body { font-family: var(--font-primary) }"}</style>` — **flagged**, because `var(...)` isn't `Inter Display`. Meanwhile `fontFamily: "var(--font-primary)"` in a style object never fires (no `font-family:` substring). **Keep font declarations out of raw CSS strings in JS; put them in style objects or the linked `.css` file.**
5. **Rule A over-matches.** Any string containing a `#` + 3–8 hex chars trips it — including `href="#section-a1b2c3"` and some SVG/data URIs.
6. **oxlint only parses JS/JSX.** `.css` files are **never linted**. All token discipline in CSS is honor-system.

### 20 per-component prop rules

Two selector families:
- **Prop allowlist:** `JSXOpeningElement[name.name='X'] > JSXAttribute > JSXIdentifier[name!=/^(?:…)$/]` — any prop outside the whitelist warns. All whitelists implicitly allow `key`, `ref`, `className`, `style`, `children`.
- **Enum values:** `Button.variant` ∈ primary|secondary|ghost|destructive · `Button.size` ∈ sm|md|lg · `Button.type` ∈ button|submit|reset · `Badge.variant` ∈ success|warning|error|info|neutral|primary|tag · `AlertBanner.variant` & `Toast.variant` ∈ error|success|warning|info · `IconButton.variant` ∈ ghost|solid · `Tooltip.placement` ∈ top|bottom|left|right · `TableColumn.align` ∈ left|center|right.

**The lint's component set ≠ the export set.** x-omelette lists 20; the runtime exports 21. The lint **omits** `Table`, `Select`, `Tabs`, `CardTitle` and **adds** three non-exported pseudo-components — `TableColumn` (`key, header, align, width, render`), `SelectOption` (`value, label`), `TabItem` (`value, label, count, disabled`). These describe the *shapes of the array items* you pass to `columns` / `options` / `tabs`, not real JSX elements. So `Table`, `Select`, and `Tabs` themselves are **unconstrained** by the prop rules — but the item shapes are documented and worth honoring.

⚠️ Two prop-allowlist rules are **stricter than the implementation**: `Meter` accepts `...rest` and `Table` accepts `headerStyle`/`cellStyle`, but `Input`'s allowlist correctly includes `containerStyle`. Conversely, `Checkbox`/`Radio`/`Switch`/`Select`/`Input` whitelists **omit `onChange`, `id`, `name`, `value`, `placeholder`, `options`** even though every implementation destructures them — passing `onChange` to a `Checkbox` will warn. Since everything is `"warn"`, it won't fail a build, but it will pollute an adherence score.

### Practical rules for writing the rebuild

| Do | Don't |
|---|---|
| `background: "var(--surface-card)"` | `background: "#ffffff"` |
| `padding: "var(--space-4)"` | `padding: "16px"` |
| `width: 120` (unitless number) | `width: "120px"` |
| `` border: `1px solid var(--border-card)` `` (template) | `border: "1px solid var(--border-card)"` (plain string) |
| `fontFamily: "var(--font-primary)"` in a style object | `font-family: …` inside a CSS string in JS |
| `fontWeight: "var(--weight-semibold)"` | `fontWeight: 600` |
| Only whitelisted props + enum values | Extra props, arbitrary variant strings |
| Add `ignorePatterns` for `_ds_bundle.js` | Lint the vendored bundle |

⚠️ **The DS would fail its own lint.** 112 distinct string literals containing `Npx` and ~15 raw hex values live in `_ds_bundle.js`. The hexes are all in `ui_kits/.../design-canvas.jsx` — internal design tooling using an unrelated warm palette (`#c96442`, `#2a251f`, `#fef4a8`, `#f0eee9`, `#29261b`). **That file is not part of the Deccan design language; don't take color cues from it.** The shipped config has no `ignorePatterns`, so add one.

---

## 7 · Licensing & production risk

I read the TTF `name` tables directly. Verdict:

### 🔴 BLOCKER — Season Mix is an unlicensed TRIAL cut
`assets/fonts/SeasonMix-TRIAL-Regular.ttf` (172 KB), internal family name **`Season Mix-TRIAL`**, ©2017–2025 **Displaay Type Foundry s.r.o.** Its embedded license reads:

> "Using the fonts or the data within the font files in a legal manner means you should not modify, reassemble, rename, store on publicly accessible servers, redistribute, or sell them. Engaging in any prohibited activities with this typographic software may lead to legal action."

`tokens/fonts.css` `@font-face`s it from `assets/fonts/` — **serving this file from any public deployment is exactly the prohibited "store on publicly accessible servers" + "redistribute."** It also **renames** the family (declares `"Season Mix"` for a file whose internal name is `"Season Mix-TRIAL"`), arguably a second violation. Redistributing this directory (git, artifact, tarball) redistributes the trial binary.

**Mitigation:** buy the license from displaay.net, or drop `--font-display` entirely. Its only role is "brand/display moments" — and the readme itself flags that role as *an unconfirmed assumption*. **No shipped component uses `--font-display`.** Cutting it costs nothing and removes the blocker outright. (Also note trial cuts are typically charset-limited — expect missing glyphs.)

### 🟢 CLEAR — Inter Display
All four TTFs are **SIL Open Font License 1.1**, "Copyright 2016 The Inter Project Authors," v4.000, by rsms. Free for commercial use, embedding, and redistribution. OFL only requires the license accompany the files and that derivatives not use the reserved name. **Action:** ship `OFL.txt` alongside `assets/fonts/`. Currently absent.

### 🟡 JetBrains Mono — license fine, delivery is not
No file ships. `tokens/fonts.css` line 18 `@import`s `https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap`. JetBrains Mono is itself **OFL 1.1** — so *licensing* is not the issue. The *delivery* is:
- **Hard-fails under a strict CSP / in Claude Artifacts** (external hosts blocked) → mono text silently falls back to `ui-monospace`/Menlo. Every ID, hash, count, score, and meter value changes metrics.
- Third-party request to Google on every page load (privacy / GDPR review surface).
- Offline / air-gapped enterprise deploys break.
- The `@import` sits at the top of `fonts.css`, which is itself `@import`ed by `styles.css` → **nested @import chain, fully render-blocking.**

**Fix:** self-host JetBrains Mono (it's OFL) and delete the `@import`. This also fixes the perf and CSP problems in one move.

### Other production blockers

| Issue | Severity | Impact |
|---|---|---|
| **Bundle hijacks `#root`** — 2 unconditional `createRoot(getElementById("root")).render()` calls | 🔴 High | Renders the Deccan demo over your app. Must strip or sandbox. |
| **Missing weight 600** — no Inter Display SemiBold file; `--weight-semibold` silently renders as Bold 700 | 🟡 Med | Affects buttons, badges, tags, table headers, tabs — i.e. most of the UI. |
| **Icon set is approximated** — original never supplied; inline SVGs hand-drawn + Lucide flagged as substitute | 🟡 Med | Explicitly flagged "for confirmation." Iconography will not match the real product. |
| **Wordmark SVGs absent** — readme documents `assets/logo/{,-white,-blue}.svg`; the directory doesn't exist | 🟡 Med | No brand mark for a header. Must be sourced. |
| **`.d.ts` / `.prompt.md` / component sources absent** | 🟡 Med | No type safety, no IDE hints; prop contracts must be reverse-engineered from the bundle (or read off the lint config, which is close but not exact). |
| **~40 unnamespaced `window` globals** | 🟡 Med | Collision risk; `window.Badge` shadows a *different* Badge than the namespaced one. |
| **Hardcoded CloudFront image** in task-data | 🟢 Low | `digpbmme8jwkp.cloudfront.net/…/l12_vdag.png` — external dep, may rot. |
| **Undeclared KaTeX dep** | 🟢 Low | `RichHtml` needs `window.renderMathInElement`; guarded, degrades to raw `$…$`. |
| **`color-mix()` used** in Badge/Table/Tabs/FocusBadge | 🟢 Low | Baseline 2023 — fine on modern browsers, breaks silently on older ones (falls back to transparent/unset). |
| **Manifest records reduced-motion values** for the 3 transition tokens | 🟢 Low | Don't generate code from the manifest for those; read `effects.css`. |
| **No dark mode** | 🟢 Low | Zero dark tokens, no `prefers-color-scheme`. Light-mode only by design. |

### Minimum path to production
1. Remove or license Season Mix; drop `--font-display` if unused (it is).
2. Self-host JetBrains Mono; delete the Google Fonts `@import`.
3. Add `OFL.txt` for Inter.
4. Extract the 21 primitives from the bundle; discard `ui_kits/**`, `argo-report/**`, `design-canvas.jsx` and the three `createRoot` mounts.
5. Add Inter Display SemiBold 600, or accept the 700 substitution and document it.
6. Source the real icon set + wordmark from Deccan AI.
7. Add `ignorePatterns: ["_ds_bundle.js"]` to the oxlint config.