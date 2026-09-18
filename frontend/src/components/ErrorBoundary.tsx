"use client";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

/**
 * Section-level error boundary.
 *
 * React unmounts the entire tree when a render throws, so without a boundary
 * one bad value takes the whole page with it — verified: a malformed reports
 * payload replaced the app with "Application error: a client-side exception
 * has occurred", losing the navigation and any way back.
 *
 * Wrapping each independent region means a broken panel degrades to a small
 * inline message while the rest of the page — crucially the nav — keeps
 * working. `title` should name the region so the user knows what is missing
 * rather than doubting the whole screen.
 */
interface Props {
  children: ReactNode;
  /** What failed, in the user's terms: "the flags list", "this chart". */
  title?: string;
  /** Rendered instead of the default card when supplied. */
  fallback?: (reset: () => void) => ReactNode;
  /** Changing any of these resets the boundary — e.g. navigating to a new report. */
  resetKeys?: unknown[];
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: Props) {
    if (!this.state.error || !this.props.resetKeys) return;
    const changed =
      prev.resetKeys?.length !== this.props.resetKeys.length ||
      this.props.resetKeys.some((k, i) => !Object.is(k, prev.resetKeys?.[i]));
    if (changed) this.setState({ error: null });
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the detail in the console for whoever is debugging; the UI stays
    // plain. Nothing here is shown to the user verbatim — a stack trace is
    // not something a recruiter can act on.
    console.error(`[HireLens] ${this.props.title ?? "Section"} failed to render`, error, info);
  }

  private reset = () => this.setState({ error: null });

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(this.reset);

    const what = this.props.title ?? "This section";
    return (
      <Card className="border-critical-line bg-critical-soft/40 p-5">
        <div className="flex items-start gap-3">
          <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-critical" />
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-medium text-content">{what} couldn&apos;t be displayed</h3>
            <p className="mt-1 text-sm leading-relaxed text-content-muted">
              Something in this data didn&apos;t look the way the page expected. The rest of the
              page still works, and nothing has been lost.
            </p>
            <Button
              size="sm"
              className="mt-3"
              icon={<RotateCcw className="size-3.5" />}
              onClick={this.reset}
            >
              Try again
            </Button>
          </div>
        </div>
      </Card>
    );
  }
}
