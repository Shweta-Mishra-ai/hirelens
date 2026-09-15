import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CareerTrajectoryPanel } from "@/components/report/CareerTrajectoryPanel";
import type { CareerTrajectory } from "@/types";

/**
 * These pin the behaviour that the previous "Talent Velocity" panel got
 * wrong: it always rendered a number, because the backend always produced
 * one (a function of role count and skill-list length that saturated at 98).
 * The discriminated union now forces the no-data case to be handled, and
 * these tests make sure it is handled by saying so rather than by printing a
 * zero.
 */

const COMPUTED: CareerTrajectory = {
  status: "computed",
  total_experience_months: 95,
  median_tenure_months: 20,
  roles_analyzed: 3,
  advancement_steps: 2,
  months_per_advancement: 48,
  gap_months: 2,
  retention_stability: 83,
  progression_score: 63,
  trajectory: "Steady advancement",
  basis: "Measured from 3 dated role(s) spanning 7.9 years.",
};

describe("CareerTrajectoryPanel", () => {
  it("renders metrics derived from real dates", () => {
    render(<CareerTrajectoryPanel data={COMPUTED} />);
    expect(screen.getByText("7.9")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("Steady advancement")).toBeInTheDocument();
    expect(screen.getByText(/one per 48 mo/)).toBeInTheDocument();
  });

  it("shows why nothing could be measured instead of inventing a score", () => {
    render(
      <CareerTrajectoryPanel
        data={{
          status: "insufficient_data",
          roles_analyzed: 1,
          reason: "Career trajectory needs at least two roles with readable dates.",
        }}
      />,
    );
    expect(screen.getByText(/Not enough dated history/i)).toBeInTheDocument();
    expect(screen.getByText(/at least two roles/i)).toBeInTheDocument();
    // No fabricated numbers anywhere in the no-data state.
    expect(screen.queryByText(/\/100/)).not.toBeInTheDocument();
    expect(screen.queryByText("98")).not.toBeInTheDocument();
  });

  it("states plainly when no advancement was observable", () => {
    render(
      <CareerTrajectoryPanel
        data={{ ...COMPUTED, advancement_steps: 0, months_per_advancement: null, trajectory: "No title advancement observed" }}
      />,
    );
    expect(screen.getByText("No title advancement observed")).toBeInTheDocument();
    expect(screen.getByText(/No upward title change was detectable/i)).toBeInTheDocument();
  });

  it("carries the caveat that these are observations, not predictions", () => {
    render(<CareerTrajectoryPanel data={COMPUTED} />);
    expect(screen.getByText(/not a prediction and not a judgement/i)).toBeInTheDocument();
  });

  it("explains that concurrent roles are not double-counted", () => {
    render(<CareerTrajectoryPanel data={COMPUTED} />);
    expect(screen.getByText(/concurrent roles counted once/i)).toBeInTheDocument();
  });
});
