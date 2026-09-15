import { describe, it, expect } from "vitest";
import { validateFiles } from "@/components/FileDropzone";

function file(name: string, sizeMb: number) {
  const f = new File(["x"], name, { type: "application/pdf" });
  Object.defineProperty(f, "size", { value: Math.round(sizeMb * 1024 * 1024) });
  return f;
}

describe("validateFiles", () => {
  it("accepts PDF and DOCX", () => {
    const { accepted, rejected } = validateFiles([file("a.pdf", 1), file("b.docx", 1)]);
    expect(accepted).toHaveLength(2);
    expect(rejected).toHaveLength(0);
  });

  it("is case-insensitive about the extension", () => {
    const { accepted } = validateFiles([file("A.PDF", 1), file("B.DocX", 1)]);
    expect(accepted).toHaveLength(2);
  });

  it("rejects unsupported types with the reason attached to the file", () => {
    const { accepted, rejected } = validateFiles([file("resume.txt", 1)]);
    expect(accepted).toHaveLength(0);
    expect(rejected[0].file.name).toBe("resume.txt");
    expect(rejected[0].reason).toMatch(/PDF or DOCX/);
  });

  it("rejects an extensionless file", () => {
    const { rejected } = validateFiles([file("resume", 1)]);
    expect(rejected).toHaveLength(1);
  });

  it("rejects empty files", () => {
    const { rejected } = validateFiles([file("empty.pdf", 0)]);
    expect(rejected[0].reason).toMatch(/empty/i);
  });

  it("enforces the size limit and names the actual size", () => {
    const { accepted, rejected } = validateFiles([file("huge.pdf", 12)]);
    expect(accepted).toHaveLength(0);
    expect(rejected[0].reason).toContain("12.0 MB");
    expect(rejected[0].reason).toContain("10MB");
  });

  it("enforces a batch cap, rejecting the overflow rather than dropping it silently", () => {
    const files = Array.from({ length: 5 }, (_, i) => file(`r${i}.pdf`, 1));
    const { accepted, rejected } = validateFiles(files, { maxFiles: 3 });
    expect(accepted).toHaveLength(3);
    expect(rejected).toHaveLength(2);
    expect(rejected[0].reason).toMatch(/3 files/);
  });

  it("reports every problem in a mixed batch", () => {
    const { accepted, rejected } = validateFiles([
      file("good.pdf", 1),
      file("bad.exe", 1),
      file("huge.pdf", 50),
    ]);
    expect(accepted.map((f) => f.name)).toEqual(["good.pdf"]);
    expect(rejected).toHaveLength(2);
  });

  it("handles an empty selection", () => {
    const { accepted, rejected } = validateFiles([]);
    expect(accepted).toHaveLength(0);
    expect(rejected).toHaveLength(0);
  });
});
