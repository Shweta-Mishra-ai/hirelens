"use client";
import { useCallback, useId, useRef, useState } from "react";
import { UploadCloud } from "lucide-react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";
import { formatBytes } from "@/lib/format";

export const ACCEPTED_EXTENSIONS = ["pdf", "docx"] as const;
export const MAX_FILE_MB = 10;

export interface FileRejection {
  file: File;
  reason: string;
}

/**
 * Validate a batch client-side so obvious problems are reported instantly and
 * with the offending filename attached, instead of costing an upload
 * round-trip. The server re-validates everything including magic bytes —
 * this is a convenience, never the security boundary.
 */
export function validateFiles(
  files: File[],
  { maxFiles, maxMb = MAX_FILE_MB }: { maxFiles?: number; maxMb?: number } = {},
): { accepted: File[]; rejected: FileRejection[] } {
  const accepted: File[] = [];
  const rejected: FileRejection[] = [];

  for (const file of files) {
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ACCEPTED_EXTENSIONS.includes(ext as (typeof ACCEPTED_EXTENSIONS)[number])) {
      rejected.push({ file, reason: `${ext ? `.${ext}` : "That format"} isn't supported — use PDF or DOCX.` });
    } else if (file.size === 0) {
      rejected.push({ file, reason: "This file is empty." });
    } else if (file.size > maxMb * 1024 * 1024) {
      rejected.push({ file, reason: `${formatBytes(file.size)} exceeds the ${maxMb}MB limit.` });
    } else if (maxFiles !== undefined && accepted.length >= maxFiles) {
      rejected.push({ file, reason: `Only ${maxFiles} files can be uploaded at once.` });
    } else {
      accepted.push(file);
    }
  }

  return { accepted, rejected };
}

export function FileDropzone({
  onFiles,
  multiple = false,
  maxFiles,
  disabled,
  title,
  hint,
  className,
  compact,
}: {
  onFiles: (accepted: File[], rejected: FileRejection[]) => void;
  multiple?: boolean;
  maxFiles?: number;
  disabled?: boolean;
  title: string;
  hint: string;
  className?: string;
  compact?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const inputId = useId();

  const handle = useCallback(
    (list: FileList | null) => {
      if (!list || list.length === 0) return;
      const { accepted, rejected } = validateFiles(Array.from(list), { maxFiles });
      onFiles(accepted, rejected);
      // Reset so selecting the same file twice in a row still fires change.
      if (inputRef.current) inputRef.current.value = "";
    },
    [onFiles, maxFiles],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!disabled) handle(e.dataTransfer.files);
      }}
      className={cn(
        "rounded-xl border border-dashed text-center transition-colors duration-150",
        compact ? "px-5 py-8" : "px-6 py-12",
        dragging ? "border-brand-500 bg-brand-500/5" : "border-line-strong bg-canvas-raised",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
    >
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        className="sr-only"
        multiple={multiple}
        disabled={disabled}
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        onChange={(e) => handle(e.target.files)}
      />

      <UploadCloud
        aria-hidden
        className={cn(
          "mx-auto transition-colors",
          compact ? "size-6" : "size-8",
          dragging ? "text-brand-400" : "text-content-faint",
        )}
      />
      <p className={cn("font-medium text-content", compact ? "mt-3 text-sm" : "mt-4 text-base")}>
        {title}
      </p>
      <p className="mt-1 text-xs text-content-faint">{hint}</p>

      <Button
        type="button"
        variant={compact ? "secondary" : "primary"}
        size={compact ? "sm" : "md"}
        className="mt-4"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        {multiple ? "Choose files" : "Choose file"}
      </Button>
    </div>
  );
}
