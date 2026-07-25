import { createClient } from "@supabase/supabase-js";

// Next prerenders these client-component routes during `next build`.  Do not
// pass empty values to `createClient`: it throws while prerendering and makes a
// build fail before the deployment environment can provide its public vars.
// The placeholders keep the client constructible; real authentication still
// requires the documented NEXT_PUBLIC_SUPABASE_* values at runtime.
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key";

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
