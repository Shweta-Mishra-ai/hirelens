import type React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErrorBoundary } from "@/components/ErrorBoundary";

/**
 * React unmounts the whole tree when a render throws, so without a boundary
 * a single bad value replaces the entire app with a generic crash page —
 * navigation included. Verified against the running app: a `reports` field
 * arriving as an object instead of an array did exactly that.
 */
// React.JSX, not the bare global: React 19 removed the global JSX namespace,
// so `JSX.Element` no longer resolves.
function Boom({ shouldThrow = true }: { shouldThrow?: boolean }): React.JSX.Element {
  if (shouldThrow) throw new TypeError("simulated render failure");
  return <p>recovered content</p>;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs the caught error; keep the test output readable.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary title="The list">
        <p>all good</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("all good")).toBeInTheDocument();
  });

  it("catches a render error instead of unmounting the tree", () => {
    render(
      <ErrorBoundary title="The flags list">
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/couldn't be displayed/i)).toBeInTheDocument();
  });

  it("names the section that failed, so the user knows what is missing", () => {
    render(
      <ErrorBoundary title="The flags list">
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/The flags list couldn't be displayed/i)).toBeInTheDocument();
  });

  it("reassures that nothing was lost", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/nothing has been lost/i)).toBeInTheDocument();
  });

  it("never shows the raw error or a stack trace", () => {
    const { container } = render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(container.textContent).not.toContain("simulated render failure");
    expect(container.textContent).not.toContain("TypeError");
  });

  it("siblings outside the boundary keep rendering", () => {
    render(
      <div>
        <nav>navigation</nav>
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      </div>,
    );
    expect(screen.getByText("navigation")).toBeInTheDocument();
  });

  it("recovers when the user retries", async () => {
    // React renders a failing child twice (once to recover, once to surface
    // the error), so a "throw on first render" flag is not reliable here.
    // Flip the condition from outside instead, which is what a retry after a
    // transient data problem actually looks like.
    let broken = true;
    function Flaky() {
      if (broken) throw new Error("transient");
      return <p>recovered content</p>;
    }

    render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/couldn't be displayed/i)).toBeInTheDocument();

    broken = false;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText("recovered content")).toBeInTheDocument();
  });

  it("resets when resetKeys change, e.g. navigating to another report", () => {
    const { rerender } = render(
      <ErrorBoundary resetKeys={["report-1"]}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/couldn't be displayed/i)).toBeInTheDocument();

    rerender(
      <ErrorBoundary resetKeys={["report-2"]}>
        <Boom shouldThrow={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("recovered content")).toBeInTheDocument();
  });

  it("supports a custom fallback", () => {
    render(
      <ErrorBoundary fallback={() => <p>custom fallback</p>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("custom fallback")).toBeInTheDocument();
  });
});
