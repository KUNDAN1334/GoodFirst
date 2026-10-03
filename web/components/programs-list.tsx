"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Check, Info } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  PROGRAMS,
  STATUS_ORDER,
  VERIFIED_ON,
  day,
  formatDate,
  phaseState,
  statusFor,
  type Program,
  type ProgramStatus,
} from "@/lib/programs";

export function ProgramsList() {
  // Server render and first client render both use the verification date, so they match.
  // Right after mounting we switch to the real date, and statuses update on their own.
  const [today, setToday] = useState<Date>(() => day(VERIFIED_ON));
  useEffect(() => setToday(new Date()), []);

  const rows = useMemo(() => {
    return PROGRAMS.map((p) => ({ program: p, status: statusFor(p, today) })).sort(
      (a, b) => STATUS_ORDER.indexOf(a.status.kind) - STATUS_ORDER.indexOf(b.status.kind),
    );
  }, [today]);

  const actionable = rows.filter((r) => r.status.kind === "open" || r.status.kind === "live").length;

  return (
    <div>
      <p className="text-sm text-muted">
        {actionable} live or open right now. Dates checked against each program&apos;s official site on{" "}
        {formatDate(VERIFIED_ON)}; statuses update automatically from those dates. Always confirm on the official site
        before you plan around a deadline.
      </p>
      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        {rows.map(({ program, status }) => (
          <ProgramCard key={program.id} program={program} status={status} today={today} />
        ))}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: ProgramStatus }) {
  const tone =
    status.kind === "open" || status.kind === "live" ? "verified" : status.kind === "not_announced" ? "neutral" : "flagged";
  return (
    <Badge tone={tone} className="shrink-0">
      {(status.kind === "open" || status.kind === "live") && (
        <span className="size-1.5 rounded-full bg-verified" aria-hidden />
      )}
      {status.label}
    </Badge>
  );
}

function ProgramCard({ program, status, today }: { program: Program; status: ProgramStatus; today: Date }) {
  const edition = status.edition;
  return (
    <article className="flex flex-col rounded-lg border border-rule bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg leading-snug font-semibold">
            <a href={program.url} target="_blank" rel="noreferrer" className="hover:underline">
              {program.name}
            </a>
          </h2>
          <p className="mt-0.5 text-sm text-muted">
            {program.organizer ?? " "}
            {program.stipend && <span className="ml-2 text-verified">Stipend</span>}
          </p>
        </div>
        <StatusBadge status={status} />
      </div>

      <p className="mt-3 text-[0.95rem] leading-relaxed">{program.summary}</p>
      <p className={cn("mt-2 text-sm", status.kind === "open" || status.kind === "live" ? "text-verified" : "text-muted")}>
        {status.detail}
      </p>

      {program.heads_up && (
        <p className="mt-3 flex gap-2 rounded-md bg-flagged-wash px-3 py-2 text-sm text-ink">
          <Info className="mt-0.5 size-4 shrink-0 text-flagged" aria-hidden />
          {program.heads_up}
        </p>
      )}

      {edition && (
        <div className="mt-4">
          <p className="text-sm font-medium">{edition.label}</p>
          <ol className="mt-2 space-y-1.5">
            {edition.phases.map((phase) => {
              const state = phaseState(phase, today);
              return (
                <li key={phase.name} className="flex flex-wrap items-start gap-x-2.5 gap-y-0.5 text-sm">
                  <span
                    aria-hidden
                    className={cn(
                      "mt-1 flex size-3.5 shrink-0 items-center justify-center rounded-full border",
                      state === "past" && "border-rule-strong bg-surface-2 text-muted",
                      state === "current" && "border-verified bg-verified",
                      state === "future" && "border-rule-strong",
                    )}
                  >
                    {state === "past" && <Check className="size-2.5" />}
                  </span>
                  <span className={cn("flex-1", state === "past" && "text-muted")}>{phase.name}</span>
                  <span className={cn("ml-auto shrink-0 font-mono text-xs tabular-nums", state === "current" ? "text-verified" : "text-muted")}>
                    {formatDate(phase.start)}
                    {phase.end && ` – ${formatDate(phase.end)}`}
                  </span>
                </li>
              );
            })}
          </ol>
          {edition.note && <p className="mt-2 text-xs text-muted">{edition.note}</p>}
        </div>
      )}

      {program.pattern && <p className="mt-3 text-xs text-muted">{program.pattern}</p>}

      <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 pt-4 text-sm">
        <a
          href={program.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 font-medium text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
        >
          Official site <ArrowUpRight className="size-3.5" aria-hidden />
        </a>
        {program.sources.map((s) => (
          <a
            key={s.url}
            href={s.url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-muted underline decoration-rule underline-offset-4 hover:text-ink"
          >
            Source: {s.label}
          </a>
        ))}
      </div>
    </article>
  );
}
