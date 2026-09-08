import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Button, Badge, TextInput } from "@/components/ui/primitives";

describe("UI primitives", () => {
  it("Button renders children and responds to clicks", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Analyze Resume</Button>);
    fireEvent.click(screen.getByText("Analyze Resume"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("Button does not fire onClick when disabled", () => {
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabled>
        Export CSV
      </Button>,
    );
    fireEvent.click(screen.getByText("Export CSV"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("Badge renders its label text", () => {
    render(<Badge tone="success">All systems operational</Badge>);
    expect(screen.getByText("All systems operational")).toBeInTheDocument();
  });

  it("TextInput forwards value + onChange like a normal input", () => {
    const onChange = vi.fn();
    render(<TextInput value="ada" onChange={onChange} placeholder="Search…" />);
    const input = screen.getByPlaceholderText("Search…") as HTMLInputElement;
    expect(input.value).toBe("ada");
    fireEvent.change(input, { target: { value: "grace" } });
    expect(onChange).toHaveBeenCalledOnce();
  });
});
