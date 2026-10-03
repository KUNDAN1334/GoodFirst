"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, RotateCcw, Square } from "lucide-react";
import { CIAside, CIResults } from "@/components/ci/ci-results";
import { CIForm, CIHero } from "@/components/ci/ci-form";
import { ProgressTimeline, type StepDefinition, type StepState } from "@/components/progress-timeline";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { explainCI, getHealth, type CIInput } from "@/lib/api";
import type { CIResult, Health } from "@/lib/types";

type Phase = "idle" | "running" | "done" | "error";

// The three fixed nodes of the CI graph (goodfirst/ci.py: build_ci_graph).
const CI_STEPS: StepDefinition[] = [
  { name: "fetching", title: "Reading the PR on GitHub", hint: "Failed checks, their logs or annotations, and the files this PR changes" },
  { name: "explaining", title: "Gemma reads the log", hint: "Only the end of the log around the error. Local model on your CPU" },
  { name: "honesty_check", title: "Checking every claim", hint: "Quoted lines and files are compared with the real log and repo" },
];

const freshSteps = (): Record<string, StepState> =>
  Object.fromEntries(CI_STEPS.map((s) => [s.name, { status: "pending" }]));

export default function CIPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [input, setInput] = useState<CIInput>({ pr: "", language: "english" });
  const [steps, setSteps] = useState(freshSteps);
  const [result, setResult] = useState<CIResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null | undefined>(undefined);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    getHealth().then(setHealth);
  }, []);

  const start = useCallback((next: CIInput) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setInput(next);
    setSteps(freshSteps());
    setResult(null);
    setError(null);
    setPhase("running");
    window.scrollTo({ top: 0 });

    explainCI(
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
              startedAt: e.status === "started" ? Date.now() : prev[e.step]?.startedAt,
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

  const reset = () => {
    abortRef.current?.abort();
    setPhase("idle");
    getHealth().then(setHealth);
  };

  const timeline = <ProgressTimeline steps={steps} repo={input.pr} definitions={CI_STEPS} label="Explaining" />;

  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <main className="mx-auto max-w-6xl px-4 pt-6 pb-16 sm:px-6 sm:pt-8">
        {phase === "idle" && (
          <div className="grid grid-cols-1 gap-10 lg:min-h-[calc(100dvh-9.5rem-1px)] lg:grid-cols-[1.1fr_1fr] lg:items-center lg:gap-14">
            <div className="min-w-0">
              <CIHero />
            </div>
            <CIForm initial={input} health={health} onSubmit={start} />
          </div>
        )}

        {phase !== "idle" && (
          <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-12">
            <div className="min-w-0 space-y-10">
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="ghost" size="sm" onClick={reset}>
                  <ArrowLeft /> Another PR
                </Button>
                {phase === "running" ? (
                  <Button variant="ghost" size="sm" onClick={reset}>
                    <Square /> Stop
                  </Button>
                ) : (
                  <Button variant="ghost" size="sm" onClick={() => start(input)}>
                    <RotateCcw /> Run again
                  </Button>
                )}
              </div>

              {phase === "running" && (
                <>
                  {timeline}
                  <div className="space-y-3" aria-hidden>
                    <Skeleton className="h-8 w-72" />
                    <Skeleton className="h-4 w-full max-w-xl" />
                    <Skeleton className="mt-6 h-24 w-full" />
                  </div>
                </>
              )}

              {phase === "error" && (
                <>
                  {timeline}
                  <div role="alert" className="rounded-lg border border-removed/40 bg-removed-wash p-5">
                    <p className="font-semibold text-removed">Stopped</p>
                    <p className="mt-1 max-w-[68ch]">{error}</p>
                  </div>
                </>
              )}

              {phase === "done" && result && <CIResults result={result} />}
            </div>
            <aside className="lg:sticky lg:top-6 lg:self-start">
              {phase === "done" && result && <CIAside result={result} />}
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}
