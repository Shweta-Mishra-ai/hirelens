import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Field";
import { Tabs } from "@/components/ui/Tabs";
import { ScoreRing, ScorePill } from "@/components/ui/Score";
import { VerdictStamp, verdictFromRecommendation } from "@/components/VerdictStamp";

describe("Button", () => {
  it("does not fire while loading", async () => {
    const onClick = vi.fn();
    render(<Button loading onClick={onClick}>Save</Button>);
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");
    await userEvent.click(btn).catch(() => {});
    expect(onClick).not.toHaveBeenCalled();
  });

  it("fires when enabled", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("Input", () => {
  it("links its label, so clicking the label focuses the field", async () => {
    render(<Input label="Work email" />);
    await userEvent.click(screen.getByText("Work email"));
    expect(screen.getByLabelText("Work email")).toHaveFocus();
  });

  it("exposes an error to assistive tech, not just to sighted users", () => {
    render(<Input label="Email" error="Enter a valid email address." />);
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid email address.");
    expect(input.getAttribute("aria-describedby")).toBe(screen.getByRole("alert").id);
  });

  it("sets no aria-invalid when there is no error", () => {
    render(<Input label="Email" />);
    expect(screen.getByLabelText("Email")).not.toHaveAttribute("aria-invalid");
  });
});

describe("Select", () => {
  it("renders its options and reports changes", async () => {
    const onChange = vi.fn();
    render(
      <Select
        label="Sort"
        value="newest"
        onChange={onChange}
        options={[
          { value: "newest", label: "Newest first" },
          { value: "oldest", label: "Oldest first" },
        ]}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "oldest");
    expect(onChange).toHaveBeenCalled();
  });
});

describe("Tabs", () => {
  const items = [
    { id: "overview", label: "Overview" },
    { id: "flags", label: "Flags", count: 4 },
    { id: "skills", label: "Skills" },
  ];

  it("marks exactly one tab selected", () => {
    render(<Tabs items={items} value="flags" onChange={() => {}} />);
    const selected = screen.getAllByRole("tab").filter((t) => t.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent("Flags");
  });

  it("moves between tabs with the arrow keys", async () => {
    const onChange = vi.fn();
    render(<Tabs items={items} value="overview" onChange={onChange} />);
    screen.getByRole("tab", { name: /Overview/ }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("flags");
  });

  it("wraps around at the ends", async () => {
    const onChange = vi.fn();
    render(<Tabs items={items} value="overview" onChange={onChange} />);
    screen.getByRole("tab", { name: /Overview/ }).focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenCalledWith("skills");
  });

  it("keeps only the active tab in the tab order", () => {
    render(<Tabs items={items} value="flags" onChange={() => {}} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.filter((t) => t.getAttribute("tabindex") === "0")).toHaveLength(1);
  });
});

describe("ScoreRing", () => {
  it("describes the score for screen readers", () => {
    render(<ScoreRing score={74} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/74 out of 100/);
  });

  it("clamps out-of-range and non-finite scores", () => {
    render(<ScoreRing score={150} />);
    expect(screen.getByText("100")).toBeInTheDocument();
    cleanupRender(<ScoreRing score={-20} />, "0");
    cleanupRender(<ScoreRing score={NaN} />, "0");
  });

  function cleanupRender(el: React.ReactElement, expected: string) {
    const { unmount } = render(el);
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
    unmount();
  }
});

describe("ScorePill", () => {
  it("renders the clamped score", () => {
    render(<ScorePill score={74} />);
    expect(screen.getByText("74")).toBeInTheDocument();
  });
});

describe("VerdictStamp", () => {
  it("maps every known recommendation", () => {
    expect(verdictFromRecommendation("recommended")).toBe("recommended");
    expect(verdictFromRecommendation("high_risk")).toBe("high_risk");
    expect(verdictFromRecommendation("manual_review")).toBe("manual_review");
  });

  it("falls back to manual review for anything unrecognised", () => {
    // A verdict must never silently become "recommended" because the backend
    // sent something this build doesn't know about.
    for (const bad of ["", "approved", "unknown", null, undefined]) {
      expect(verdictFromRecommendation(bad as string)).toBe("manual_review");
    }
  });

  it("uses investigative wording, never an adjudication", () => {
    render(<VerdictStamp verdict="high_risk" />);
    expect(screen.getByText("High risk")).toBeInTheDocument();
    expect(screen.queryByText(/reject/i)).not.toBeInTheDocument();
  });
});
