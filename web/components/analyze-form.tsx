"use client";

import { useState } from "react";
import { Cpu, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ContributionGraph } from "@/components/contribution-graph";
import { cn } from "@/lib/utils";
import type { Health, Language } from "@/lib/types";
import type { AnalyzeInput } from "@/lib/api";

const QUESTION_MAX = 500;

export function Hero() {
  return (
    <div className="max-w-xl">
      <h1 className="display-wide text-[2.5rem] leading-[1.02] font-bold tracking-[-0.035em] text-balance sm:text-[3.1rem]">
        Your first green square starts here.
      </h1>
      <p className="mt-4 max-w-[34rem] text-[1.05rem] leading-relaxed text-muted">
        Paste a repo and ask anything. GoodFirst answers from the repo&apos;s own docs, picks good first issues, and
        shows the evidence for every claim. What it can&apos;t back up gets crossed out.
      </p>
      <p className="mt-4 inline-flex items-center gap-2 rounded-full border border-rule bg-surface px-3 py-1 text-sm text-muted">
        <Cpu className="size-4 text-verified" aria-hidden />
        Runs locally on Gemma · no API keys · works offline
      </p>
      <div className="mt-6">
        <ContributionGraph />
      </div>
    </div>
  );
}

interface FormProps {
  initial: AnalyzeInput;
  health: Health | null | undefined; // undefined = still checking
  onSubmit: (input: AnalyzeInput) => void;
}

export function AnalyzeForm({ initial, health, onSubmit }: FormProps) {
  const [repo, setRepo] = useState(initial.repo);
  const [question, setQuestion] = useState(initial.question);
  const [language, setLanguage] = useState<Language>(initial.language);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!repo.trim()) return;
    onSubmit({ repo: repo.trim(), question: question.trim(), language });
  };

  return (
    <form onSubmit={submit} className="rounded-xl border border-rule bg-surface p-5 shadow-[0_1px_0_var(--rule)] sm:p-6">
      <label htmlFor="repo" className="text-sm font-medium">
        GitHub repo
      </label>
      <div className="relative mt-2">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <Input
          id="repo"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          placeholder="owner/repo or https://github.com/owner/repo"
          className="h-12 pl-9 font-mono text-[0.9rem]"
          autoComplete="off"
          spellCheck={false}
          required
        />
      </div>

      <div className="mt-5 flex items-baseline justify-between gap-3">
        <label htmlFor="question" className="text-sm font-medium">
          What do you want to know?
        </label>
        <span className="text-xs text-muted">Optional</span>
      </div>
      <textarea
        id="question"
        value={question}
        onChange={(e) => setQuestion(e.target.value.slice(0, QUESTION_MAX))}
        rows={3}
        placeholder="e.g. I know Python. How do I run this locally, and which part is easy to start with?"
        className="mt-2 w-full resize-y rounded-md border border-rule-strong bg-surface px-3 py-2.5 text-[0.95rem] leading-relaxed text-ink placeholder:text-muted/70"
      />
      <p className="mt-1.5 text-xs text-muted">
        The answer comes only from the repo&apos;s docs. If they don&apos;t say, GoodFirst writes the question up for the
        maintainers instead of guessing.
      </p>

      <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span id="lang-label" className="text-sm font-medium">
            Explain it in
          </span>
          <div role="radiogroup" aria-labelledby="lang-label" className="mt-2 inline-flex rounded-md border border-rule-strong p-0.5">
            {(["english", "hinglish"] as const).map((lang) => (
              <button
                key={lang}
                type="button"
                role="radio"
                aria-checked={language === lang}
                onClick={() => setLanguage(lang)}
                className={cn(
                  "rounded-[5px] px-3.5 py-1.5 text-sm capitalize transition-colors",
                  language === lang ? "bg-rule text-ink" : "text-muted hover:text-ink",
                )}
              >
                {lang}
              </button>
            ))}
          </div>
        </div>
        <Button type="submit" size="lg" disabled={!repo.trim()}>
          Analyze repo
        </Button>
      </div>

      <HealthLine health={health} />
    </form>
  );
}

export function HealthLine({ health }: { health: Health | null | undefined }) {
  if (health === undefined) return null;
  let text: string;
  let tone: string;
  if (health === null) {
    text = 'Backend not running. Start it with "python -m goodfirst.api".';
    tone = "bg-removed";
  } else if (!health.ollama_reachable) {
    text = "Ollama isn't running. Open the Ollama app, then try again.";
    tone = "bg-removed";
  } else if (!health.model_available) {
    text = `Model not pulled yet. Run: ollama pull ${health.model}`;
    tone = "bg-flagged";
  } else {
    text = `${health.model} is ready on this computer`;
    tone = "bg-verified";
  }
  return (
    <p className="mt-4 flex items-center gap-2 border-t border-rule pt-3.5 text-sm text-muted" role="status">
      <span className={cn("size-2 rounded-full", tone)} aria-hidden />
      {text}
    </p>
  );
}
