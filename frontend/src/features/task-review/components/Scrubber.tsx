import { Icon, t, weight, ACTION_COLOR } from "../../../ds";
import type { Step } from "../../../lib/types";

export function Scrubber({
  steps,
  step,
  playing,
  onPlayToggle,
  onStepTo,
}: {
  steps: Step[];
  step: number;
  playing: boolean;
  onPlayToggle: () => void;
  onStepTo: (i: number) => void;
}) {
  const total = steps.length;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "12px 16px", background: t.n9, border: `1px solid ${t.n7}`, borderRadius: t.radiusXl, boxShadow: t.shadowSm }}>
      <span style={{ color: t.n3, cursor: "pointer", display: "inline-flex" }} onClick={() => onStepTo(0)}>
        <Icon name="skipStart" size={20} color={t.n3} />
      </span>
      <span
        onClick={onPlayToggle}
        style={{ width: 44, height: 44, borderRadius: t.radiusFull, background: t.primary6, color: t.n9, display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: "pointer", flexShrink: 0 }}
      >
        <Icon name={playing ? "pause" : "play"} size={20} color={t.n9} />
      </span>
      <span style={{ color: t.n3, cursor: "pointer", display: "inline-flex" }} onClick={() => onStepTo(total - 1)}>
        <Icon name="skipEnd" size={20} color={t.n3} />
      </span>

      <span style={{ fontFamily: t.fontMono, fontSize: "0.9rem", fontWeight: weight.medium, color: t.n1, whiteSpace: "nowrap" }}>
        {step + 1} / {total}
      </span>

      <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 6, height: 20 }}>
        {steps.map((s, i) => {
          const color = ACTION_COLOR[s.type];
          const current = i === step;
          const played = i < step;
          return (
            <span
              key={s.idx}
              onClick={() => onStepTo(i)}
              title={`${s.idx}. ${s.type} — ${s.description}`}
              style={{
                flex: 1,
                height: current ? 18 : 9,
                borderRadius: t.radiusPill,
                cursor: "pointer",
                transition: t.transitionUi,
                background: current
                  ? color
                  : played
                    ? `color-mix(in srgb, ${color} 50%, ${t.n7})`
                    : t.n6,
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
