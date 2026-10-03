import { AlertTriangle, CheckCircle2, ExternalLink, FileCode2, GitPullRequest, Info, XCircle } from "lucide-react";
import { AskMaintainer } from "@/components/results/ask-maintainer";
import { ConfidenceMeter } from "@/components/results/confidence-meter";
import { EvidencePanel } from "@/components/results/evidence-panel";
import { InlineCode } from "@/components/results/inline-code";
import { Badge } from "@/components/ui/badge";
import type { CIResult, FailedCheck } from "@/lib/types";
import { cn, formatSeconds } from "@/lib/utils";

// What each log_status means for the person reading (mirrors goodfirst/ci.py).
const LOG_STATUS: Record<FailedCheck["log_status"], string> = {
  ok: "Log read",
  needs_token: "Log needs a GITHUB_TOKEN",
  missing: "Log not available",
  not_actions: "Not GitHub Actions: summary only",
  not_fetched: "Log not fetched",
};

const CAUSE: Record<"yes" | "no" | "unsure", string> = {
  yes: "Probably yes",
  no: "Probably not",
  unsure: "Not sure",
};

export function CIResults({ result }: { result: CIResult }) {
  const pr = result.pr;
  const e = result.explanation;
  return (
    <>
      <div>
        <a
          href={pr.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-start gap-2 text-2xl font-semibold tracking-tight hover:underline sm:text-3xl"
        >
          <GitPullRequest className="mt-1.5 size-5 shrink-0 text-muted" aria-hidden />
          <span className="break-words">
            {pr.title} <span className="font-normal text-muted">#{pr.number}</span>
          </span>
        </a>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
          <span className="font-mono">
            {pr.owner}/{pr.repo}
          </span>
          <span>
            {pr.checks_total} checks, {pr.failed.length} failed
            {pr.checks_pending > 0 && `, ${pr.checks_pending} still running`}
          </span>
          <span>{pr.changed_files.length} changed files</span>
          <span>
            Done in {formatSeconds(result.total_s)} on <span className="font-mono">{result.model}</span>
          </span>
        </div>
        {pr.notes.length > 0 && (
          <ul className="mt-4 space-y-1.5">
            {pr.notes.map((n) => (
              <li key={n} className="flex items-start gap-2 text-sm text-muted">
                <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
                {n}
              </li>
            ))}
          </ul>
        )}
      </div>

      {pr.failed.length > 0 && (
        <section aria-labelledby="checks-title">
          <h2 id="checks-title" className="text-xl font-semibold">
            Failed checks
          </h2>
          <ul className="mt-3 divide-y divide-rule rounded-lg border border-rule bg-surface">
            {pr.failed.map((c) => (
              <li key={c.check_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
                <XCircle className="size-4 shrink-0 text-removed" aria-label="Failed" />
                <a href={c.url} target="_blank" rel="noreferrer" className="min-w-0 font-medium break-words hover:underline">
                  {c.name}
                </a>
                <span className="text-sm text-muted">{c.conclusion}</span>
                <Badge tone={c.log_status === "ok" ? "verified" : "neutral"} className="ml-auto">
                  {LOG_STATUS[c.log_status]}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}

      {result.explain_error && (
        <div role="alert" className="rounded-lg border border-flagged/40 bg-flagged-wash p-5">
          <p className="font-semibold text-flagged">No explanation this time</p>
          <p className="mt-1 max-w-[68ch]">{result.explain_error}</p>
        </div>
      )}

      {e && (
        <section aria-labelledby="explain-title" className="space-y-8">
          <div>
            <h2 id="explain-title" className="text-xl font-semibold">
              What failed
            </h2>
            <p className="mt-2 max-w-[68ch] text-[1.05rem] leading-relaxed">
              <InlineCode text={e.what_failed} />
            </p>
            <h3 className="mt-6 text-sm font-semibold text-muted">Why</h3>
            <p className="mt-1.5 max-w-[68ch] leading-relaxed">
              <InlineCode text={e.why} />
            </p>
          </div>

          {e.fix_steps.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-muted">How to fix it</h3>
              <ol className="mt-3 space-y-2.5">
                {e.fix_steps.map((s, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-rule font-mono text-xs text-muted">
                      {i + 1}
                    </span>
                    <div className="min-w-0 pt-0.5">
                      <p className={cn("break-words", !s.verified && "wavy")}>
                        <InlineCode text={s.text} />
                      </p>
                      {!s.verified && (
                        <p className="mt-1 text-xs text-flagged">This command isn&apos;t in the log. Double-check it.</p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {e.quoted_lines.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-muted">From the log</h3>
              <pre className="mt-2 overflow-x-auto rounded-lg border border-rule bg-surface-2 p-4 font-mono text-[0.85rem] leading-relaxed">
                {e.quoted_lines.map((q) => q.text).join("\n")}
              </pre>
              <p className="mt-1.5 text-xs text-muted">Every line here was found in the real log.</p>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="rounded-lg border border-rule bg-surface p-4">
              <h3 className="text-sm font-semibold text-muted">Caused by this PR?</h3>
              <p className="mt-1.5 text-lg font-medium">{CAUSE[e.caused_by_this_pr]}</p>
              <p className="mt-1 text-sm text-muted">Gemma&apos;s guess.</p>
              {result.linked_files.length > 0 ? (
                <p className="mt-2 flex gap-2 text-sm">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-verified" aria-hidden />
                  <span>
                    Fact: the error mentions{" "}
                    {result.linked_files.map((f, i) => (
                      <span key={f}>
                        {i > 0 && ", "}
                        <code className="font-mono text-[0.85em]">{f}</code>
                      </span>
                    ))}
                    , which this PR changes.
                  </span>
                </p>
              ) : (
                <p className="mt-2 text-sm text-muted">The error doesn&apos;t name any file this PR changes.</p>
              )}
            </div>
            <div className="rounded-lg border border-rule bg-surface p-4">
              <h3 className="text-sm font-semibold text-muted">Files to look at</h3>
              {e.files.length ? (
                <ul className="mt-2 space-y-1.5">
                  {e.files.map((f) => (
                    <li key={f.path} className="flex items-center gap-2 text-sm">
                      <FileCode2 className="size-4 shrink-0 text-muted" aria-hidden />
                      <code className="min-w-0 font-mono break-all">{f.path}</code>
                      {f.in_pr && <Badge tone="verified">in this PR</Badge>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-muted">No file could be confirmed.</p>
              )}
            </div>
          </div>

          {result.warnings.length > 0 && (
            <ul className="space-y-1.5">
              {result.warnings.map((w) => (
                <li key={w} className="flex gap-2 text-sm text-flagged">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  {w}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {result.ask_comment && (
        <div className="lg:hidden">
          <CIAsk result={result} />
        </div>
      )}
    </>
  );
}

function CIAsk({ result }: { result: CIResult }) {
  if (!result.ask_comment) return null;
  return (
    <AskMaintainer
      title="Still stuck? Ask on the PR"
      why="GoodFirst couldn't back this explanation up well enough. Post this on the pull request yourself; GoodFirst never writes to GitHub."
      question={result.ask_comment}
      copyLabel="Copy comment"
    />
  );
}

export function CIAside({ result }: { result: CIResult }) {
  return (
    <div className="space-y-5">
      {result.confidence !== null && (
        <div className="rounded-xl border border-rule bg-surface p-5">
          <ConfidenceMeter value={result.confidence} floor={result.confidence_floor} />
        </div>
      )}
      {result.ask_comment && (
        <div className="hidden lg:block">
          <CIAsk result={result} />
        </div>
      )}
      {result.evidence.length > 0 && (
        <EvidencePanel evidence={result.evidence} adjustments={[]} groups={[{ key: undefined, title: "Pull request" }]} />
      )}
      <a
        href={result.pr.url + "/checks"}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"
      >
        Open the checks on GitHub <ExternalLink className="size-3.5" aria-hidden />
      </a>
    </div>
  );
}
