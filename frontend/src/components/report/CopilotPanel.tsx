"use client";
import { Check, Plus, Save, X } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input, Textarea } from "@/components/ui/Field";
import { Alert } from "@/components/ui/Feedback";
import { cn } from "@/lib/cn";

export interface ScorecardItem {
  category: string;
  label: string;
  score: number;
  notes: string;
}

export interface ProbeQuestion {
  question: string;
  category?: string;
  is_asked: boolean;
}

const RATING_SCALE = [1, 2, 3, 4, 5] as const;

function RatingInput({
  value,
  onChange,
  label,
}: {
  value: number;
  onChange: (n: number) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={`${label} rating`} className="flex gap-1">
      {RATING_SCALE.map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={`${n} out of 5`}
          onClick={() => onChange(value === n ? 0 : n)}
          className={cn(
            "size-7 rounded-md border text-xs font-medium tabular transition-colors",
            "focus-visible:outline-none focus-visible:shadow-focus",
            n <= value
              ? "border-brand-500 bg-brand-500/15 text-brand-300"
              : "border-line-strong bg-canvas-inset text-content-faint hover:border-line-strong hover:text-content-muted",
          )}
        >
          {n}
        </button>
      ))}
    </div>
  );
}

/**
 * Live interview companion.
 *
 * Note what this panel does NOT claim. The previous version labelled the
 * save button "Your decision trains the AI model" — nothing in this system
 * trains on recruiter input, and telling users their notes shape the model
 * both misrepresents the product and invites them to enter data they
 * otherwise wouldn't. The copy now says exactly what happens: it saves to
 * this report.
 */
export function CopilotPanel({
  scorecard,
  onScorecardChange,
  questions,
  onQuestionsChange,
  newQuestion,
  onNewQuestionChange,
  notes,
  onNotesChange,
  saving,
  success,
  error,
  onSave,
}: {
  scorecard: ScorecardItem[];
  onScorecardChange: (next: ScorecardItem[]) => void;
  questions: ProbeQuestion[];
  onQuestionsChange: (next: ProbeQuestion[]) => void;
  newQuestion: string;
  onNewQuestionChange: (v: string) => void;
  notes: string;
  onNotesChange: (v: string) => void;
  saving: boolean;
  success: boolean;
  error: string | null;
  onSave: () => void;
}) {
  function addQuestion() {
    const q = newQuestion.trim();
    if (!q) return;
    onQuestionsChange([...questions, { question: q, category: "custom", is_asked: false }]);
    onNewQuestionChange("");
  }

  const askedCount = questions.filter((q) => q.is_asked).length;

  return (
    <div className="space-y-5">
      {error && <Alert tone="error">{error}</Alert>}
      {success && <Alert tone="success">Saved to this candidate&apos;s file.</Alert>}

      <Card>
        <CardHeader
          title="Interview scorecard"
          description="Rate each area 1–5 as the interview runs. Saved against this report only."
        />
        <CardBody className="space-y-4">
          {scorecard.map((item, i) => (
            <div key={item.category} className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <label className="text-sm font-medium text-content">{item.label}</label>
                <RatingInput
                  label={item.label}
                  value={item.score}
                  onChange={(score) =>
                    onScorecardChange(
                      scorecard.map((s, idx) => (idx === i ? { ...s, score } : s)),
                    )
                  }
                />
              </div>
              <Input
                value={item.notes}
                onChange={(e) =>
                  onScorecardChange(
                    scorecard.map((s, idx) =>
                      idx === i ? { ...s, notes: e.target.value } : s,
                    ),
                  )
                }
                placeholder={`What did you observe on ${item.label.toLowerCase()}?`}
                aria-label={`${item.label} notes`}
              />
            </div>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Probe questions"
          description="Generated against this candidate's specific flags. Tick them off as you go, or add your own."
          action={
            questions.length > 0 ? (
              <span className="text-xs tabular text-content-faint">
                {askedCount}/{questions.length} asked
              </span>
            ) : null
          }
        />
        <CardBody className="space-y-3">
          {questions.length === 0 ? (
            <p className="text-sm text-content-faint">
              No questions yet. Add one below.
            </p>
          ) : (
            <ul className="space-y-2">
              {questions.map((q, i) => (
                <li
                  key={i}
                  className={cn(
                    "flex items-start gap-3 rounded-lg border px-3.5 py-3 transition-colors",
                    q.is_asked
                      ? "border-positive-line bg-positive-soft"
                      : "border-line bg-canvas-inset",
                  )}
                >
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={q.is_asked}
                    aria-label={`Mark as asked: ${q.question}`}
                    onClick={() =>
                      onQuestionsChange(
                        questions.map((x, idx) =>
                          idx === i ? { ...x, is_asked: !x.is_asked } : x,
                        ),
                      )
                    }
                    className={cn(
                      "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border transition-colors",
                      "focus-visible:outline-none focus-visible:shadow-focus",
                      q.is_asked
                        ? "border-positive bg-positive text-canvas"
                        : "border-line-strong hover:border-content-faint",
                    )}
                  >
                    {q.is_asked && <Check className="size-3" strokeWidth={3} />}
                  </button>

                  <span
                    className={cn(
                      "min-w-0 flex-1 text-sm leading-relaxed",
                      q.is_asked ? "text-content-faint line-through" : "text-content-muted",
                    )}
                  >
                    {q.question}
                  </span>

                  {q.category && (
                    <Badge tone="neutral" className="shrink-0 capitalize">
                      {q.category}
                    </Badge>
                  )}

                  <button
                    type="button"
                    aria-label={`Remove question: ${q.question}`}
                    onClick={() => onQuestionsChange(questions.filter((_, idx) => idx !== i))}
                    className="shrink-0 rounded p-0.5 text-content-faint transition-colors hover:text-critical"
                  >
                    <X className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex gap-2">
            <div className="flex-1">
              <Input
                value={newQuestion}
                onChange={(e) => onNewQuestionChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addQuestion();
                  }
                }}
                placeholder="Add your own question…"
                aria-label="New probe question"
              />
            </div>
            <Button
              icon={<Plus className="size-4" />}
              disabled={!newQuestion.trim()}
              onClick={addQuestion}
            >
              Add
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Interview notes" />
        <CardBody className="space-y-4">
          <Textarea
            rows={6}
            value={notes}
            onChange={(e) => onNotesChange(e.target.value)}
            placeholder="What stood out? What still needs checking?"
            aria-label="Interview notes"
          />
          <div className="flex items-center justify-between gap-4">
            <p className="text-xs text-content-faint">
              Saved to this candidate&apos;s file and visible to anyone you share it with.
            </p>
            <Button
              variant="primary"
              loading={saving}
              icon={<Save className="size-4" />}
              onClick={onSave}
            >
              Save
            </Button>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
