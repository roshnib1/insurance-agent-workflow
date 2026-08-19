import { FileSearch } from "lucide-react";

export default function EvidenceCard({ index, text }: { index: number; text: string }) {
  return (
    <div className="flex gap-2.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-sunken)] px-3 py-2.5">
      <span className="font-mono-data mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--color-surface)] text-[10px] text-[var(--color-ink-muted)]">
        {index}
      </span>
      <div className="flex items-start gap-2">
        <FileSearch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-ink-faint)]" strokeWidth={1.75} />
        <p className="text-[12.5px] leading-relaxed text-[var(--color-ink)]">{text}</p>
      </div>
    </div>
  );
}
