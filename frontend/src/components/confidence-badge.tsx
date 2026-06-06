import clsx from "clsx";

/** Normalize an arbitrary confidence-level string into one of four canonical buckets. */
export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT";

export function normalizeLevel(level: string | null | undefined): ConfidenceLevel | null {
  if (!level) return null;
  const l = level.trim().toUpperCase();
  if (l.startsWith("HIGH")) return "HIGH";
  if (l.startsWith("MED")) return "MEDIUM";
  if (l.startsWith("LOW")) return "LOW";
  if (l.startsWith("INSUF") || l.startsWith("NONE") || l.startsWith("UNK")) return "INSUFFICIENT";
  return null;
}

/** Derive a confidence level by bucketing a 0–1 score (used when level is null). */
export function levelFromScore(score: number | null | undefined): ConfidenceLevel | null {
  if (score === null || score === undefined || Number.isNaN(score)) return null;
  if (score >= 0.7) return "HIGH";
  if (score >= 0.4) return "MEDIUM";
  if (score >= 0.2) return "LOW";
  return "INSUFFICIENT";
}

const LEVEL_STYLES: Record<ConfidenceLevel, string> = {
  HIGH: "bg-[var(--green-bg)] text-[var(--green)]",
  MEDIUM: "bg-[var(--orange-bg)] text-[var(--orange)]",
  LOW: "bg-[var(--red-bg)] text-[var(--red)]",
  INSUFFICIENT: "bg-[var(--bg-hover)] text-[var(--text-muted)]",
};

interface Props {
  level: ConfidenceLevel | null;
  score?: number | null;
  className?: string;
}

/** Small, reusable confidence-level pill consistent across panels and cards. */
export function ConfidenceBadge({ level, score, className }: Props) {
  if (!level) return null;
  const pct = score !== null && score !== undefined && !Number.isNaN(score) ? `${Math.round(score * 100)}%` : null;
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold transition-colors duration-300",
        LEVEL_STYLES[level],
        className
      )}
    >
      {level}
      {pct && <span className="tabular-nums opacity-80">{pct}</span>}
    </span>
  );
}
