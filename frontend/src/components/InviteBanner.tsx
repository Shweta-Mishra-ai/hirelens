"use client";
import { Users } from "lucide-react";

/**
 * Tells someone arriving on an invite link what is actually happening, and
 * that the address is the part that matters. Without it the link looked
 * like an ordinary signup page and the address was theirs to retype —
 * which is how people ended up joining nothing.
 */
export function InviteBanner({ email, mode }: { email: string; mode: "signup" | "login" }) {
  return (
    <div className="mb-5 flex gap-3 rounded-lg border border-brand-500/30 bg-brand-500/10 p-3.5">
      <Users aria-hidden className="mt-0.5 size-4 shrink-0 text-brand-400" />
      <div className="text-sm">
        <p className="font-medium text-content">You&rsquo;ve been invited to a hiring team</p>
        <p className="mt-1 leading-relaxed text-content-muted">
          {mode === "signup"
            ? "Create your account with "
            : "Sign in as "}
          <span className="font-medium text-content">{email}</span>
          {" "}and you&rsquo;ll join it automatically. Use a different address and the
          invite won&rsquo;t find you.
        </p>
      </div>
    </div>
  );
}
