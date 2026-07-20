# Deccan AI — Design System

The brand & product design system for **Deccan AI**. It contains the color, type, spacing, radius, shadow, and motion tokens; the reusable React UI components; foundation specimen cards; brand assets; and product UI kits. An automated compiler reads this project, bundles the components into a runtime library (`window.DeccanAIDesignSystem_ffd752`), and indexes the tokens declared from `styles.css`.

> **Use `styles.css` as the single entry point.** It `@import`s every token + font file. Consume the components from the generated `_ds_bundle.js` via `window.DeccanAIDesignSystem_ffd752`.

---

## 1 · Product context

Deccan AI is an **enterprise dataset-visualization platform**. Teams use it to explore and review datasets across categories like **coding**, **agentic traces**, and **RL environment samples**. The audience is mixed — **technical** users (ML engineers, data scientists inspecting raw traces and payloads) *and* **non-technical** stakeholders (reviewers, leads tracking status and coverage) — so the UI must stay dense and precise without becoming intimidating.

The product vocabulary in the source guidelines points at the core surfaces:
- **Dataset tables** — long, scannable lists with status chips, counts, and category tags.
- **Detail drawers / side panels** — open a row (a trace, a sample) for inspection without leaving the list.
- **Timeline event chips** — categorical "delta" colors mark events along a trace.
- **ID / data tags** — monospace identifiers (`0xA3F9`) and metadata.
- **Focus badges** — page-level labels flagging the active dataset/context.

### Sources provided
- `uploads/UI_DESIGN_GUIDELINES (1).md` — the authoritative token + component spec, lifted from the product's `src/styles/core/_tokens.scss` and component library. **All tokens here trace back to that file.**
- `uploads/assets-1781045925313.svg` — the Deccan AI wordmark (copied to `assets/logo/`).
- `uploads/pasted-1781046192756-0.png` — **product homepage screenshot** (All Domains view) — the source of truth for the Web App UI kit.
- **Licensed font files** — Inter Display (full family) + Season Mix (TRIAL cut), copied to `assets/fonts/`.
- No codebase or Figma file was attached.

> Note: the guidelines doc names *Instrument Sans*, but the live product (per the screenshot) and the supplied binaries use **Inter Display**. The tokens follow the real product.

---

## 2 · Content fundamentals (voice & copy)

Deccan AI's copy is **plain, technical, and direct** — it respects a reader who knows their domain but never shows off.

- **Tone:** matter-of-fact and operational. State what happened and what to do next. No marketing gloss, no exclamation points in product chrome.
- **Person:** address the user as **you** ("This dataset is read-only"); the system refers to itself implicitly, not as "I". Use **imperative** for actions ("View", "Retry", "Choose a category").
- **Casing:** **Sentence case** for descriptions and helper text ("All datasets across domains"). **Title Case** for proper nouns — page/domain names ("All Domains", "Functional Streams", "Physical Intelligence") and dataset names ("Academic Research RAG", "Coding Agent Evaluation - Python"). Buttons are single Title-Case-ish verbs ("View").
- **Brand name:** always **Deccan AI** (two words, "AI" capitalized).
- **Numbers & counts:** availability is counted in lowercase **"datapoints"** ("10 datapoints", "1 datapoint" — singular handled); format large counts with thousands separators (`1,284 rows`); render IDs/hashes/code values in **monospace**.
- **Descriptions:** one to two full sentences, technical and concrete, leading with what the dataset does — *"Expert-curated RAG datasets built from research papers to enhance model reasoning across academia topics."* Truncate at two lines in tables.
- **Status language:** short, single-word where possible — *Approved · Pending · Rejected · Queued · Read-only*.
- **Error copy:** lead with the problem, follow with the fix. *"Upload failed — 3 rows could not be parsed. Check the schema and retry."*
- **Emoji:** **none.** This is an enterprise tool; iconography carries meaning, not emoji.
- **Vibe:** confident, quiet, instrument-grade. Think "lab bench", not "consumer app".

**Example microcopy**
> Empty state: *"No datasets yet. Create one to start visualizing samples."*
> Confirmation: *"Delete dataset? This permanently removes agentic-traces-v2 and its 1,284 samples."*
> Helper: *"Numeric only."*

---

## 3 · Visual foundations

A **calm, neutral, light-mode** system with a single confident blue. The work is the data — chrome recedes.

- **Color & vibe.** Backgrounds are off-white/white (`--neutrals-85` page, `--neutrals-9` cards). Text is near-black (`--neutrals-0/1`). One **primary blue** (`--primary-6 #1279f7`) carries every interactive action; everything else is grayscale until status demands color. Imagery, when present, is screenshots/data viz — **cool and neutral**, not warm or filtered. No duotones, no grain.
- **Accents are semantic, not decorative.** Red = error/destructive, Green = success, Yellow = warning, Purple = metadata/annotation, Blue = info. Each has `lite / dull / base / dark` tints. The vivid **delta** hues (pink/cyan/violet/…) are reserved for categorical timeline chips and data tags.
- **Type.** **Inter Display** for all UI chrome, body, and headings (confirmed against the live product; weights 400/500/700/900 shipped). *Season Mix* is reserved for brand/display moments (⚠ trial cut). *JetBrains Mono* for code, IDs, counts, and data values. Headings are tight: `line-height 1.23`, `letter-spacing -1.12px`. Body is `1.5`.
- **Spacing.** Strict **8px base**; every gap/pad is a `0.25rem` multiple (`--space-1…12`). Density is medium — generous enough to scan a long table, tight enough to keep context on screen.
- **Corner radius.** Soft but not pill-y. **8px (`--radius-lg`) is the default** for buttons, inputs, cards-of-record; 12px for panels/larger cards; 16px for modals/drawers; full pills only for status chips and avatars. Tables and code use sharp `0` corners.
- **Borders.** Hairlines do the heavy lifting: 1px `--neutrals-7` for cards, `--neutrals-6` for table rules. Inputs rest on a soft `--accent-blue-lite` border and switch to a `--primary-6` focus outline.
- **Shadows.** Soft, near-black, low-spread. `--shadow-md` at rest for cards; escalate to `--shadow-lg` on hover, `--shadow-xl` for drawers/dropdowns. Active/selected cards use the blue-tinted `--shadow-elevated`. Shadows suggest a single sheet of paper lifting — never deep or dramatic.
- **Cards.** White surface, 12px radius, 1px `--neutrals-7` border, `--shadow-md`. Interactive cards gain a `--primary-6` border + `--shadow-lg` on hover; selected cards use `--shadow-elevated`.
- **Backgrounds.** Flat fills only — **no gradients, no patterns, no textures, no hand illustration.** Alternate table rows / chip fills step to `--neutrals-8`. Decorative primary tints (`--primary-0…5`) appear only as faint surface washes, never as text.
- **Transparency & blur.** Used sparingly and only functionally: the modal/drawer backdrop is `rgba(13,13,13,0.5)`; hover/press overlays are `--overlay-subtle / --overlay-medium`. No glassmorphism.
- **Motion.** Quick and purposeful. UI transitions are `0.2s ease-in-out`; layout shifts (sidebar) use `380ms cubic-bezier(0.4,0,0.2,1)`; drawers slide `0.3s ease`. **No bounces, no looping decorative animation.** Always ship a `prefers-reduced-motion: reduce` override (tokens collapse to `0.01ms`).
- **Interactive states.** Hover = darken one step (`--primary-6 → --primary-7`) or a `--neutrals-85` wash. Focus = 2px `--primary-6` outline (offset 2px) or `--shadow-focus`. Pressed = `translateY(1px)` (buttons) / `scale(0.95)` (icon buttons). Disabled = `opacity 0.6`, **color never changes**. Error = red border + `--shadow-error` glow on focus.
- **Layout rules.** Sidebar 240px expanded / 48px collapsed. Drawers up to 800px, full-width on mobile. Min touch target 40px.

---

## 4 · Iconography

- **Style:** thin-stroke, geometric **line icons** (~1.5px stroke on a 16px grid), single-color via `currentColor` so they inherit text color. They match the neutral, instrument-grade tone — outline, not filled, not duotone.
- **Source:** the original product's icon set was **not provided** (no codebase/sprite/icon-font was attached). The components in this system ship small **inline SVGs** drawn to the spec (close ×, chevron, plus, download, info, check) so nothing depends on an external set.
- **Recommended substitute:** for any product/UI-kit work needing a fuller icon set, use **[Lucide](https://lucide.dev)** — its 1.5px stroke weight and 24px geometric grid are the closest CDN match to the inline glyphs here. ⚠ **This is a substitution**, flagged for confirmation; if Deccan AI has a licensed/in-house icon set, drop it into `assets/icons/` and we'll wire it in.
- **Emoji / unicode:** **never** used as icons. Status is conveyed by colored `Badge` dots, not emoji.
- **Logo:** the wordmark lives in `assets/logo/` in three fills — `deccan-ai-wordmark.svg` (#121212 on light), `-white.svg` (reversed for dark), `-blue.svg` (primary accent). Give it clear space ≥ the cap-height of "Deccan" on all sides.

---

## 5 · Components

Reusable React primitives, exported on `window.DeccanAIDesignSystem_ffd752`. Each has a `.d.ts` (props), a `.prompt.md` (usage), and a group card HTML.

| Group | Directory | Components |
|---|---|---|
| Forms | `components/forms/` | `Button`, `IconButton`, `Input`, `Select`, `Checkbox`, `Radio`, `Switch` |
| Feedback | `components/feedback/` | `Badge`, `FocusBadge`, `AlertBanner`, `Toast`, `Tooltip` |
| Data display | `components/data-display/` | `Card` (+`CardTitle`), `Table`, `Avatar`, `Tag`, `Meter` |
| Navigation | `components/navigation/` | `Tabs` |
| Overlay | `components/overlay/` | `Dialog`, `Drawer` |

Usage (inside a card or consuming page):
```html
<link rel="stylesheet" href="styles.css">
<script src="_ds_bundle.js"></script>
<script type="text/babel">
  const { Button, Table, Drawer } = window.DeccanAIDesignSystem_ffd752;
</script>
```

---

## 6 · UI kits

Full-screen product recreations live under `ui_kits/<product>/` (each with `index.html` + JSX screens). These compose the components above — they do not re-implement primitives.

- **`ui_kits/dataset-explorer/`** — the Web App. Two linked screens:
  - **`index.html`** — the **All Domains homepage**, recreated faithfully from the product screenshot: domains sidebar (icon tiles + counts), blue breadcrumb header, blue-bar section title, datasets table (domain chips, datapoint pills, 2-line descriptions, View buttons).
  - **`dataset-detail.html`** — the **dataset detail page** that opens from **View** (wired live on the *Deep Research Agent Study* row). Structured from the DRA showcase: dataset header, **dataset card** (metadata, coverage chips, “Tested on” model configs with info tooltips), **scoring methodology** (ACCEPT rule, difficulty, rubric DI·AR·RF·EP·FD), “Get the dataset” CTA, and a **per-model eval samples table** (Rubric 0–3 + Verifier pass-rate `Meter`s, Difficulty, ACCEPT) where each row opens a **sample drawer** (prompt shown, held-out sanity check / solution logic / verifiers). Styled entirely in the Deccan AI system — not a copy of the showcase's own look. Rows other than the DRA one still show a “to be defined” placeholder.

---

## 7 · Foundation cards (Design System tab)

Specimen cards live in `guidelines/cards/` and render in the Design System tab, grouped:
- **Colors** — primary, neutrals, accents, delta/tag, status pairs, text & surfaces
- **Type** — font families, type scale
- **Spacing** — spacing scale, radius scale, elevation
- **Brand** — logo
- **Components** — forms, feedback, data display, navigation, overlay

---

## 8 · Index / manifest

```
styles.css                      ← global entry (imports only)
tokens/
  fonts.css                     @font-face — Inter Display + Season Mix (local), JetBrains Mono (⚠ Google substitute)
  colors.css                    primary, neutrals, accents, delta, overlays + semantic aliases
  typography.css                font families, sizes, weights, leading, tracking
  spacing.css                   8px scale + layout dimensions
  radius.css                    radius scale
  shadows.css                   elevation + focus/error/inset
  effects.css                   transitions, focus outline, scrollbar (+ reduced-motion)
components/
  forms/ feedback/ data-display/ navigation/ overlay/
guidelines/cards/               foundation specimen cards (@dsCard)
assets/logo/                    wordmark (default / white / blue)
assets/fonts/                   Inter Display (400/500/700/900) + Season Mix (TRIAL)
ui_kits/dataset-explorer/       Web App · All Domains homepage + dataset detail (DRA)
readme.md                       this file
SKILL.md                        Agent-Skill manifest (Claude Code compatible)
```

---

## Caveats / open items
1. **Season Mix is a TRIAL cut** (`SeasonMix-TRIAL-Regular.ttf`) — swap in the licensed file before production. Its intended role (brand/display only?) is an assumption — confirm.
2. **Inter Display SemiBold (600) wasn't provided**; CSS weight 600 resolves to Bold 700. Add the SemiBold file if the product uses it.
3. **JetBrains Mono still loads from Google Fonts** — no licensed file provided.
4. **Icon set is approximated** (hand-matched line glyphs / Lucide substitute) — supply the in-house set to replace.
5. The homepage shows 8 of 21 datasets (those visible in the screenshot); other rows are omitted, not invented. Only the *Deep Research Agent Study* row's **View** opens the real detail page — other datasets' detail views aren't defined yet.
6. The dataset detail page uses the **DRA Management Consulting** content from the showcase as its concrete example; sample 01 carries full ground-truth detail, samples 02–13 carry scores + prompt previews (full ground truth “on request”).
