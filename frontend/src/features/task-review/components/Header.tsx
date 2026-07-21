import { FocusBadge, Icon, t, weight } from "../../../ds";

function Rule() {
  return <span style={{ width: 1, height: 22, background: t.n7, flexShrink: 0 }} />;
}

function PagerBox({ dir, onClick, disabled }: { dir: "chevronLeft" | "chevronRight"; onClick: () => void; disabled: boolean }) {
  return (
    <span
      onClick={disabled ? undefined : onClick}
      title={dir === "chevronLeft" ? "Previous task" : "Next task"}
      style={{
        width: 30,
        height: 30,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: 7,
        border: `1px solid ${t.n6}`,
        background: t.n9,
        color: t.n2,
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.4 : 1,
      }}
    >
      <Icon name={dir} size={16} stroke={1.8} />
    </span>
  );
}

export function Header({ index, total, onPrev, onNext, onSkip, onBrowseGym, gymTaskId, onExitGym, onOpenQa, annotatorEmail, onSetAnnotator }: { index: number; total: number; onPrev: () => void; onNext: () => void; onSkip: () => void; onBrowseGym: () => void; gymTaskId?: string | null; onExitGym?: () => void; onOpenQa?: () => void; annotatorEmail?: string; onSetAnnotator?: (email: string) => void }) {
  const mono = { fontFamily: t.fontMono } as const;
  const initial = (annotatorEmail || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 20,
        height: 56,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "0 20px",
        background: t.n9,
        borderBottom: `1px solid ${t.n7}`,
      }}
    >
      <img src="/deccan-ai-wordmark.svg" alt="Deccan AI" style={{ height: 22, width: "auto" }} />
      <Rule />
      <nav style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.8125rem" }}>
        <span style={{ color: t.n3 }}>Browser-Use Gym</span>
        <Icon name="chevronRight" size={14} stroke={1.6} color={t.n3} />
        <span style={{ color: t.n1, fontWeight: weight.semibold }}>Tasking</span>
      </nav>
      <Rule />
      {gymTaskId ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: "0.8125rem", fontWeight: weight.semibold, color: t.n1, whiteSpace: "nowrap" }}>
            Gym · <span style={mono}>{gymTaskId}</span>
          </span>
          <span onClick={onExitGym} style={{ marginLeft: 4, fontSize: "0.78125rem", fontWeight: weight.semibold, color: t.primary6, cursor: "pointer" }}>Samples</span>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }} title="One task at a time">
          <PagerBox dir="chevronLeft" onClick={onPrev} disabled={index <= 0} />
          <span style={{ fontSize: "0.8125rem", fontWeight: weight.semibold, color: t.n1, whiteSpace: "nowrap" }}>
            Task <span style={mono}>{index + 1}</span> of <span style={mono}>{total}</span>
          </span>
          <PagerBox dir="chevronRight" onClick={onNext} disabled={index >= total - 1} />
          <span onClick={onSkip} style={{ marginLeft: 4, fontSize: "0.78125rem", fontWeight: weight.semibold, color: t.primary6, cursor: "pointer" }}>Skip</span>
        </div>
      )}
      <span style={{ width: 1, height: 22, background: t.n7 }} />
      <span onClick={onBrowseGym} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: "0.78125rem", fontWeight: weight.semibold, color: t.primary6, cursor: "pointer", whiteSpace: "nowrap" }}>
        <Icon name="swap" size={14} /> Gym tasks
      </span>
      {onOpenQa && (
        <span onClick={onOpenQa} title="Multi-annotator QA — agreement + adjudication" style={{ fontSize: "0.78125rem", fontWeight: weight.semibold, color: t.primary6, cursor: "pointer", whiteSpace: "nowrap" }}>
          ⚖ QA review
        </span>
      )}
      <span style={{ flex: 1 }} />
      <FocusBadge>Multitab · Web Navigation</FocusBadge>
      <span title="You're annotating as this identity — change it to submit as a different annotator" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: "0.68rem", color: t.n3, fontWeight: weight.semibold, textTransform: "uppercase", letterSpacing: "0.06em" }}>as</span>
        <input
          value={annotatorEmail ?? ""}
          onChange={(e) => onSetAnnotator?.(e.target.value)}
          spellCheck={false}
          style={{ width: 168, padding: "5px 9px", borderRadius: t.radiusLg, border: `1px solid ${t.n6}`, background: t.n85, color: t.n1, fontFamily: t.fontMono, fontSize: "0.72rem", outline: "none" }}
        />
        <span style={{ width: 34, height: 34, borderRadius: t.radiusFull, background: t.primary7, color: t.n9, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "0.82rem", fontWeight: weight.bold, flexShrink: 0 }}>{initial}</span>
      </span>
    </header>
  );
}
