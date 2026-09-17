"use client";
import { useEffect } from "react";

/**
 * Catches a password recovery link that landed on the wrong page.
 *
 * The API asks Supabase to send people to /reset-password, but Supabase only
 * honours that if the URL is on its redirect allowlist. When it is not, it
 * quietly uses the project's Site URL instead — the token still arrives, in
 * the fragment, just attached to whatever page that happens to be. The person
 * sees the dashboard or the sign-in form and has no way to continue, which
 * looks exactly like a broken reset email.
 *
 * Rather than depend on a dashboard setting being right, this watches every
 * page for a recovery fragment and forwards it to the page that handles it.
 * Allowlisting the URL is still worth doing — it saves this hop — but nothing
 * breaks when it has not been done.
 *
 * Deliberately narrow: it moves only on `type=recovery`. A Google sign-in
 * callback carries an access token in the fragment too, and hijacking that
 * would break sign-in to fix a redirect.
 */
export function RecoveryLinkCatcher() {
  useEffect(() => {
    if (window.location.pathname.startsWith("/reset-password")) return;

    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const query = new URLSearchParams(window.location.search);
    const type = fragment.get("type") ?? query.get("type");
    if (type !== "recovery") return;

    // Carry the fragment across verbatim — it holds the token, and it is what
    // the reset page reads. replace() rather than push(), so Back does not
    // return to a page holding a live credential.
    window.location.replace(
      `/reset-password${window.location.search}${window.location.hash}`,
    );
  }, []);

  return null;
}
