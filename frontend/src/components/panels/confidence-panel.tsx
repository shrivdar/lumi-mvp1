"use client";

import { useEffect, useMemo, useState } from "react";
import type { AgentTrace, HitlRequest } from "@/lib/types";
import {
  ConfidenceBadge,
  normalizeLevel,
  levelFromScore,
  type ConfidenceLevel,
} from "@/components/confidence-badge";
import { Gauge, Users } from "lucide-react";

interface Props {
  traces: AgentTrace[];
  hitlEvents: HitlRequest[];
}

const LEVEL_ORDER: ConfidenceLevel[] = ["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"];

const LEVEL_BAR: Record<ConfidenceLevel, string> = {
  HIGH: "var(--green)",
  MEDIUM: "var(--orange)",
  LOW: "var(--red)",
  INSUFFICIENT: "var(--text-muted)",
};

/** Pick the gauge color for an overall 0–1 confidence index. */
function gaugeColor(score: number): string {
  if (score >= 0.7) return "var(--green)";
  if (score >= 0.4) return "var(--orange)";
  return "var(--red)";
}

/** Animated radial arc gauge built with inline SVG (no chart lib). */
function ConfidenceGauge({ value }: { value: number }) {
  // value: 0–1. Sweep a 270° arc.
  const [animated, setAnimated] = useState(0);
  useEffect(() => {
    const t = requestAnimationFrame(() => setAnimated(value));
    return () => cancelAnimationFrame(t);
  }, [value]);

  const size = 132;
  const stroke = 11;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const sweep = 270; // degrees of usable arc
  const startAngle = 135; // start bottom-left, sweep clockwise
  const circumference = 2 * Math.PI * r;
  const arcLen = (sweep / 360) * circumference;
  const dash = arcLen * animated;
  const color = gaugeColor(value);
  const pct = Math.round(value * 100);

  return (
    <div className="relative flex items-center justify-center">
      <svg width={size} height={size} className="-rotate-90" style={{ transform: `rotate(${startAngle - 90}deg)` }}>
        {/* Track */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="var(--bg-hover)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${arcLen} ${circumference}`}
        />
        {/* Value arc */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          style={{ transition: "stroke-dasharray 1s cubic-bezier(0.4,0,0.2,1)" }}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="text-3xl font-semibold tabular-nums leading-none" style={{ color }}>
          {pct}
          <span className="text-base font-normal text-[var(--text-muted)]">%</span>
        </span>
        <span className="mt-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Confidence</span>
      </div>
    </div>
  );
}

export function ConfidencePanel({ traces, hitlEvents }: Props) {
  // Only completed traces with a numeric score contribute to the index.
  const scored = useMemo(
    () =>
      traces.filter(
        (t) => t.confidence_score !== null && t.confidence_score !== undefined && !Number.isNaN(t.confidence_score)
      ),
    [traces]
  );

  const meanScore = useMemo(() => {
    if (scored.length === 0) return 0;
    return scored.reduce((s, t) => s + (t.confidence_score ?? 0), 0) / scored.length;
  }, [scored]);

  const distribution = useMemo(() => {
    const counts: Record<ConfidenceLevel, number> = { HIGH: 0, MEDIUM: 0, LOW: 0, INSUFFICIENT: 0 };
    for (const t of traces) {
      const lvl = normalizeLevel(t.confidence_level) ?? levelFromScore(t.confidence_score);
      if (lvl) counts[lvl] += 1;
    }
    return counts;
  }, [traces]);

  const maxCount = Math.max(1, ...Object.values(distribution));

  // Per-agent rows sorted ascending so the weakest surface at the top.
  const perAgent = useMemo(
    () =>
      [...scored].sort((a, b) => (a.confidence_score ?? 0) - (b.confidence_score ?? 0)),
    [scored]
  );

  const totalGraded = Object.values(distribution).reduce((s, n) => s + n, 0);

  // Empty state — no traces have arrived yet.
  if (traces.length === 0) {
    return (
      <div className="space-y-3 py-2">
        <div className="flex flex-col items-center justify-center py-10 text-center animate-fade-in">
          <Gauge size={26} className="text-[var(--border)] mb-3" />
          <p className="text-xs text-[var(--text-muted)]">Awaiting agent results…</p>
          <p className="text-[10px] text-[var(--text-muted)] mt-1">Confidence updates as agents complete</p>
        </div>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-8 rounded-lg shimmer" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Overall Confidence Index */}
      <div className="flex flex-col items-center animate-fade-in">
        {scored.length > 0 ? (
          <ConfidenceGauge value={meanScore} />
        ) : (
          <div className="flex h-[132px] flex-col items-center justify-center text-center">
            <Gauge size={22} className="text-[var(--border)] mb-2" />
            <p className="text-[11px] text-[var(--text-muted)]">No scored findings yet</p>
          </div>
        )}
        <p className="mt-1 text-[10px] text-[var(--text-muted)] tabular-nums">
          Mean across {scored.length} completed {scored.length === 1 ? "agent" : "agents"}
        </p>
      </div>

      {/* Distribution by confidence level */}
      <div className="animate-fade-in" style={{ animationDelay: "80ms" }}>
        <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
          Distribution
        </p>
        <div className="space-y-2">
          {LEVEL_ORDER.map((lvl, i) => {
            const count = distribution[lvl];
            const width = totalGraded > 0 ? (count / maxCount) * 100 : 0;
            return (
              <div key={lvl} className="flex items-center gap-2">
                <span className="w-[78px] shrink-0 text-[10px] font-medium text-[var(--text-secondary)]">
                  {lvl}
                </span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--bg-hover)]">
                  <div
                    className="h-2 rounded-full"
                    style={{
                      width: `${width}%`,
                      background: LEVEL_BAR[lvl],
                      transition: "width 0.8s cubic-bezier(0.4,0,0.2,1)",
                      transitionDelay: `${i * 80}ms`,
                    }}
                  />
                </div>
                <span className="w-4 shrink-0 text-right text-[10px] tabular-nums text-[var(--text-muted)]">
                  {count}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Per-agent confidence */}
      {perAgent.length > 0 && (
        <div className="animate-fade-in" style={{ animationDelay: "160ms" }}>
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
            Per-agent (weakest first)
          </p>
          <div className="space-y-1.5">
            {perAgent.map((t, i) => {
              const score = t.confidence_score ?? 0;
              const pct = Math.round(score * 100);
              const lvl = normalizeLevel(t.confidence_level) ?? levelFromScore(score);
              const barColor = lvl ? LEVEL_BAR[lvl] : "var(--text-muted)";
              return (
                <div
                  key={`${t.agent_id}-${i}`}
                  className="rounded-lg px-2 py-1.5 transition-colors hover:bg-[var(--bg-hover)] animate-slide-up"
                  style={{ animationDelay: `${i * 40}ms` }}
                >
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-[var(--text)]">
                      {t.agent_id}
                    </span>
                    {t.division && (
                      <span className="shrink-0 text-[9px] text-[var(--text-muted)]">{t.division}</span>
                    )}
                    <span className="shrink-0 text-[10px] tabular-nums text-[var(--text-secondary)]">{pct}%</span>
                  </div>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-[var(--bg-hover)]">
                    <div
                      className="h-1 rounded-full"
                      style={{
                        width: `${pct}%`,
                        background: barColor,
                        transition: "width 0.8s cubic-bezier(0.4,0,0.2,1)",
                        transitionDelay: `${i * 40}ms`,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Human-review queue */}
      <div className="animate-fade-in" style={{ animationDelay: "240ms" }}>
        <p className="mb-2 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
          <Users size={11} />
          Human-review queue
        </p>
        {hitlEvents.length === 0 ? (
          <p className="rounded-lg border border-dashed border-[var(--border)] px-3 py-3 text-center text-[10px] text-[var(--text-muted)]">
            No findings routed for review
          </p>
        ) : (
          <div className="space-y-1.5">
            {hitlEvents.map((h, i) => {
              const statusStyle =
                h.status === "approved"
                  ? "border-[var(--green)] bg-[var(--green-bg)] text-[var(--green)]"
                  : h.status === "rejected"
                    ? "border-[var(--red)] bg-[var(--red-bg)] text-[var(--red)]"
                    : "border-[var(--orange)] bg-[var(--orange-bg)] text-[var(--orange)]";
              return (
                <div
                  key={`${h.finding_id}-${i}`}
                  className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2.5 py-2 animate-slide-up"
                  style={{ animationDelay: `${i * 50}ms` }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-mono text-[10px] text-[var(--text-muted)]">{h.agent_id}</span>
                    <span
                      className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold capitalize ${statusStyle}`}
                    >
                      {h.status}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-[var(--text-secondary)]">
                    {h.reason || h.finding}
                  </p>
                  <div className="mt-1.5">
                    <ConfidenceBadge level={levelFromScore(h.confidence_score)} score={h.confidence_score} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
