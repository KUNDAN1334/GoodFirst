"use client";

import { useEffect, useState } from "react";

const WEEKS = 34;
const TODAY_ROW = 4; // fixed so server and client render the same grid
const MONTHS = ["Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"];

/**
 * A GitHub-style contribution graph that is empty except for one square:
 * today's, which lights up once on load. The story of the product in one picture.
 */
export function ContributionGraph() {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setCount(1);
      return;
    }
    const id = setTimeout(() => setCount(1), 1100); // in step with the square's animation
    return () => clearTimeout(id);
  }, []);

  return (
    <figure className="w-full max-w-[30rem] min-w-0 rounded-md border border-rule bg-surface px-4 py-3" aria-label="Contribution graph">
      <figcaption className="text-sm text-ink">
        <span className="tabular-nums">{count}</span> contribution{count === 1 ? "" : "s"} in the last year
      </figcaption>

      <div className="mt-2 overflow-hidden" dir="rtl">
        {/* rtl keeps the most recent weeks (and today's square) visible on narrow screens */}
        <div dir="ltr" className="inline-block">
          <div className="mb-1 flex justify-between pr-2 pl-0.5 text-[10px] text-muted" aria-hidden>
            {MONTHS.map((m) => (
              <span key={m}>{m}</span>
            ))}
          </div>
          <div className="grid grid-flow-col grid-rows-7 gap-[3px]" aria-hidden>
            {Array.from({ length: WEEKS * 7 }, (_, i) => {
              const week = Math.floor(i / 7);
              const day = i % 7;
              const isLastWeek = week === WEEKS - 1;
              if (isLastWeek && day > TODAY_ROW) return <span key={i} className="size-[10px]" />;
              const isToday = isLastWeek && day === TODAY_ROW;
              return <span key={i} className={isToday ? "heat-cell heat-first" : "heat-cell heat-0"} />;
            })}
          </div>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted">
        <span className="heat-label">Today: your first contribution</span>
        <span className="flex items-center gap-1" aria-hidden>
          Less
          <span className="heat-cell heat-0" />
          <span className="heat-cell heat-1" />
          <span className="heat-cell heat-2" />
          <span className="heat-cell heat-3" />
          <span className="heat-cell heat-4" />
          More
        </span>
      </div>
    </figure>
  );
}
