"use client";

import { useState } from "react";
import { GitPullRequest } from "lucide-react";
import { HealthLine } from "@/components/analyze-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { CIInput } from "@/lib/api";
import type { Health, Language } from "@/lib/types";

export function CIHero() {
  return (
    <div className="max-w-xl">
      <h1 className="display-wide text-[2.4rem] leading-[1.04] font-bold tracking-[-0.035em] text-balance sm:text-[3rem]">
        Red checks on your PR?
      </h1>
      <p className="mt-4 max-w-[34rem] text-[1.05rem] leading-relaxed text-muted">
        Paste the pull request. GoodFirst reads the failed checks and their logs from GitHub, Gemma explains what broke
        in plain words, and every quoted log line and file is checked against the real log. Anything it can&apos;t find
        there is crossed out.
      </p>
      <ul className="mt-5 space-y-1.5 text-sm text-muted">
        <li>Works with GitHub Actions checks. Other CI services only show their summary.</li>
        <li>Job logs need a GITHUB_TOKEN in .env. Without one, GoodFirst uses the check annotations.</li>
        <li>Read-only: GoodFirst never comments or pushes. You copy the comment yourself.</li>
      </ul>
    </div>
  );
}

export function CIForm({
  initial,
  health,
  onSubmit,
}: {
  initial: CIInput;
  health: Health | null | undefined;
  onSubmit: (input: CIInput) => void;
}) {
  const [pr, setPr] = useState(initial.pr);
  const [language, setLanguage] = useState<Language>(initial.language);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pr.trim()) return;
    onSubmit({ pr: pr.trim(), language });
  };

  return (
    <form onSubmit={submit} className="rounded-xl border border-rule bg-surface p-5 shadow-[0_1px_0_var(--rule)] sm:p-6">
      <label htmlFor="pr" className="text-sm font-medium">
        Pull request
      </label>
      <div className="relative mt-2">
        <GitPullRequest className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <Input
          id="pr"
          value={pr}
          onChange={(e) => setPr(e.target.value)}
          placeholder="https://github.com/owner/repo/pull/123"
          className="h-12 pl-9 font-mono text-[0.9rem]"
          autoComplete="off"
          spellCheck={false}
          required
        />
      </div>
      <p className="mt-1.5 text-xs text-muted">Also accepts owner/repo#123.</p>

      <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span id="ci-lang-label" className="text-sm font-medium">
            Explain it in
          </span>
          <div role="radiogroup" aria-labelledby="ci-lang-label" className="mt-2 inline-flex rounded-md border border-rule-strong p-0.5">
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
        <Button type="submit" size="lg" disabled={!pr.trim()}>
          Explain the failure
        </Button>
      </div>

      <HealthLine health={health} />
    </form>
  );
}
