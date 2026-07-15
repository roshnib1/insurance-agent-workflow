"use client";

import { useRef, useState } from "react";
import { UploadCloud } from "lucide-react";

const ACCEPTED_EXTENSIONS = [".html", ".htm", ".pdf"];

export default function UploadPanel({
  onUpload,
  disabled = false,
}: {
  onUpload: (file: File) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) return;
    setFileName(file.name);
    onUpload(file);
  }

  return (
    <div
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!disabled) handleFiles(e.dataTransfer.files);
      }}
      className="flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border border-dashed px-3 py-5 text-center transition"
      style={{
        borderColor: isDragging ? "var(--color-wire)" : "var(--color-border-strong)",
        background: isDragging ? "var(--color-wire-soft)" : "var(--color-surface-sunken)",
        opacity: disabled ? 0.6 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      <UploadCloud className="h-5 w-5 text-[var(--color-ink-muted)]" strokeWidth={1.5} />
      <p className="text-[12px] font-medium text-[var(--color-ink)]">
        {fileName ?? "Drop HTML or PDF, or click to browse"}
      </p>
      <p className="text-[10.5px] text-[var(--color-ink-faint)]">.html, .htm, .pdf</p>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_EXTENSIONS.join(",")}
        className="hidden"
        disabled={disabled}
        onChange={(e) => handleFiles(e.target.files)}
      />
    </div>
  );
}
