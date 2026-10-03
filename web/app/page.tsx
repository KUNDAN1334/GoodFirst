"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ExternalLink, Info, RotateCcw, Square, Star } from "lucide-react";
import { AnalyzeForm, Hero } from "@/components/analyze-form";
import { ProgressTimeline, STEPS, type StepState } from "@/components/progress-timeline";
import { AskMaintainer } from "@/components/results/ask-maintainer";
import { ConfidenceMeter } from "@/components/results/confidence-meter";
import { EvidencePanel } from "@/components/results/evidence-panel";
import { IssueCards } from "@/components/results/issue-cards";
import { RepoMap } from "@/components/results/repo-map";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { analyze, getHealth, type AnalyzeInput } from "@/lib/api";
import type { AnalyzeResult, Health } from "@/lib/types";
import { formatSeconds } from "@/lib/utils";

type Phase = "idle" | "running" | "done" | "error";

const freshSteps = (): Record<string, StepState> =>
  Object.fromEntries(STEPS.map((s) => [s.name, { status: "pending" }]));

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [input, setInput] = useState<AnalyzeInput>({ repo: "", question: "", language: "english" });
  const [steps, setSteps] = useState(freshSteps);
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null | undefined>(undefined);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    getHealth().then(setHealth);
  }, []);

  const start = useCallback((next: AnalyzeInput) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setInput(next);
    setSteps(freshSteps());
    setResult(null);
    setError(null);
    setPhase("running");
    window.scrollTo({ top: 0 });

    analyze(
      next,
      {
        onStep: (e) =>
          setSteps((prev) => ({
            ...prev,
            [e.step]: {
              ...prev[e.step],
              status: e.status,
              seconds: e.seconds,
              detail: e.detail,
              startedAt: e.status === "started" ? Date.now() : prev[e.step].startedAt,
            },
          })),
        onResult: (r) => {
          setResult(r);
          setPhase("done");
        },
        onError: (message) => {
          setError(message);
          setPhase("error");
          setSteps((prev) => {
            const copy = { ...prev };
            for (const k of Object.keys(copy)) {
              if (copy[k].status === "started") copy[k] = { ...copy[k], status: "failed", detail: "Stopped" };
            }
            return copy;
          });
        },
      },
      controller.signal,
    );
  }, []);

  const cancel = () => {
    abortRef.current?.abort();
    setPhase("idle");
  };

  const reset = () => {
    abortRef.current?.abort();
    setPhase("idle");
    getHealth().then(setHealth);
  };

  return (
    <div className="min-h-dvh">
      <SiteHeader onHome={reset} />

      <main className="mx-auto max-w-6xl px-4 pt-6 pb-16 sm:px-6 sm:pt-8">
        {phase === "idle" && (
          <div className="grid grid-cols-1 gap-10 lg:min-h-[calc(100dvh-9.5rem-1px)] lg:grid-cols-[1.1fr_1fr] lg:items-center lg:gap-14">
            <div className="min-w-0">
              <Hero />
            </div>
            <AnalyzeForm initial={input} health={health} onSubmit={start} />
          </div>
        )}

        {phase !== "idle" && (
          <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-12">
            <div className="min-w-0 space-y-12">
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="ghost" size="sm" onClick={reset}>
                  <ArrowLeft /> New analysis
                </Button>
                {phase === "running" && (
                  <Button variant="ghost" size="sm" onClick={cancel}>
                    <Square /> Stop
                  </Button>
                )}
                {phase !== "running" && (
                  <Button variant="ghost" size="sm" onClick={() => start(input)}>
                    <RotateCcw /> Run again
                  </Button>
                )}
              </div>

              {phase === "running" && (
                <>
                  <ProgressTimeline steps={steps} repo={input.repo} question={input.question} />
                  <ResultsSkeleton />
                </>
              )}

              {phase === "error" && (
                <>
                  <ProgressTimeline steps={steps} repo={input.repo} question={input.question} />
                  <div role="alert" className="rounded-lg border border-removed/40 bg-removed-wash p-5">
                    <p className="font-semibold text-removed">The analysis stopped</p>
                    <p className="mt-1 max-w-[68ch]">{error}</p>
                  </div>
                </>
              )}

              {phase === "done" && result && <Results result={result} />}
            </div>

            <aside className="lg:sticky lg:top-6 lg:self-start">
              {phase === "done" && result ? (
                <ResultsAside result={result} />
              ) : phase === "running" ? (
                <AsideSkeleton />
              ) : null}
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

function Results({ result }: { result: AnalyzeResult }) {
  const r = result.repo;
  return (
    <>
      <div>
        <a
          href={r.html_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 font-mono text-2xl font-semibold tracking-tight break-all hover:underline sm:text-3xl"
        >
          {r.full_name}
          <ExternalLink className="size-4 shrink-0 text-muted" aria-hidden />
        </a>
        {r.description && <p className="mt-2 max-w-[68ch] text-lg text-muted">{r.description}</p>}
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
          {r.language && <span>{r.language}</span>}
          <span className="inline-flex items-center gap-1">
            <Star className="size-3.5" aria-hidden /> {r.stars.toLocaleString()}
          </span>
          {r.license && <span>{r.license}</span>}
          <span>{r.file_count.toLocaleString()} files</span>
          <span>
            Done in {formatSeconds(result.total_s)} on <span className="font-mono">{result.model}</span>
          </span>
        </div>
        {r.notes.length > 0 && (
          <ul className="mt-4 space-y-1.5">
            {r.notes.map((n) => (
              <li key={n} className="flex items-start gap-2 text-sm text-muted">
                <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
                {n}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="lg:hidden">
        <Verdict result={result} />
      </div>

      <RepoMap data={result.explanation} error={result.explain_error} />
      <IssueCards data={result.issues} error={result.issues_error} />
    </>
  );
}

function verdictFor(result: AnalyzeResult) {
  const ex = result.explanation;
  const is = result.issues;
  // No beginner issues at all: the most useful question is asking for a first task.
  if (is && is.picks.length === 0 && is.ask_maintainer) {
    return { question: is.ask_maintainer, why: "There are no open beginner issues, so asking for a small first task is the best next step." };
  }
  if (ex?.ask_reason === "answer_not_found" && ex.ask_maintainer) {
    return { question: ex.ask_maintainer, why: "The repo's docs don't clearly answer your question, so GoodFirst won't guess. This message asks the maintainers directly." };
  }
  if (ex?.ask_maintainer) {
    return { question: ex.ask_maintainer, why: "GoodFirst isn't confident about this repo's docs. A short, polite question saves you a lot of guessing." };
  }
  if (is?.low_confidence && is.ask_maintainer) {
    return { question: is.ask_maintainer, why: "GoodFirst isn't sure these issues suit you. Asking on the issue first is the safe move." };
  }
  return { question: null, why: "" };
}

/** Overall confidence + the ask-the-maintainers box. */
function Verdict({ result }: { result: AnalyzeResult }) {
  const { question, why } = verdictFor(result);
  return (
    <div className="space-y-5">
      <ConfidenceMeter value={result.overall_confidence} floor={result.confidence_floor} label="Overall confidence" />
      {question && <AskMaintainer question={question} why={why} />}
    </div>
  );
}

function ResultsAside({ result }: { result: AnalyzeResult }) {
  const adjustments = [...(result.explanation?.warnings ?? []), ...(result.issues?.warnings ?? [])].filter(
    (w) => w.startsWith("Lowered") || w.startsWith("Confidence capped") || w.startsWith("You asked"),
  );
  return (
    <div className="space-y-5">
      {/* On small screens the verdict is shown near the top of the results instead. */}
      <div className="hidden lg:block">
        <Verdict result={result} />
      </div>
      <EvidencePanel evidence={result.evidence} adjustments={adjustments} />
    </div>
  );
}

function ResultsSkeleton() {
  return (
    <div className="space-y-4" aria-hidden>
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-full max-w-xl" />
      <Skeleton className="h-4 w-full max-w-lg" />
      <Skeleton className="mt-6 h-32 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

function AsideSkeleton() {
  return (
    <div className="space-y-4 rounded-xl border border-rule bg-surface p-5" aria-hidden>
      <Skeleton className="h-5 w-24" />
      <div className="grid grid-cols-3 gap-2">
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-4/6" />
    </div>
  );
}
