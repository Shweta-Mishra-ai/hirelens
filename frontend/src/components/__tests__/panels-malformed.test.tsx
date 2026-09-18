import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AIContentPanel } from "@/components/report/AIContentPanel";
import { VerifyPanel } from "@/components/report/VerifyPanel";
import { asList } from "@/lib/list";

/**
 * Report panels iterate nested fields directly. A report written by an older
 * build, saved partially, or holding a field whose type changed therefore
 * threw during render — and a throw in render takes the whole panel down,
 * error boundary or not. These check the panels cope instead.
 */

describe("asList", () => {
  it("passes a list through", () => {
    expect(asList([1, 2])).toEqual([1, 2]);
  });

  it.each([undefined, null, "text", 5, {}, true])("turns %s into an empty list", (value) => {
    expect(asList(value)).toEqual([]);
  });

  it("does not explode a string into characters", () => {
    expect(asList("AWS")).toEqual([]);
  });
});

describe("AIContentPanel with fields missing", () => {
  it("renders when the indicator lists are absent", () => {
    render(<AIContentPanel analysis={{ likelihood: "low" } as never} />);
    expect(screen.getByText(/AI-writing patterns/i)).toBeInTheDocument();
  });

  it("renders when the indicator lists are the wrong type", () => {
    render(
      <AIContentPanel
        analysis={{ likelihood: "high", indicators: "lots", human_indicators: {} } as never}
      />,
    );
    expect(screen.getByText(/AI-writing patterns/i)).toBeInTheDocument();
  });

  it("still lists real indicators", () => {
    render(
      <AIContentPanel
        analysis={{ likelihood: "medium", indicators: ["Uniform sentence length"], human_indicators: [] } as never}
      />,
    );
    expect(screen.getByText("Uniform sentence length")).toBeInTheDocument();
  });
});

describe("VerifyPanel with fields missing", () => {
  const minimal = { run_at: "2026-01-01T00:00:00Z", github: { status: "no_username" } };

  it("renders when every check list is absent", () => {
    render(
      <VerifyPanel
        verification={minimal as never}
        loading={false}
        error={null}
        githubOverride=""
        onGithubOverrideChange={() => {}}
        onRun={() => {}}
      />,
    );
    expect(document.body.textContent).toBeTruthy();
  });

  it("renders when the check lists are the wrong type", () => {
    render(
      <VerifyPanel
        verification={{
          ...minimal,
          education: "none",
          certifications: 0,
          experience: {},
          trust_assessment: { verdict: "insufficient_evidence", score: 0, evidence_available: false },
        } as never}
        loading={false}
        error={null}
        githubOverride=""
        onGithubOverrideChange={() => {}}
        onRun={() => {}}
      />,
    );
    expect(document.body.textContent).toBeTruthy();
  });
});
