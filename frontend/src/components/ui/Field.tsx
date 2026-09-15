"use client";
import { forwardRef, useId } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";

const CONTROL =
  "w-full rounded-md border border-line-strong bg-canvas-inset px-3 text-content " +
  "placeholder:text-content-faint transition-colors duration-150 " +
  "hover:border-line-strong/80 focus:border-brand-500 focus:outline-none focus:shadow-focus " +
  "disabled:cursor-not-allowed disabled:opacity-50";

function Label({ htmlFor, children, hint }: { htmlFor: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="mb-1.5 flex items-baseline justify-between gap-3">
      <label htmlFor={htmlFor} className="text-xs font-medium text-content-muted">
        {children}
      </label>
      {hint}
    </div>
  );
}

function ErrorText({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <p id={id} role="alert" className="mt-1.5 text-xs text-critical">
      {children}
    </p>
  );
}

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: React.ReactNode;
  error?: string | null;
  icon?: React.ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, icon, className, id, ...rest },
  ref,
) {
  const auto = useId();
  const inputId = id ?? auto;
  const errId = `${inputId}-error`;
  return (
    <div className="w-full">
      {label && <Label htmlFor={inputId} hint={hint}>{label}</Label>}
      <div className="relative">
        {icon && (
          <span aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-faint">
            {icon}
          </span>
        )}
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errId : undefined}
          className={cn(CONTROL, "h-9", icon && "pl-9", error && "border-critical focus:border-critical", className)}
          {...rest}
        />
      </div>
      {error && <ErrorText id={errId}>{error}</ErrorText>}
    </div>
  );
});

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  hint?: React.ReactNode;
  error?: string | null;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, error, className, id, ...rest },
  ref,
) {
  const auto = useId();
  const taId = id ?? auto;
  const errId = `${taId}-error`;
  return (
    <div className="flex w-full flex-col">
      {label && <Label htmlFor={taId} hint={hint}>{label}</Label>}
      <textarea
        ref={ref}
        id={taId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errId : undefined}
        className={cn(CONTROL, "py-2.5 leading-relaxed", error && "border-critical", className)}
        {...rest}
      />
      {error && <ErrorText id={errId}>{error}</ErrorText>}
    </div>
  );
});

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: readonly { value: string; label: string }[];
}

/**
 * A native <select> with the OS chrome suppressed and our own chevron. The
 * previous build rendered a bare browser dropdown next to custom controls,
 * which was the most visible inconsistency on the dashboard.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, options, className, id, ...rest },
  ref,
) {
  const auto = useId();
  const selId = id ?? auto;
  return (
    <div className="w-full">
      {label && <Label htmlFor={selId}>{label}</Label>}
      <div className="relative">
        <select
          ref={ref}
          id={selId}
          className={cn(CONTROL, "h-9 cursor-pointer appearance-none pr-9", className)}
          {...rest}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value} className="bg-canvas-overlay text-content">
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          aria-hidden
          className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-content-faint"
        />
      </div>
    </div>
  );
});
