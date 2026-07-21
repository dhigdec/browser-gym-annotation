import { Icon, t, weight, ACTION_COLOR } from "../../../ds";
import type { Step, Tab } from "../../../lib/types";
import type { StepStatus } from "../../../lib/reviewMachine";

/** Four status-circle variants (spec §2.3): verified · corrected · re-run · pending. */
function StatusCircle({ variant }: { variant: StepStatus }) {
  if (variant === "verified") {
    return (
      <span style={{ width: 16, height: 16, borderRadius: t.radiusFull, background: t.green, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Icon name="check" size={10} stroke={2.8} color={t.n9} />
      </span>
    );
  }
  if (variant === "corrected") {
    return (
      <span style={{ width: 16, height: 16, borderRadius: t.radiusFull, background: t.primary6, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Icon name="pencil" size={9} stroke={2} color={t.n9} />
      </span>
    );
  }
  const ring = variant === "rerun" ? ACTION_COLOR.tab : t.n5;
  return (
    <span style={{ width: 16, height: 16, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
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
    <div style={{ height: 184, flexShrink: 0, background: t.n9, border: `1px solid ${t.n7}`, borderRadius: t.radiusXl, boxShadow: t.shadowMd, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 16px", borderBottom: `1px solid ${t.n7}`, flexShrink: 0 }}>
        <span style={{ fontSize: "0.8125rem", fontWeight: weight.bold, color: t.n1 }}>Action trace</span>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontFamily: t.fontMono, fontSize: "0.719rem", fontWeight: weight.bold, color: t.greenDark }}>
            Reviewed {verifiedThrough} / {steps.length}
          </span>
          {stepsApproved ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 11px", borderRadius: 7, background: t.greenLite, color: t.greenDark, fontSize: "0.75rem", fontWeight: weight.bold }}>
              <Icon name="check" size={13} stroke={2.4} color={t.greenDark} /> Steps approved
            </span>
          ) : (
            <span onClick={onApproveRemaining} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 7, background: t.primary6, border: `1px solid ${t.primary6}`, color: t.n9, fontSize: "0.75rem", fontWeight: weight.bold, cursor: "pointer" }}>
              <Icon name="check" size={14} stroke={2.2} color={t.n9} /> {reviewedAll ? "Approve all steps" : `Approve remaining ${remaining}`}
            </span>
          )}
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
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
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "9px 16px",
                  cursor: "pointer",
                  background: selected ? t.surfaceTint : "transparent",
                  borderLeft: `2px solid ${selected ? t.primary6 : "transparent"}`,
                  transition: t.transitionUi,
                }}
              >
                <span style={{ fontFamily: t.fontMono, fontSize: "0.719rem", color: t.n3, width: 22, flexShrink: 0 }}>{String(s.idx).padStart(2, "0")}</span>
                <StatusCircle variant={variant} />
                <span style={{ width: 8, height: 8, borderRadius: t.radiusFull, background: ACTION_COLOR[s.type], flexShrink: 0 }} />
                <span style={{ fontSize: "0.625rem", fontWeight: weight.bold, letterSpacing: "0.04em", textTransform: "uppercase", color: ACTION_COLOR[s.type], width: 64, flexShrink: 0 }}>{s.type}</span>
                <span style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: "0.8125rem", color: t.n1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.description}</span>
                  {variant === "rerun" && (
                    <span style={{ flexShrink: 0, fontSize: "0.594rem", fontWeight: weight.bold, textTransform: "uppercase", letterSpacing: "0.04em", color: pink, background: `color-mix(in srgb, ${pink} 12%, transparent)`, padding: "2px 6px", borderRadius: t.radiusSm }}>re-run</span>
                  )}
                </span>
                <span style={{ fontSize: "0.6875rem", color: t.n3, fontFamily: t.fontMono, flexShrink: 0 }}>{titleOf(s.tabId)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
