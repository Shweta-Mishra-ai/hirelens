-- HireLens — 006: cover the foreign keys, and stop RLS re-evaluating auth.uid()
--
-- Two findings from Supabase's own database linter, neither of which changes
-- who can see what — only how much work the database does to decide it.
--
-- Idempotent: safe to run more than once.

-- ── Foreign keys without a covering index ───────────────────────────────────
-- Postgres does not index a foreign key for you. Without one, every delete of
-- a referenced row sequentially scans the referencing table to check the
-- constraint — so removing a team scans every invite, and removing a user
-- scans every comment and vote.
CREATE INDEX IF NOT EXISTS idx_report_comments_user
    ON public.report_comments (user_id);
CREATE INDEX IF NOT EXISTS idx_report_votes_user
    ON public.report_votes (user_id);
CREATE INDEX IF NOT EXISTS idx_team_invites_invited_by
    ON public.team_invites (invited_by);
CREATE INDEX IF NOT EXISTS idx_team_invites_team
    ON public.team_invites (team_id);
CREATE INDEX IF NOT EXISTS idx_teams_owner
    ON public.teams (owner_id);

-- ── auth.uid() evaluated once per query, not once per row ───────────────────
-- `auth.uid() = user_id` is re-evaluated for every row scanned. Wrapping it as
-- `(select auth.uid())` turns it into an InitPlan that runs once. Identical
-- semantics, and the difference grows with the size of the table.
--
-- These policies protect the anon and authenticated keys. The API itself
-- connects with the service-role key and filters on user_id in application
-- code, so nothing here is the only thing standing between two tenants.

DROP POLICY IF EXISTS "Users own their reports" ON public.reports;
CREATE POLICY "Users own their reports" ON public.reports
    FOR ALL USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS "You can edit your own profile" ON public.profiles;
CREATE POLICY "You can edit your own profile" ON public.profiles
    FOR UPDATE USING ((SELECT auth.uid()) = id)
    WITH CHECK ((SELECT auth.uid()) = id);

DROP POLICY IF EXISTS "Team members can view their teams" ON public.teams;
CREATE POLICY "Team members can view their teams" ON public.teams
    FOR SELECT USING (
        owner_id = (SELECT auth.uid())
        OR id IN (
            SELECT team_id FROM public.team_members
            WHERE user_id = (SELECT auth.uid())
        )
    );

DROP POLICY IF EXISTS "Team members can view membership" ON public.team_members;
CREATE POLICY "Team members can view membership" ON public.team_members
    FOR SELECT USING (
        team_id IN (
            SELECT tm.team_id FROM public.team_members tm
            WHERE tm.user_id = (SELECT auth.uid())
        )
    );

DROP POLICY IF EXISTS "Team members can view/add comments on accessible reports"
    ON public.report_comments;
CREATE POLICY "Team members can view/add comments on accessible reports"
    ON public.report_comments
    FOR ALL USING (
        report_id IN (
            SELECT r.id FROM public.reports r
            WHERE r.user_id = (SELECT auth.uid())
               OR r.team_id IN (
                    SELECT tm.team_id FROM public.team_members tm
                    WHERE tm.user_id = (SELECT auth.uid())
               )
        )
    );

DROP POLICY IF EXISTS "Team members can view/cast votes on accessible reports"
    ON public.report_votes;
CREATE POLICY "Team members can view/cast votes on accessible reports"
    ON public.report_votes
    FOR ALL USING (
        report_id IN (
            SELECT r.id FROM public.reports r
            WHERE r.user_id = (SELECT auth.uid())
               OR r.team_id IN (
                    SELECT tm.team_id FROM public.team_members tm
                    WHERE tm.user_id = (SELECT auth.uid())
               )
        )
    );

DROP POLICY IF EXISTS saved_jds_owner_all ON public.saved_jds;
CREATE POLICY saved_jds_owner_all ON public.saved_jds
    FOR ALL USING ((SELECT auth.uid()) = user_id)
    WITH CHECK ((SELECT auth.uid()) = user_id);

-- ── team_invites: say the rule out loud ─────────────────────────────────────
-- RLS was on with no policy, which denies everything and is the safe default —
-- but a table with no policy reads like an oversight rather than a decision,
-- and the next person to look cannot tell which it was. An invitee may read
-- the invitation addressed to them; everything else goes through the API.
--
-- The address is compared without lower() on the column because sql/004
-- normalises every row on write and backfilled the existing ones.
--
-- NOTE: Supabase's linter still reports auth_rls_initplan for this policy.
-- The subquery IS present — `pg_policies.qual` shows it, so Postgres runs it
-- as an InitPlan once per query, not once per row. The linter appears to match
-- `(select auth.<fn>())` only when it is compared directly against a column,
-- not when it is nested inside another call. Left as written rather than
-- contorted to satisfy a pattern match; the table holds a handful of rows per
-- team in any case.
DROP POLICY IF EXISTS team_invites_addressee_select ON public.team_invites;
CREATE POLICY team_invites_addressee_select ON public.team_invites
    FOR SELECT USING (
        email = lower(COALESCE((SELECT auth.jwt() ->> 'email'), ''))
    );
