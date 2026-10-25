import type { ReactNode } from "react";

/** Shared compact label for incident metadata and seek actions. */
export default function TraceBadge({ children, className = "", onClick, "aria-label": ariaLabel }: {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  "aria-label"?: string;
}) {
  const classes = `trace-badge ${className}`;
  return onClick
    ? <button type="button" className={classes} onClick={onClick} aria-label={ariaLabel}>{children}</button>
    : <span className={classes} aria-label={ariaLabel}>{children}</span>;
}
