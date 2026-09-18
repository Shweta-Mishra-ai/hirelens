import { createClient } from "@supabase/supabase-js";

// Next prerenders these client-component routes during `next build`. Do not
// pass empty values to `createClient`: it throws while prerendering and makes a
// build fail before the deployment environment can provide its public vars.
// The placeholders keep the client constructible; real authentication still
// requires the documented NEXT_PUBLIC_SUPABASE_* values at runtime.
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key";

/**
 * This client exists for exactly one thing: starting the Google OAuth
 * redirect. The session HireLens runs on is its own JWT, minted by the API
 * after it verifies the Supabase token — supabase-js never holds a session
 * this app reads.
 *
 * All three auth options are therefore off, and each one is load-bearing:
 *
 * `detectSessionInUrl` is the important one. Left on, supabase-js consumes any
 * `#access_token=…` fragment during its own async start-up and strips it from
 * the URL. That is a race against the app's own handlers — the one that
 * exchanges a Google token for a session, and the one that reads a password
 * recovery token — and the loser sees a URL with nothing in it. A race that is
 * usually won looks exactly like a feature that usually works.
 *
 * `persistSession` would otherwise leave a real Supabase access token in
 * localStorage that nothing reads and signing out does not reliably clear.
 *
 * `autoRefreshToken` would keep a background timer alive refreshing that
 * unused session for as long as the tab is open.
 */
export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    detectSessionInUrl: false,
    persistSession: false,
    autoRefreshToken: false,
  },
});
