"use client";
import { User } from "lucide-react";
import { initials } from "@/lib/format";
import { cn } from "@/lib/cn";

/**
 * A person, rendered from whatever the server could resolve.
 *
 * The rule this exists to enforce: never derive a display name or avatar
 * initials from a user id. Ids here are UUIDs, so doing that produced
 * avatars reading "F1" and member rows showing `8c3f1a2e-...` where a name
 * belongs. When the server cannot resolve a name, we say so plainly instead
 * of manufacturing one.
 */
export function PersonAvatar({
  name,
  avatarName,
  size = "md",
  className,
}: {
  name?: string;
  /**
   * Initials source, when it differs from the label. The label for the
   * signed-in user is "You", but "YO" is a poor avatar — pass their real
   * name here so the circle still reads as them.
   */
  avatarName?: string;
  size?: "sm" | "md";
  className?: string;
}) {
  const dim = size === "sm" ? "size-7 text-2xs" : "size-8 text-xs";
  const resolved = (avatarName ?? name)?.trim();

  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-semibold",
        dim,
        resolved
          ? "bg-brand-500/15 text-brand-300"
          : "bg-canvas-overlay text-content-faint",
        className,
      )}
    >
      {resolved ? initials(resolved) : <User className="size-3.5" />}
    </span>
  );
}

/** The name to show, or an honest placeholder. */
export function personLabel(name?: string): string {
  const resolved = name?.trim();
  return resolved || "Teammate";
}
