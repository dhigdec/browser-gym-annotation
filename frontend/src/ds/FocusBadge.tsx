import type { CSSProperties, ReactNode } from "react";
import { t, tint, weight } from "./tokens";

/**
 * FocusBadge — page-level context label (e.g. "Multitab · Web Navigation").
 * DS spec: primary-7 text, 12%-primary-7 fill, 2px primary-7 border, radius-xl.
 */
export function FocusBadge({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        color: t.primary7,
        background: tint(t.primary7, 12),
        border: `2px solid ${t.primary7}`,
        borderRadius: t.radiusXl,
        fontWeight: weight.semibold,
        fontSize: "0.8rem",
        padding: "3px 12px",
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {children}
    </span>
  );
}
