import { FocusBadge, Icon, t, weight } from "../../../ds";

function Rule() {
  return <span style={{ width: 1, height: 22, background: t.n7, flexShrink: 0 }} />;
}

function PagerBox({ dir }: { dir: "chevronLeft" | "chevronRight" }) {
  return (
    <span
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
        cursor: "pointer",
      }}
    >
      <Icon name={dir} size={16} stroke={1.8} />
    </span>
  );
}

export function Header() {
  const mono = { fontFamily: t.fontMono } as const;
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
        <Icon name="chevronRight" size={14} stroke={1.6} color={t.n4} />
        <span style={{ color: t.n1, fontWeight: weight.semibold }}>Tasking</span>
      </nav>
      <Rule />
      <div style={{ display: "flex", alignItems: "center", gap: 8 }} title="One task at a time">
        <PagerBox dir="chevronLeft" />
        <span style={{ fontSize: "0.8125rem", fontWeight: weight.semibold, color: t.n1, whiteSpace: "nowrap" }}>
          Task <span style={mono}>4</span> of <span style={mono}>12</span>
        </span>
        <PagerBox dir="chevronRight" />
        <span style={{ marginLeft: 4, fontSize: "0.78rem", fontWeight: weight.semibold, color: t.primary6, cursor: "pointer" }}>
          Skip
        </span>
      </div>
      <span style={{ flex: 1 }} />
      <FocusBadge>Multitab · Web Navigation</FocusBadge>
      <span
        style={{
          width: 34,
          height: 34,
          borderRadius: t.radiusFull,
          background: t.primary7,
          color: t.n9,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "0.75rem",
          fontWeight: weight.bold,
        }}
      >
        QA
      </span>
    </header>
  );
}
