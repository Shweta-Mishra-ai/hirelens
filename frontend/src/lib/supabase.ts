import { createClient } from "@supabase/supabase-js";

// Next prerenders client-component routes during `next build`. Do not pass
// empty values to `createClient`, because it throws before deployment env vars
// can be provided. Real auth still requires the documented public Supabase vars.
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key";

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
