/**
 * Open source programs and events, with dates checked against official sources.
 *
 * How to keep this accurate:
 * - Only put a date here if the program's official site (or official announcement) states it.
 * - If the next edition isn't announced, leave it out: the page will say "Next edition not announced".
 * - Update VERIFIED_ON whenever you re-check.
 *
 * The page computes each status ("Applications open", "In progress", "Upcoming", ...) from these
 * dates and TODAY'S date in the browser, so statuses change on their own as dates pass.
 */

export const VERIFIED_ON = "2026-10-03";

export interface Phase {
  name: string;
  start: string; // YYYY-MM-DD
  end?: string; // YYYY-MM-DD, inclusive; omit for a single-day milestone
  apply?: boolean; // true if this phase is when people can apply/register
}

export interface Edition {
  label: string;
  phases: Phase[];
  note?: string;
}

export interface Program {
  id: string;
  name: string;
  organizer?: string;
  summary: string;
  url: string; // official site
  sources: { label: string; url: string }[]; // where the dates come from
  stipend?: boolean;
  rolling?: string; // set for programs without fixed dates
  editions: Edition[]; // oldest first; only officially announced ones
  pattern?: string; // how the program usually runs, stated as past behaviour, not a promise
  heads_up?: string; // important rule changes etc.
}

export const PROGRAMS: Program[] = [
  {
    id: "hacktoberfest",
    name: "Hacktoberfest",
    summary: "A month-long celebration of open source every October.",
    url: "https://hacktoberfest.com/",
    sources: [
      { label: "hacktoberfest.com", url: "https://hacktoberfest.com/" },
      {
        label: "MLH: Hacktoberfest 2026 guide",
        url: "https://blog.mlh.com/everything-you-need-to-know-about-hacktoberfest-2026-ai-belongs-to-everyone-mdk",
      },
    ],
    editions: [{ label: "2026", phases: [{ name: "Hacktoberfest", start: "2026-10-01", end: "2026-10-31" }] }],
    heads_up:
      "New in 2026: pull requests no longer count toward rewards. You collect stickers by joining activities like Fests, livestreams and challenges.",
  },
  {
    id: "gsoc",
    name: "Google Summer of Code",
    organizer: "Google",
    summary: "Paid, mentored open source projects with organizations worldwide.",
    url: "https://summerofcode.withgoogle.com/",
    sources: [{ label: "Official GSoC timeline", url: "https://developers.google.com/open-source/gsoc/timeline" }],
    stipend: true,
    editions: [
      {
        label: "2026",
        phases: [
          { name: "Contributor applications", start: "2026-03-16", end: "2026-03-31", apply: true },
          { name: "Accepted projects announced", start: "2026-04-30" },
          { name: "Coding begins", start: "2026-05-25" },
          { name: "Final submissions (standard projects)", start: "2026-08-24", end: "2026-08-31" },
          { name: "Final submissions (extended projects)", start: "2026-11-02" },
        ],
      },
    ],
    pattern: "Recent editions opened contributor applications in March.",
  },
  {
    id: "outreachy",
    name: "Outreachy",
    organizer: "Software Freedom Conservancy",
    summary: "Paid, remote internships in open source for people subject to systemic bias.",
    url: "https://www.outreachy.org/",
    sources: [{ label: "Outreachy applicant guide", url: "https://www.outreachy.org/docs/applicant/" }],
    stipend: true,
    editions: [
      {
        label: "December 2026 cohort",
        phases: [
          { name: "Initial applications", start: "2026-08-24", end: "2026-08-31", apply: true },
          { name: "Contribution period", start: "2026-10-05", end: "2026-11-02" },
          { name: "Interns announced", start: "2026-11-30" },
          { name: "Internship", start: "2026-12-07", end: "2027-03-08" },
        ],
        note: "The contribution period is for applicants who passed the initial application.",
      },
    ],
    pattern: "Runs twice a year: a May to August cohort and a December to March cohort.",
  },
  {
    id: "lfx",
    name: "LFX Mentorship",
    organizer: "Linux Foundation",
    summary: "Paid mentorships on Linux Foundation and CNCF projects.",
    url: "https://lfx.linuxfoundation.org/tools/mentorship/",
    sources: [
      { label: "CNCF term 3 schedule (via Project HAMi)", url: "https://project-hami.io/blog/lfx-mentorship-2026-term-3" },
      { label: "LFX programme timelines", url: "https://docs.linuxfoundation.org/lfx/mentorship/mentorship-program-timelines" },
    ],
    stipend: true,
    editions: [
      {
        label: "2026 Term 3 (Sep to Nov)",
        phases: [
          { name: "Mentee applications", start: "2026-08-03", end: "2026-08-18", apply: true },
          { name: "Application review", start: "2026-08-19", end: "2026-09-01" },
          { name: "Mentorship", start: "2026-09-07", end: "2026-11-27" },
        ],
        note: "These are the CNCF dates. Other foundations on LFX can use slightly different dates.",
      },
    ],
    pattern: "Usually three terms a year: March to May, June to August, September to November.",
  },
  {
    id: "mlh-fellowship",
    name: "MLH Fellowship",
    organizer: "Major League Hacking",
    summary: "A remote fellowship where you contribute to open source with a small pod of peers.",
    url: "https://fellowship.mlh.com/",
    sources: [{ label: "MLH Fellowship: Open Source", url: "https://fellowship.mlh.com/programs/open-source" }],
    rolling: "Batches start every few months. Applications are reviewed on a rolling basis and close a few weeks before each batch.",
    editions: [],
  },
  {
    id: "gssoc",
    name: "GirlScript Summer of Code",
    organizer: "GirlScript Foundation",
    summary: "A beginner-friendly open source program open to everyone, with a large Indian community.",
    url: "https://gssoc.girlscript.org/",
    sources: [{ label: "gssoc.girlscript.org", url: "https://gssoc.girlscript.org/" }],
    editions: [
      {
        label: "2026",
        phases: [
          { name: "Applications open", start: "2026-03-24", apply: true },
          { name: "Open source track closes", start: "2026-08-16" },
        ],
        note: "The official timeline gives the contribution period as May to June 2026.",
      },
    ],
  },
  {
    id: "summer-of-bitcoin",
    name: "Summer of Bitcoin",
    summary: "Paid summer internships on Bitcoin open source projects for university students.",
    url: "https://www.summerofbitcoin.org/",
    sources: [{ label: "Summer of Bitcoin student guide", url: "https://guide.summerofbitcoin.org/about/how-it-works" }],
    stipend: true,
    editions: [
      {
        label: "2026",
        phases: [
          { name: "Applications close", start: "2026-02-15", apply: true },
          { name: "Bootcamp", start: "2026-02-16", end: "2026-03-20" },
          { name: "Project proposals due", start: "2026-04-20" },
        ],
      },
    ],
  },
  {
    id: "kwoc",
    name: "Kharagpur Winter of Code",
    organizer: "KOSS, IIT Kharagpur",
    summary: "A winter program that helps students start contributing to open source.",
    url: "https://kwoc.kossiitkgp.org/",
    sources: [{ label: "kwoc.kossiitkgp.org", url: "https://kwoc.kossiitkgp.org/" }],
    editions: [],
    pattern: "Past editions ran from December to January.",
  },
];

// ---------------------------------------------------------------------------
// Status, computed from the dates above and today's date.
// ---------------------------------------------------------------------------

export type StatusKind = "open" | "live" | "upcoming" | "between" | "rolling" | "not_announced";

export interface ProgramStatus {
  kind: StatusKind;
  label: string; // short badge text
  detail: string; // one line: what happens next, with a date
  edition?: Edition; // the edition the status is about, if any
}

const DAY = 86_400_000;

/** Parse YYYY-MM-DD as a local calendar date (no timezone surprises). */
export function day(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatDate(iso: string): string {
  const d = day(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

function phaseEnd(p: Phase): Date {
  return new Date(day(p.end ?? p.start).getTime() + DAY - 1); // inclusive end of day
}

export function statusFor(program: Program, today: Date): ProgramStatus {
  if (program.rolling) {
    return { kind: "rolling", label: "Rolling applications", detail: program.rolling };
  }
  for (const edition of program.editions) {
    const phases = edition.phases;
    const last = phases[phases.length - 1];
    if (!last || today > phaseEnd(last)) continue; // this edition is over

    const first = phases[0];
    if (today < day(first.start)) {
      return {
        kind: "upcoming",
        label: "Upcoming",
        detail: `${first.name} ${first.end ? "opens" : "on"} ${formatDate(first.start)}`,
        edition,
      };
    }
    const current = phases.find((p) => today >= day(p.start) && today <= phaseEnd(p));
    if (current) {
      const until = current.end ? ` until ${formatDate(current.end)}` : " today";
      return current.apply
        ? { kind: "open", label: "Applications open", detail: `${current.name}${until}`, edition }
        : { kind: "live", label: "Live now", detail: `${current.name}${until}`, edition };
    }
    const next = phases.find((p) => day(p.start) > today)!;
    const appliedAlready = phases.some((p) => p.apply && phaseEnd(p) < today);
    return {
      kind: "between",
      label: appliedAlready ? "Applications closed" : "Upcoming",
      detail: `Next: ${next.name} on ${formatDate(next.start)}`,
      edition,
    };
  }
  const lastEdition = program.editions[program.editions.length - 1];
  return {
    kind: "not_announced",
    label: "Next edition not announced",
    detail: lastEdition
      ? `${/^\d{4}$/.test(lastEdition.label) ? `The ${lastEdition.label} edition` : lastEdition.label} is over. No dates for the next one yet.`
      : "No dates for the next edition yet.",
    edition: lastEdition,
  };
}

export function phaseState(p: Phase, today: Date): "past" | "current" | "future" {
  if (today > phaseEnd(p)) return "past";
  if (today >= day(p.start)) return "current";
  return "future";
}

/** Order on the page: things you can act on first. */
export const STATUS_ORDER: StatusKind[] = ["open", "live", "between", "upcoming", "rolling", "not_announced"];
