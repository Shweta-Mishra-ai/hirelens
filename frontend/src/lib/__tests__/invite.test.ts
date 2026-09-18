import { describe, it, expect } from "vitest";
import { readInviteParams, withInvite } from "@/lib/invite";

/**
 * An invite is accepted by whoever signs in with the invited address. The
 * link carried that address all along, but neither auth page read it — so
 * people retyped it by hand, and a typo meant joining nothing with nobody
 * told. Anyone who already had an account got "this email already exists"
 * and a dead end.
 */

function params(query: string) {
  return new URLSearchParams(query);
}

describe("readInviteParams", () => {
  it("reads the address and team from an invite link", () => {
    const invite = readInviteParams(params("invite_email=anita@acme.com&team_id=t1"));
    expect(invite).toEqual({ email: "anita@acme.com", teamId: "t1" });
  });

  it("returns nothing for an ordinary visit", () => {
    expect(readInviteParams(params(""))).toEqual({ email: null, teamId: null });
  });

  it("survives no search params at all", () => {
    expect(readInviteParams(null)).toEqual({ email: null, teamId: null });
  });

  it("ignores a value that is not an address", () => {
    expect(readInviteParams(params("invite_email=notanemail")).email).toBeNull();
  });

  it("trims surrounding whitespace", () => {
    expect(readInviteParams(params("invite_email=%20anita@acme.com%20")).email).toBe("anita@acme.com");
  });

  it("takes the team on its own", () => {
    expect(readInviteParams(params("team_id=t1"))).toEqual({ email: null, teamId: "t1" });
  });
});

describe("withInvite", () => {
  it("carries the invite to the other auth page", () => {
    const url = withInvite("/login", { email: "anita@acme.com", teamId: "t1" });
    expect(url.startsWith("/login?")).toBe(true);
    const back = readInviteParams(params(url.split("?")[1]));
    expect(back).toEqual({ email: "anita@acme.com", teamId: "t1" });
  });

  it("escapes an address that needs it", () => {
    const url = withInvite("/login", { email: "a+tag@acme.com", teamId: null });
    expect(readInviteParams(params(url.split("?")[1])).email).toBe("a+tag@acme.com");
  });

  it("leaves the path alone when there is no invite", () => {
    expect(withInvite("/login", { email: null, teamId: null })).toBe("/login");
  });
});
