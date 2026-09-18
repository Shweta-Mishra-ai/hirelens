/**
 * The invite link's parameters, and where they need to be carried.
 *
 * An invite is sent to an email address and accepted by whoever signs in
 * with that address. The link carried `invite_email` and `team_id` all
 * along — but neither the signup nor the sign-in page ever read them, so
 * the person had to retype the address by hand. Retype it differently and
 * the invite simply never matches: they join nothing, and neither they nor
 * the person who invited them is told.
 *
 * It was worse for someone who already had an account. The link points at
 * /signup, so they got "an account with this email already exists" and a
 * dead end, with nothing to say that signing in normally would do it.
 */

export interface InviteParams {
  email: string | null;
  teamId: string | null;
}

export function readInviteParams(search: URLSearchParams | null): InviteParams {
  if (!search) return { email: null, teamId: null };
  const email = search.get("invite_email");
  const teamId = search.get("team_id");
  return {
    email: email && email.includes("@") ? email.trim() : null,
    teamId: teamId ? teamId.trim() : null,
  };
}

/** Carry the invite across to the other auth page, so the link keeps working. */
export function withInvite(path: string, invite: InviteParams): string {
  const params = new URLSearchParams();
  if (invite.email) params.set("invite_email", invite.email);
  if (invite.teamId) params.set("team_id", invite.teamId);
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}
