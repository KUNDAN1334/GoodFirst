/** Render text with `backtick` spans as <code>. An unclosed backtick runs to the end. */
export function InlineCode({ text }: { text: string }) {
  const parts = text.split("`");
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <code
            key={i}
            className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[0.84em] text-ink ring-1 ring-rule"
          >
            {part}
          </code>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}
