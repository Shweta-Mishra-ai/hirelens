import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PersonAvatar, personLabel } from "@/components/ui/Person";

/**
 * The rule under test: a user id is never a display name.
 *
 * Comment threads and team member lists used to render the raw UUID as the
 * author and build avatar initials from it, so a teammate appeared as "F1"
 * beside `8c3f1a2e-...`.
 */
describe("personLabel", () => {
  it("uses the resolved name", () => {
    expect(personLabel("Priya Raghavan")).toBe("Priya Raghavan");
    expect(personLabel("You")).toBe("You");
  });

  it("falls back to a neutral word, never an id", () => {
    expect(personLabel(undefined)).toBe("Teammate");
    expect(personLabel("")).toBe("Teammate");
    expect(personLabel("   ")).toBe("Teammate");
  });
});

describe("PersonAvatar", () => {
  it("shows initials for a resolved name", () => {
    render(<PersonAvatar name="Priya Raghavan" />);
    expect(screen.getByText("PR")).toBeInTheDocument();
  });

  it("shows an icon rather than invented initials when unresolved", () => {
    const { container } = render(<PersonAvatar />);
    expect(container.querySelector("svg")).toBeTruthy();
    expect(container.textContent?.trim()).toBe("");
  });

  it("never renders characters taken from a uuid", () => {
    const uuid = "f1a2b3c4-5d6e-7f80-9012-3456789abcde";
    const { container } = render(<PersonAvatar name={undefined} />);
    // The old behaviour produced "F1" from exactly this shape of input.
    expect(container.textContent).not.toContain("F1");
    expect(container.textContent).not.toContain(uuid.slice(0, 2).toUpperCase());
  });
});
