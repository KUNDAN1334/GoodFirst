"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight } from "lucide-react";
import { ThemeToggle } from "@/components/theme";
import { cn } from "@/lib/utils";

export const REPO_URL = "https://github.com/KUNDAN1334/GoodFirst";

/**
 * The GoodFirst mark: a tiny contribution graph, empty except for one bright square
 * (your first contribution). Same drawing as app/icon.svg, the browser-tab icon.
 */
export function Logo({ className = "size-6" }: { className?: string }) {
  const cells: [number, number, string][] = [];
  for (let row = 0; row < 3; row++) {
    for (let col = 0; col < 3; col++) {
      const fill =
        row === 2 && col === 2 ? "#39d353" : row === 1 && col === 1 ? "#0e4429" : "var(--logo-empty, #21262d)";
      cells.push([5 + col * 8, 5 + row * 8, fill]);
    }
  }
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="7" fill="#0d1117" />
      {cells.map(([x, y, fill]) => (
        <rect key={`${x}-${y}`} x={x} y={y} width="6" height="6" rx="1.5" fill={fill} />
      ))}
    </svg>
  );
}

/**
 * Site-wide navigation. On the home page `onHome` resets the analysis instead of navigating.
 */
export function SiteHeader({ onHome }: { onHome?: () => void }) {
  const pathname = usePathname();
  const brand = (
    <>
      <Logo />
      <span className="max-sm:sr-only">GoodFirst</span>
    </>
  );
  const navLink = (active: boolean) =>
    cn(
      "rounded-md px-2 py-1.5 text-sm whitespace-nowrap transition-colors sm:px-2.5",
      active ? "bg-surface-2 text-ink" : "text-muted hover:bg-surface-2 hover:text-ink",
    );

  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-2 px-4 sm:gap-4 sm:px-6">
        {onHome ? (
          <button onClick={onHome} className="flex items-center gap-2 font-semibold tracking-tight" aria-label="GoodFirst home">
            {brand}
          </button>
        ) : (
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight" aria-label="GoodFirst home">
            {brand}
          </Link>
        )}

        <nav className="flex items-center gap-0.5 sm:gap-1" aria-label="Main">
          <Link href="/ci" className={navLink(pathname === "/ci")}>
            CI help
          </Link>
          <Link href="/programs" className={navLink(pathname === "/programs")}>
            Programs
          </Link>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className={cn(navLink(false), "inline-flex items-center gap-1")}>
            GitHub
            <ArrowUpRight className="size-3.5" aria-hidden />
          </a>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
