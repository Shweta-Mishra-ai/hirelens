"use client";
import { useRef } from "react";
import { cn } from "@/lib/cn";

export interface TabItem {
  id: string;
  label: string;
  /** Rendered as a muted count chip after the label. */
  count?: number;
  icon?: React.ReactNode;
}

/**
 * Roving-tabindex tablist. The previous build rendered nine plain <button>s
 * with no ARIA roles and no keyboard navigation between them.
 */
export function Tabs({
  items,
  value,
  onChange,
  className,
}: {
  items: readonly TabItem[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  function onKeyDown(e: React.KeyboardEvent) {
    const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : e.key === "Home" ? "first" : e.key === "End" ? "last" : null;
    if (dir === null) return;
    e.preventDefault();
    const i = items.findIndex((t) => t.id === value);
    const next =
      dir === "first" ? 0 : dir === "last" ? items.length - 1 : (i + dir + items.length) % items.length;
    onChange(items[next].id);
    listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  }

  return (
    <div
      ref={listRef}
      role="tablist"
      onKeyDown={onKeyDown}
      className={cn(
        "flex gap-0.5 overflow-x-auto border-b border-line px-1 [scrollbar-width:none]",
        "[&::-webkit-scrollbar]:hidden",
        className,
      )}
    >
      {items.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            role="tab"
            type="button"
            id={`tab-${t.id}`}
            aria-selected={active}
            aria-controls={`panel-${t.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cn(
              "relative -mb-px flex shrink-0 items-center gap-2 whitespace-nowrap px-3.5 py-2.5",
              "border-b-2 text-sm font-medium transition-colors duration-150",
              "focus-visible:outline-none focus-visible:bg-canvas-overlay",
              active
                ? "border-brand-500 text-content"
                : "border-transparent text-content-faint hover:text-content-muted",
            )}
          >
            {t.icon && <span aria-hidden className="inline-flex">{t.icon}</span>}
            {t.label}
            {t.count !== undefined && (
              <span
                className={cn(
                  "rounded px-1.5 py-px text-2xs tabular",
                  active ? "bg-brand-500/15 text-brand-300" : "bg-canvas-overlay text-content-faint",
                )}
              >
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({
  id,
  active,
  children,
}: {
  id: string;
  active: boolean;
  children: React.ReactNode;
}) {
  if (!active) return null;
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} tabIndex={0} className="animate-fade-in focus:outline-none">
      {children}
    </div>
  );
}
