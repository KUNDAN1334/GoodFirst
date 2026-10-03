import { cn, pct } from "@/lib/utils";

/**
 * Horizontal meter with a tick at the confidence floor. Below the floor the fill
 * turns amber: GoodFirst is saying "ask the maintainers before trusting this".
 */
export function ConfidenceMeter({
  value,
  floor,
  label = "Confidence",
  className,
}: {
  value: number;
  floor: number;
  label?: string;
  className?: string;
}) {
  const low = value < floor;
  return (
    <div className={cn("w-full", className)}>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-muted">{label}</span>
        <span className={cn("font-semibold tabular-nums", low ? "text-flagged" : "text-ink")}>{pct(value)}</span>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value * 100)}
        className="relative mt-2 h-2 rounded-full bg-rule"
      >
        <div
          className={cn("h-full rounded-full", low ? "bg-flagged" : "bg-verified")}
          style={{ width: `${Math.max(2, value * 100)}%` }}
        />
        <span
          aria-hidden
          className="absolute -top-1 -bottom-1 w-0.5 rounded bg-muted"
          style={{ left: `${floor * 100}%` }}
          title={`Below ${pct(floor)} GoodFirst suggests asking the maintainers`}
        />
      </div>
      <p className="mt-1.5 text-xs text-muted">
        {low ? `Below ${pct(floor)}: ask the maintainers before relying on this.` : `Above the ${pct(floor)} trust line.`}
      </p>
    </div>
  );
}
