import { useState, type CSSProperties, type ReactNode } from "react";
import { t, weight } from "./tokens";

type Variant = "primary" | "secondary" | "soft";

/**
 * Button — DS spec: radius-lg, text-button (14px/600), transition-ui.
 * · primary   — primary-6 fill, white text, hover primary-7
 * · secondary — white fill, neutrals-6 border, neutrals-1 text
 * · soft      — primary-0 fill, primary-6 text (e.g. "Correct")
 */
export function Button({
  children,
  variant = "primary",
  disabled = false,
  onClick,
  leading,
  style,
}: {
  children: ReactNode;
  variant?: Variant;
  disabled?: boolean;
  onClick?: () => void;
  leading?: ReactNode;
  style?: CSSProperties;
}) {
  const [hover, setHover] = useState(false);

  const base: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    height: 34,
    padding: "0 14px",
    borderRadius: t.radiusLg,
    fontFamily: t.fontPrimary,
    fontSize: "0.8125rem",
    fontWeight: weight.semibold,
    lineHeight: 1,
    cursor: disabled ? "not-allowed" : "pointer",
    transition: t.transitionUi,
    whiteSpace: "nowrap",
    userSelect: "none",
    opacity: disabled ? 0.5 : 1,
  };

  const variants: Record<Variant, CSSProperties> = {
    primary: {
      background: hover && !disabled ? t.primary7 : t.primary6,
      color: t.n9,
      border: "1px solid transparent",
    },
    secondary: {
      background: hover && !disabled ? t.n85 : t.n9,
      color: t.n1,
      border: `1px solid ${t.n6}`,
    },
    soft: {
      background: hover && !disabled ? t.n85 : t.primary0,
      color: t.primary6,
      border: `1px solid transparent`,
    },
  };

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={disabled ? undefined : onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ ...base, ...variants[variant], ...style }}
    >
      {leading}
      {children}
    </button>
  );
}
