"use client";

import { useEffect, useState } from "react";
import { Check, CircleSlash, Loader2, X } from "lucide-react";
import { cn, formatSeconds } from "@/lib/utils";
import type { StepName, StepStatus } from "@/lib/types";

export interface StepState {
  status: StepStatus;
  seconds?: number;
  detail?: string;
  startedAt?: number;
}

export interface StepDefinition {
  name: string;
  title: string;
  hint: string;
}

export const STEPS: (StepDefinition & { name: StepName })[] = [
  { name: "fetching", title: "Reading the repo on GitHub", hint: "README, contributing guide, file list and beginner issues" },
  { name: "explaining", title: "Gemma reads the docs", hint: "Answers your question from the docs. Local model on your CPU, usually 30 to 90 seconds" },
  { name: "picking", title: "Choosing issues for you", hint: "Code ranks the issues, Gemma picks three and explains why" },
  { name: "honesty_check", title: "Checking every claim", hint: "Files, issues and commands are compared with what GitHub returned" },
];

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

export function ProgressTimeline({
  steps,
  repo,
  question,
  definitions = STEPS,
  label = "Analyzing",
}: {
  steps: Record<string, StepState>;
  repo: string;
  question?: string;
  definitions?: StepDefinition[];
  label?: string;
}) {
  const running = Object.values(steps).some((s) => s.status === "started");
  const now = useNow(running);

  return (
    <section aria-labelledby="progress-title">
      <h2 id="progress-title" className="text-sm text-muted">
        {label} <span className="font-mono text-ink">{repo}</span>
      </h2>
      {question && (
        <p className="mt-1 max-w-[68ch] text-sm text-muted">
          Question: <q className="text-ink">{question}</q>
        </p>
      )}
      <ol className="mt-4" aria-live="polite">
        {definitions.map((step, i) => {
          const s = steps[step.name];
          const elapsed =
            s.status === "started" && s.startedAt ? (now - s.startedAt) / 1000 : s.seconds;
          const last = i === definitions.length - 1;
          return (
            <li key={step.name} className="relative flex gap-4 pb-6 last:pb-0">
              {!last && (
                <span
                  aria-hidden
                  className={cn(
                    "absolute top-8 bottom-0 left-[15px] w-px",
                    s.status === "done" || s.status === "skipped" ? "bg-verified/50" : "bg-rule",
                  )}
                />
              )}
              <StepIcon status={s.status} index={i + 1} />
              <div className="min-w-0 flex-1 pt-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                  <p className={cn("font-medium", s.status === "pending" && "text-muted")}>{step.title}</p>
                  {elapsed !== undefined && s.status !== "skipped" && (
                    <span className="font-mono text-sm text-muted tabular-nums">{formatSeconds(elapsed)}</span>
                  )}
                </div>
                <p
                  className={cn(
                    "mt-0.5 text-sm",
                    s.status === "failed" ? "text-removed" : "text-muted",
                  )}
                >
                  {s.status === "done" || s.status === "failed" || s.status === "skipped"
                    ? s.detail || step.hint
                    : step.hint}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function StepIcon({ status, index }: { status: StepStatus; index: number }) {
  const base = "relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full border text-sm";
  switch (status) {
    case "started":
      return (
        <span className={cn(base, "border-ink bg-surface")}>
          <Loader2 className="size-4 animate-spin" aria-label="In progress" />
        </span>
      );
    case "done":
      return (
        <span className={cn(base, "border-verified bg-verified-wash text-verified")}>
          <Check className="size-4" aria-label="Done" />
        </span>
      );
    case "failed":
      return (
        <span className={cn(base, "border-removed bg-removed-wash text-removed")}>
          <X className="size-4" aria-label="Failed" />
        </span>
      );
    case "skipped":
      return (
        <span className={cn(base, "border-rule bg-surface text-muted")}>
          <CircleSlash className="size-4" aria-label="Skipped" />
        </span>
      );
    default:
      return <span className={cn(base, "border-rule bg-surface font-mono text-muted")}>{index}</span>;
  }
}
