import type { Metadata } from "next";
import { ProgramsList } from "@/components/programs-list";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = {
  title: "Open source programs · GoodFirst",
  description: "Famous open source programs and events, with official dates and links.",
};

export default function ProgramsPage() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <main className="mx-auto max-w-6xl px-4 pt-8 pb-16 sm:px-6 sm:pt-10">
        <h1 className="display-wide text-3xl font-bold tracking-[-0.03em] sm:text-4xl">Open source programs</h1>
        <p className="mt-2 max-w-[60ch] text-lg text-muted">
          Mentorships, internships and events where beginners get their first contributions in. Each one links to its
          official site.
        </p>
        <div className="mt-6">
          <ProgramsList />
        </div>
      </main>
    </div>
  );
}
