import type { CSSProperties, ReactNode } from "react";
import { t, tint, weight } from "./tokens";

type Tone = "neutral" | "tinted" | "idtag";

/**
 * Tag — small pill used for constraints, allowed-site chips, level type
 * chips, and monospace ID badges.
 * · neutral — neutrals-8 fill, neutrals-1 text, hairline border
 * · tinted  — 12%-of-`color` fill + `color` text (level chip, status)
 * · idtag   — delta-tag-id fill, mono, neutrals-6 border (e.g. GYM-2041)
 */
export function Tag({
  children,
  tone = "neutral",
  color,
  dot,
  style,
}: {
  children: ReactNode;
  tone?: Tone;
  color?: string;
  dot?: string;
  style?: CSSProperties;
}) {
  const tones: Record<Tone, CSSProperties> = {
    neutral: {
      background: t.n8,
      color: t.n1,
      border: `1px solid ${t.n7}`,
    },
    tinted: {
      background: tint(color ?? t.primary6, 12),
      color: color ?? t.primary6,
      border: "1px solid transparent",
    },
    idtag: {
      background: t.deltaTagId,
      color: t.n1,
      border: `1px solid ${t.n6}`,
      fontFamily: t.fontMono,
    },
  };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: dot ? 6 : 0,
        padding: "3px 9px",
        borderRadius: t.radiusSm,
        fontSize: "0.75rem",
        fontWeight: weight.semibold,
        lineHeight: 1,
        whiteSpace: "nowrap",
        ...tones[tone],
        ...style,
      }}
    >
      {dot && (
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: t.radiusFull,
            background: dot,
            flexShrink: 0,
          }}
        />
      )}
      {children}
    </span>
  );
}
