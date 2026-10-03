"use client";

import { useState } from "react";
import { Check, Copy, MessageCircleQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";

export function AskMaintainer({
  question,
  why,
  title = "Not sure? Ask the maintainers",
  copyLabel = "Copy question",
}: {
  question: string;
  why: string;
  title?: string;
  copyLabel?: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(question);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="rounded-lg border border-flagged/40 bg-flagged-wash p-4">
      <p className="flex items-center gap-2 font-medium text-flagged">
        <MessageCircleQuestion className="size-4" aria-hidden />
        {title}
      </p>
      <p className="mt-1 text-sm text-muted">{why}</p>
      <blockquote className="mt-3 rounded-md border border-rule bg-surface p-3 text-[0.95rem] leading-relaxed">
        {question}
      </blockquote>
      <Button variant="outline" size="sm" className="mt-3" onClick={copy}>
        {copied ? <Check /> : <Copy />}
        {copied ? "Copied" : copyLabel}
      </Button>
    </div>
  );
}
