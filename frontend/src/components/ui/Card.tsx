import { cn } from "@/lib/cn";

export function Card({
  className,
  interactive,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-line bg-canvas-raised shadow-card",
        interactive &&
          "transition-colors duration-150 ease-out hover:border-line-strong hover:bg-canvas-overlay/40",
        className,
      )}
      {...rest}
    />
  );
}

export function CardHeader({
  title,
  description,
  action,
  className,
  ...rest
}: // `title` is omitted from the base attributes: HTMLAttributes types it as
// the string tooltip attribute, which would reject a ReactNode heading.
Omit<React.HTMLAttributes<HTMLDivElement>, "title"> & {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 border-b border-line-subtle px-5 py-4",
        className,
      )}
      {...rest}
    >
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-content">{title}</h2>
        {description && (
          <p className="mt-0.5 text-xs text-content-faint">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function CardBody({ className, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...rest} />;
}

/** A labelled section inside a report panel. */
export function Section({
  title,
  eyebrow,
  action,
  children,
  className,
}: {
  title: React.ReactNode;
  eyebrow?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-3", className)}>
      <div className="flex items-baseline justify-between gap-4">
        <div>
          {eyebrow && (
            <div className="text-2xs font-semibold uppercase tracking-wider text-content-faint">
              {eyebrow}
            </div>
          )}
          <h3 className="text-base font-semibold text-content">{title}</h3>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
