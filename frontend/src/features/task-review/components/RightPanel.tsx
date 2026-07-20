import type { ReactNode } from "react";
import { Icon, Tag, t, weight } from "../../../ds";
import type { Metric, Task } from "../../../lib/types";

function Label({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "18px 0 8px" }}>
      <span style={{ fontSize: "0.6875rem", fontWeight: weight.semibold, letterSpacing: "0.04em", color: t.n3, textTransform: "uppercase" }}>
        {children}
      </span>
      {action}
    </div>
  );
}

function metricColor(tone: Metric["tone"]) {
  if (tone === "error") return t.red;
  if (tone === "success") return t.greenDark;
  return t.n0;
}

export function RightPanel({ task, summary }: { task: Task; summary: Metric[] }) {
  return (
    <aside
      style={{
        width: 360,
        flexShrink: 0,
        background: t.n9,
        border: `1px solid ${t.n7}`,
        borderRadius: t.radiusXl,
        boxShadow: t.shadowMd,
        padding: "16px 18px",
        overflowY: "auto",
      }}
    >
      {/* id + priority */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Tag tone="idtag">{task.id}</Tag>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.8125rem", fontWeight: weight.semibold, color: t.red }}>
          <span style={{ width: 7, height: 7, borderRadius: t.radiusFull, background: t.red }} />
          {task.priority}
        </span>
      </div>

      <h1 style={{ margin: "12px 0 4px", fontSize: "1.15rem", lineHeight: 1.25, fontWeight: weight.bold, color: t.n0, letterSpacing: "-0.01em" }}>
        {task.title}
      </h1>
      <div style={{ fontSize: "0.8125rem", color: t.n3 }}>{task.meta}</div>

      <Label action={<span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: "0.75rem", fontWeight: weight.semibold, color: t.primary6, cursor: "pointer" }}><Icon name="pencil" size={13} /> Edit</span>}>
        Task prompt
      </Label>
      <p style={{ margin: 0, fontSize: "0.84rem", lineHeight: 1.5, color: t.n1 }}>{task.prompt}</p>

      <Label>Start state</Label>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.8125rem", color: t.n2 }}>
        <span style={{ width: 6, height: 6, borderRadius: t.radiusFull, background: t.n4 }} />
        {task.startState.summary}
      </div>
      <div style={{ marginTop: 8, padding: "8px 12px", background: t.n85, border: `1px solid ${t.n7}`, borderRadius: t.radiusLg, fontFamily: t.fontMono, fontSize: "0.8rem", color: t.n1, overflowX: "auto" }}>
        {task.startState.url}
      </div>

      <Label>Constraints</Label>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {task.constraints.map((c) => (
          <Tag key={c}>{c}</Tag>
        ))}
      </div>

      <Label>Allowed sites</Label>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {task.allowedSites.map((sIt) => (
          <Tag key={sIt.host} dot={sIt.color}>{sIt.host}</Tag>
        ))}
      </div>

      <Label>Run summary</Label>
      <div style={{ border: `1px solid ${t.n7}`, borderRadius: t.radiusLg, padding: 16, display: "grid", gridTemplateColumns: "1fr 1fr", rowGap: 16, columnGap: 12 }}>
        {summary.map((m) => (
          <div key={m.label}>
            <div style={{ fontFamily: t.fontMono, fontSize: "1.5rem", fontWeight: weight.bold, lineHeight: 1, color: metricColor(m.tone) }}>{m.value}</div>
            <div style={{ marginTop: 4, fontSize: "0.75rem", color: t.n3 }}>{m.label}</div>
          </div>
        ))}
      </div>
    </aside>
  );
}
