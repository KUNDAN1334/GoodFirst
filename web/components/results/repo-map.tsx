import { AlertTriangle, CheckCircle2, ExternalLink, FileText, Folder, MessageCircleQuestion } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { InlineCode } from "./inline-code";
import { pct } from "@/lib/utils";
import type { Explanation } from "@/lib/types";

export function RepoMap({ data, error }: { data: Explanation | null; error: string | null }) {
  return (
    <section aria-labelledby="map-title">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="map-title" className="text-2xl font-semibold tracking-tight">
          Repo map
        </h2>
        {data && (
          <Badge tone={data.low_confidence ? "flagged" : "neutral"}>Confidence {pct(data.confidence)}</Badge>
        )}
      </div>

      {error && <SectionError message={error} />}
      {!data && !error && <p className="mt-3 text-muted">Skipped for this run.</p>}

      {data && (
        <div className="mt-4 space-y-8">
          {data.question && <AnswerBlock data={data} />}

          <p className="max-w-[68ch] text-lg leading-relaxed">{data.summary}</p>

          <div>
            <h3 className="font-semibold">How to set it up</h3>
            {data.setup_steps.length === 0 ? (
              <p className="mt-2 max-w-[68ch] text-muted">
                No setup steps shown: the repo&apos;s docs don&apos;t describe a setup, and GoodFirst won&apos;t guess one.
              </p>
            ) : (
              <ol className="mt-3 space-y-3">
                {data.setup_steps.map((step, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-rule-strong font-mono text-xs text-muted">
                      {i + 1}
                    </span>
                    <div className="min-w-0 max-w-[68ch] leading-relaxed">
                      <span className={step.verified ? undefined : "wavy"}>
                        <InlineCode text={step.text} />
                      </span>
                      {!step.verified && (
                        <p className="mt-1 flex items-center gap-1.5 text-sm text-flagged">
                          <AlertTriangle className="size-3.5" aria-hidden />
                          This command isn&apos;t written word-for-word in the docs. Double-check before running it.
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <div>
            <h3 className="font-semibold">Files worth opening first</h3>
            {data.important_files.length === 0 ? (
              <p className="mt-2 text-muted">None that GoodFirst could verify.</p>
            ) : (
              <ul className="mt-3 divide-y divide-rule rounded-lg border border-rule bg-surface">
                {data.important_files.map((f) => (
                  <li key={f.path} className="flex gap-3 px-4 py-3">
                    {f.path.endsWith("/") ? (
                      <Folder className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                    ) : (
                      <FileText className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                    )}
                    <div className="min-w-0">
                      <a
                        href={f.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 font-mono text-sm break-all underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
                      >
                        {f.path}
                        <ExternalLink className="size-3 shrink-0 text-muted" aria-hidden />
                      </a>
                      {f.why && <p className="mt-0.5 text-sm text-muted">{f.why}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {(data.questions_for_maintainers.length > 0 || data.unsure_about.length > 0) && (
            <div className="grid gap-6 sm:grid-cols-2">
              {data.questions_for_maintainers.length > 0 && (
                <div>
                  <h3 className="font-semibold">Good questions to ask</h3>
                  <ul className="mt-2 list-disc space-y-1.5 pl-5 text-[0.95rem] leading-relaxed marker:text-rule-strong">
                    {data.questions_for_maintainers.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </div>
              )}
              {data.unsure_about.length > 0 && (
                <div>
                  <h3 className="font-semibold">Gemma wasn&apos;t sure about</h3>
                  <ul className="mt-2 list-disc space-y-1.5 pl-5 text-[0.95rem] leading-relaxed text-muted marker:text-rule-strong">
                    {data.unsure_about.map((u) => (
                      <li key={u}>{u}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function AnswerBlock({ data }: { data: Explanation }) {
  const found = data.answer_found === true;
  return (
    <div className="rounded-lg border border-rule bg-surface p-5">
      <p className="flex items-start gap-2 text-sm text-muted">
        <MessageCircleQuestion className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          You asked: <q className="text-ink">{data.question}</q>
        </span>
      </p>
      <p className="mt-3 max-w-[68ch] text-[1.05rem] leading-relaxed">
        {data.answer ? <InlineCode text={data.answer} /> : "Gemma didn't give an answer."}
      </p>
      {found ? (
        <p className="mt-3 flex items-center gap-1.5 text-sm text-verified">
          <CheckCircle2 className="size-4" aria-hidden />
          Answered from the repo&apos;s docs
        </p>
      ) : (
        <div className="mt-3 text-sm text-flagged">
          <p className="flex items-center gap-1.5">
            <AlertTriangle className="size-4" aria-hidden />
            The docs don&apos;t clearly answer this, so it&apos;s in the message for the maintainers.
          </p>
          {data.answer_flags.length > 0 && (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-6">
              {data.answer_flags.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export function SectionError({ message }: { message: string }) {
  return (
    <div className="mt-4 rounded-lg border border-removed/40 bg-removed-wash p-4 text-sm">
      <p className="font-medium text-removed">This part couldn&apos;t be completed</p>
      <p className="mt-1 text-ink">{message}</p>
    </div>
  );
}
