import { AlertTriangle, ExternalLink, MessageSquare, Sparkles, UserCheck, Wand2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { SectionError } from "./repo-map";
import { pct } from "@/lib/utils";
import type { IssuePick, Issues } from "@/lib/types";

export function IssueCards({ data, error }: { data: Issues | null; error: string | null }) {
  return (
    <section aria-labelledby="issues-title">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="issues-title" className="text-2xl font-semibold tracking-tight">
          Good first issues
        </h2>
        {data && data.picks.length > 0 && (
          <Badge tone={data.low_confidence ? "flagged" : "neutral"}>Confidence {pct(data.confidence)}</Badge>
        )}
      </div>

      {error && <SectionError message={`Gemma couldn't pick issues: ${error}`} />}
      {!data && !error && <p className="mt-3 text-muted">Skipped for this run.</p>}

      {data && data.picks.length === 0 && (
        <div className="mt-4 rounded-lg border border-dashed border-rule-strong p-6">
          <p className="font-medium">No open beginner issues right now</p>
          <p className="mt-1 max-w-[60ch] text-sm text-muted">
            {data.message ?? "Nothing is labelled for newcomers."} That&apos;s normal for busy projects. The question below asks the
            maintainers for a small first task instead.
          </p>
        </div>
      )}

      {data && data.picks.length > 0 && (
        <div className="mt-4 space-y-4">
          {data.picks.map((pick, i) => (
            <IssueCard key={pick.number} pick={pick} rank={i + 1} />
          ))}
        </div>
      )}
    </section>
  );
}

function IssueCard({ pick, rank }: { pick: IssuePick; rank: number }) {
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm text-muted">
            <span>{rank === 1 ? "Best match" : `Option ${rank}`}</span>
            <span className="font-mono">#{pick.number}</span>
          </p>
          <a
            href={pick.url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-flex items-start gap-1.5 text-lg leading-snug font-semibold underline-offset-4 hover:underline"
          >
            {pick.title}
            <ExternalLink className="mt-1.5 size-3.5 shrink-0 text-muted" aria-hidden />
          </a>
        </div>
        {pick.source === "model" ? (
          <Badge tone="neutral" title="Chosen by Gemma from the top-ranked issues">
            <Sparkles aria-hidden /> Gemma&apos;s pick
          </Badge>
        ) : (
          <Badge tone="neutral" title="Gemma gave fewer picks, so GoodFirst's ranking filled this slot">
            <Wand2 aria-hidden /> GoodFirst ranking
          </Badge>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {pick.labels.map((l) => (
          <Badge key={l}>{l}</Badge>
        ))}
        <Badge>
          <MessageSquare aria-hidden /> {pick.comments}
        </Badge>
        {!pick.assigned && (
          <Badge tone="verified">
            <UserCheck aria-hidden /> Unassigned
          </Badge>
        )}
      </div>

      <dl className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-sm font-semibold">Why this one</dt>
          <dd className="mt-1 text-[0.95rem] leading-relaxed text-ink/90">
            {pick.source === "model"
              ? pick.why_this_one
              : "Gemma gave fewer valid picks, so GoodFirst's own ranking filled this slot. The facts from GitHub below are why it ranked well."}
          </dd>
        </div>
        <div>
          <dt className="text-sm font-semibold">Where to start</dt>
          <dd className="mt-1 text-[0.95rem] leading-relaxed text-ink/90">{pick.where_to_start}</dd>
          {pick.unverified_files.length > 0 && (
            <p className="mt-2 flex items-start gap-1.5 text-sm text-flagged">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>
                <span className="font-mono">{pick.unverified_files.join(", ")}</span> isn&apos;t in the repo or the issue.
                Check the issue first.
              </span>
            </p>
          )}
        </div>
      </dl>

      {pick.facts.length > 0 && (
        <p className="mt-4 border-t border-rule pt-3 text-sm text-muted">
          <span className="font-medium text-ink">From GitHub:</span> {pick.facts.join(". ")}.
        </p>
      )}
    </Card>
  );
}
