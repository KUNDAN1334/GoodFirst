import { AlertTriangle, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { InlineCode } from "./inline-code";
import type { Evidence, EvidenceStatus } from "@/lib/types";

const STATUS: Record<EvidenceStatus, { icon: typeof CheckCircle2; color: string; label: string }> = {
  verified: { icon: CheckCircle2, color: "text-verified", label: "Verified" },
  unchecked: { icon: CircleDashed, color: "text-muted", label: "From the docs, not checkable" },
  flagged: { icon: AlertTriangle, color: "text-flagged", label: "Couldn't verify" },
  removed: { icon: XCircle, color: "text-removed", label: "Removed" },
};

const ANALYZE_GROUPS: EvidenceGroup[] = [
  { key: "repo", title: "Repo map" },
  { key: "issues", title: "Issues" },
];

export interface EvidenceGroup {
  key: Evidence["section"];
  title: string;
}

/**
 * The evidence list. `groups` splits rows by their `section`; a group whose key is
 * undefined collects every row (the CI explainer has a single section).
 */
export function EvidencePanel({
  evidence,
  adjustments,
  groups = ANALYZE_GROUPS,
}: {
  evidence: Evidence[];
  adjustments: string[];
  groups?: EvidenceGroup[];
}) {
  const count = (s: EvidenceStatus) => evidence.filter((e) => e.status === s).length;

  return (
    <section aria-labelledby="evidence-title" className="rounded-xl border border-rule bg-surface">
      <div className="border-b border-rule p-5">
        <h2 id="evidence-title" className="text-lg font-semibold">
          Evidence
        </h2>
        <p className="mt-1 text-sm text-muted">Every claim Gemma made, where it came from, and what the honesty check did.</p>
        <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
          <Stat value={count("verified")} label="verified" className="text-verified" />
          <Stat value={count("flagged")} label="flagged" className="text-flagged" />
          <Stat value={count("removed")} label="removed" className="text-removed" />
        </dl>
      </div>

      <div className="divide-y divide-rule">
        {groups.map(({ key, title }) => {
          const rows = key === undefined ? evidence : evidence.filter((e) => e.section === key);
          if (!rows.length) return null;
          return (
            <div key={key ?? "all"} className="p-5">
              <h3 className="text-sm font-semibold text-muted">{title}</h3>
              <ul className="mt-3 space-y-3.5">
                {rows.map((e, i) => (
                  <EvidenceRow key={i} e={e} />
                ))}
              </ul>
            </div>
          );
        })}

        {adjustments.length > 0 && (
          <div className="p-5">
            <h3 className="text-sm font-semibold text-muted">Adjustments</h3>
            <ul className="mt-2 space-y-1.5 text-sm text-ink/85">
              {adjustments.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

function Stat({ value, label, className }: { value: number; label: string; className: string }) {
  return (
    <div className="rounded-md bg-surface-2 py-2">
      <dt className="sr-only">{label}</dt>
      <dd>
        <span className={cn("block text-xl font-semibold tabular-nums", value ? className : "text-muted")}>{value}</span>
        <span className="text-xs text-muted">{label}</span>
      </dd>
    </div>
  );
}

function EvidenceRow({ e }: { e: Evidence }) {
  const { icon: Icon, color, label } = STATUS[e.status];
  const claim = e.claim.length > 160 ? e.claim.slice(0, 157) + "…" : e.claim;
  return (
    <li className="flex gap-2.5">
      <Icon className={cn("mt-0.5 size-4 shrink-0", color)} aria-label={label} />
      <div className="min-w-0 text-sm leading-snug">
        <p
          className={cn(
            "break-words",
            e.status === "removed" && "struck text-muted",
            e.status === "flagged" && "wavy",
          )}
        >
          <InlineCode text={claim} />
        </p>
        <p className="mt-1 text-xs text-muted">
          Source: <span className="font-mono">{e.source}</span>
        </p>
        {e.reason && e.status !== "verified" && (
          <p className={cn("mt-0.5 text-xs", e.status === "removed" ? "text-removed" : e.status === "flagged" ? "text-flagged" : "text-muted")}>
            {e.reason}
          </p>
        )}
      </div>
    </li>
  );
}
