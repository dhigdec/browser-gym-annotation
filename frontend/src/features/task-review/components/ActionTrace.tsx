import { Button, Icon, Tag, t, weight, ACTION_COLOR } from "../../../ds";
import type { Step, Tab } from "../../../lib/types";
import type { StepStatus } from "../../../lib/reviewMachine";

/** Four status-circle variants (spec §2.3): verified · corrected · re-run · pending. */
function StatusCircle({ variant }: { variant: StepStatus }) {
  if (variant === "verified") {
    return (
      <span style={{ width: 18, height: 18, borderRadius: t.radiusFull, background: t.green, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Icon name="check" size={11} stroke={2.6} color={t.n9} />
      </span>
    );
  }
  if (variant === "corrected") {
    return (
      <span style={{ width: 18, height: 18, borderRadius: t.radiusFull, background: t.primary6, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Icon name="pencil" size={10} stroke={2} color={t.n9} />
      </span>
    );
  }
  // re-run / pending → hollow ring (pink for re-run, grey for pending)
  const ring = variant === "rerun" ? ACTION_COLOR.tab : t.n5;
  return (
    <span style={{ width: 18, height: 18, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
      <span style={{ width: 11, height: 11, borderRadius: t.radiusFull, border: `2px solid ${ring}` }} />
    </span>
  );
}

function statusOf(step: Step, verifiedThrough: number, rerunFrom: number | null): StepStatus {
  if (rerunFrom != null) {
    if (step.idx === rerunFrom) return "corrected";
    if (step.idx > rerunFrom) return "rerun";
  }
  return step.idx <= verifiedThrough ? "verified" : "pending";
}

export function ActionTrace({
  steps,
  current,
  verifiedThrough,
  stepsApproved,
  remaining,
  rerunFrom,
  rerunMode,
  tabs,
  onStepTo,
  onApproveRemaining,
}: {
  steps: Step[];
  current: number;
  verifiedThrough: number;
  stepsApproved: boolean;
  remaining: number;
  rerunFrom: number | null;
  rerunMode: string | null;
  tabs: Tab[];
  onStepTo: (i: number) => void;
  onApproveRemaining: () => void;
}) {
  const modeLabel = rerunMode === "agent" ? " · via live agent" : rerunMode === "deterministic" ? " · via oracle" : "";
  const titleOf = (id: string) => tabs.find((tb) => tb.id === id)?.title ?? id;
  const pink = ACTION_COLOR.tab;
  const reviewedAll = verifiedThrough >= steps.length;
  const forkAt = rerunFrom == null ? -1 : steps.findIndex((s) => s.idx > rerunFrom);

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
              <Icon name="check" size={14} style={{ marginRight: 4 }} /> {reviewedAll ? "Approve all steps" : `Approve remaining ${remaining}`}
            </Button>
          )}
        </div>
      </div>

      <div style={{ overflowY: "auto" }}>
        {steps.map((s, i) => {
          const selected = i === current;
          const variant = statusOf(s, verifiedThrough, rerunFrom);
          return (
            <div key={s.idx}>
              {i === forkAt && (
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 16px", background: `color-mix(in srgb, ${pink} 6%, ${t.n9})` }}>
                  <Icon name="branch" size={13} color={pink} />
                  <span style={{ fontSize: "0.72rem", fontWeight: weight.bold, color: pink }}>Re-ran from step {rerunFrom} — correction applied{modeLabel}</span>
                </div>
              )}
              <div
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
                <StatusCircle variant={variant} />
                <span style={{ fontSize: "0.72rem", fontWeight: weight.bold, letterSpacing: "0.03em", textTransform: "uppercase", color: ACTION_COLOR[s.type] }}>{s.type}</span>
                <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <span style={{ fontSize: "0.875rem", color: t.n1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.description}</span>
                  {variant === "rerun" && (
                    <span style={{ flexShrink: 0, fontSize: "0.6rem", fontWeight: weight.bold, textTransform: "uppercase", letterSpacing: "0.04em", color: pink, background: `color-mix(in srgb, ${pink} 12%, transparent)`, padding: "2px 6px", borderRadius: t.radiusSm }}>re-run</span>
                  )}
                </span>
                <span style={{ fontSize: "0.8125rem", color: t.n3, fontFamily: t.fontMono }}>{titleOf(s.tabId)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
