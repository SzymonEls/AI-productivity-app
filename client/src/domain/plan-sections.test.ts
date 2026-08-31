import { describe, expect, it } from "vitest";

import { NoSuchSection, appendSection, removeSection, sectionRanges } from "./plan-sections";

const PLAN = "# One\n\n- a\n\n# Two\n\n- b\n\n# Three\n\n- c\n";

describe("sectionRanges", () => {
  it("finds every top-level heading", () => {
    expect(sectionRanges(PLAN).map((s) => s.title)).toEqual(["One", "Two", "Three"]);
  });

  it("ignores a heading with no text and deeper levels", () => {
    expect(sectionRanges("#\n## Two\n# Real\n").map((s) => s.title)).toEqual(["Real"]);
  });

  it("has nothing to find in a plan without headings", () => {
    expect(sectionRanges("- just a list\n")).toEqual([]);
  });
});

describe("removeSection", () => {
  it("takes the section out and leaves the rest joined up", () => {
    const { plan, section } = removeSection(PLAN, 1);
    expect(section).toBe("# Two\n\n- b");
    expect(plan).toBe("# One\n\n- a\n\n# Three\n\n- c");
  });

  it("handles the first and last sections", () => {
    expect(removeSection(PLAN, 0).plan).toBe("# Two\n\n- b\n\n# Three\n\n- c");
    expect(removeSection(PLAN, 2).plan).toBe("# One\n\n- a\n\n# Two\n\n- b");
  });

  it("refuses a plan with no sections, and an index out of range", () => {
    expect(() => removeSection("- nothing\n", 0)).toThrow(NoSuchSection);
    expect(() => removeSection(PLAN, 9)).toThrow(NoSuchSection);
  });
});

describe("appendSection", () => {
  it("joins with a blank line, and starts clean when empty", () => {
    expect(appendSection("# A\n", "# B")).toBe("# A\n\n# B");
    expect(appendSection("", "# B")).toBe("# B");
  });
});
