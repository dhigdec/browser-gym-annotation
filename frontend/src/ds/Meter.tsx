import type { CSSProperties } from "react";
import { t, weight } from "./tokens";

export type MeterState = "pending" | "pass" | "fail";

/**
 * Meter — the per-verifier score slot (DS Meter is documented for
 * "rubric scores and verifier pass rates"). A small square:
 * · pending — dashed neutral placeholder (before the benchmark runs)
 * · pass    — green-lite fill, green-dark "1"
 * · fail    — red-lite fill, red-dark "0"
 */
export function Meter({
  state,
  value,
  size = 22,
  style,
}: {
  state: MeterState;
  value?: number;
  size?: number;
  style?: CSSProperties;
}) {
  const shown = value ?? (state === "pass" ? 1 : state === "fail" ? 0 : "–");

  const skins: Record<MeterState, CSSProperties> = {
    pending: {
      background: "transparent",
      border: `1px dashed ${t.n5}`,
      color: t.n3,
    },
    pass: {
      background: t.greenLite,
      border: "1px solid transparent",
      color: t.greenDark,
    },
    fail: {
      background: t.redLite,
      border: "1px solid transparent",
      color: t.redDark,
    },
  };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        borderRadius: t.radiusMd,
        fontFamily: t.fontMono,
        fontSize: "0.75rem",
        fontWeight: weight.bold,
        ...skins[state],
        ...style,
      }}
    >
      {shown}
    </span>
  );
}
