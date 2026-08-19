export default function AuditTimeline({ steps }: { steps: string[] }) {
  if (steps.length === 0) {
    return <p className="text-[12.5px] text-[var(--color-ink-faint)]">No audit events recorded yet.</p>;
  }
  return (
    <ol className="flex flex-col">
      {steps.map((step, i) => (
        <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
          <div className="flex flex-col items-center">
            <span className="font-mono-data flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--color-wire-soft)] text-[10px] font-semibold text-[var(--color-wire)]">
              {i + 1}
            </span>
            {i < steps.length - 1 && <span className="mt-1 w-px flex-1 bg-[var(--color-border)]" />}
          </div>
          <p className="pt-0.5 text-[12.5px] leading-relaxed text-[var(--color-ink)]">{step}</p>
        </li>
      ))}
    </ol>
  );
}
