import { Button, Icon, Tag, t, weight, ACTION_COLOR } from "../../../ds";
import type { Step, Tab } from "../../../lib/types";

function StatusCircle({ done }: { done: boolean }) {
  if (done) {
    return (
      <span style={{ width: 18, height: 18, borderRadius: t.radiusFull, background: t.green, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Icon name="check" size={11} stroke={2.4} color={t.n9} />
      </span>
    );
  }
  return <span style={{ width: 18, height: 18, borderRadius: t.radiusFull, border: `2px solid ${t.n5}`, flexShrink: 0 }} />;
}

export function ActionTrace({
  steps,
  current,
  verifiedThrough,
  stepsApproved,
  remaining,
  tabs,
  onStepTo,
  onApproveRemaining,
}: {
  steps: Step[];
  current: number;
  verifiedThrough: number;
  stepsApproved: boolean;
  remaining: number;
  tabs: Tab[];
  onStepTo: (i: number) => void;
  onApproveRemaining: () => void;
}) {
  const titleOf = (id: string) => tabs.find((tb) => tb.id === id)?.title ?? id;
  return (
    <div style={{ height: 200, flexShrink: 0, background: t.n9, border: `1px solid ${t.n7}`, borderRadius: t.radiusXl, boxShadow: t.shadowMd, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: `1px solid ${t.n7}` }}>
        <span style={{ fontSize: "0.875rem", fontWeight: weight.bold, color: t.n0 }}>Action trace</span>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontFamily: t.fontMono, fontSize: "0.8125rem", color: stepsApproved ? t.greenDark : t.n2 }}>
            Reviewed {verifiedThrough} / {steps.length}
          </span>
          {stepsApproved ? (
            <Tag tone="tinted" color={t.green}>
              <Icon name="check" size={13} color={t.greenDark} style={{ marginRight: 4 }} /> Steps approved
            </Tag>
          ) : (
            <Button onClick={onApproveRemaining}>
              <Icon name="check" size={14} style={{ marginRight: 4 }} /> Approve remaining {remaining}
            </Button>
          )}
        </div>
      </div>

      <div style={{ overflowY: "auto" }}>
        {steps.map((s, i) => {
          const selected = i === current;
          const done = s.idx <= verifiedThrough;
          return (
            <div
              key={s.idx}
              onClick={() => onStepTo(i)}
              style={{
                display: "grid",
                gridTemplateColumns: "34px 24px 92px 1fr auto",
                alignItems: "center",
                gap: 10,
                padding: "9px 16px",
                cursor: "pointer",
                background: selected ? t.surfaceTint : "transparent",
                boxShadow: selected ? `inset 3px 0 0 ${t.primary6}` : "none",
                transition: t.transitionUi,
              }}
            >
              <span style={{ fontFamily: t.fontMono, fontSize: "0.8125rem", color: t.n3 }}>{String(s.idx).padStart(2, "0")}</span>
              <StatusCircle done={done} />
              <span style={{ fontSize: "0.72rem", fontWeight: weight.bold, letterSpacing: "0.03em", textTransform: "uppercase", color: ACTION_COLOR[s.type] }}>{s.type}</span>
              <span style={{ fontSize: "0.875rem", color: t.n1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.description}</span>
              <span style={{ fontSize: "0.8125rem", color: t.n3, fontFamily: t.fontMono }}>{titleOf(s.tabId)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
