/**
 * The Markdown port, against output captured from python-markdown.
 *
 * Compared with whitespace between tags collapsed: the two libraries differ on
 * where they put newlines, which no reader or stylesheet can tell apart. Text
 * inside a tag is compared as-is, because that is what a person reads.
 */

import { describe, expect, it } from "vitest";

import golden from "./__golden__markdown.json";
import {
  markdownFilename,
  normalizeTwoSpaceNestedLists,
  paintTags,
  projectMarkdown,
  renderMarkdown,
  renderPlan,
  stripRepeatedTitle,
} from "./markdown";

/** Collapse the whitespace that only separates tags. */
function shape(html: string): string {
  return html.replace(/>\s+</g, "><").replace(/\s+/g, " ").trim();
}

const cases = Object.entries(golden).filter(([name]) => !name.startsWith("_")) as [
  string,
  { source: string; inline: string; project: string },
][];

describe("renderMarkdown", () => {
  for (const [name, expected] of cases) {
    it(`matches python-markdown for ${name}`, () => {
      expect(shape(renderMarkdown(expected.source))).toBe(shape(expected.inline));
    });
  }
});

describe("renderPlan", () => {
  for (const [name, expected] of cases) {
    it(`matches render_project_markdown for ${name}`, () => {
      expect(shape(renderPlan(expected.source))).toBe(shape(expected.project));
    });
  }
});

describe("paintTags", () => {
  it("leaves a tag outside a list item alone", () => {
    expect(paintTags("<h1>Not a #tag</h1>")).toBe("<h1>Not a #tag</h1>");
  });

  it("leaves a link anchor alone", () => {
    const html = '<li><a href="#top">top</a> and #real</li>';
    const painted = paintTags(html);
    expect(painted).toContain('href="#top"');
    expect(painted).toContain('<span class="plan-tag">#real</span>');
  });

  it("keeps non-ASCII letters in a tag", () => {
    expect(paintTags("<li>#dom-i-ogród</li>")).toBe(
      '<li><span class="plan-tag">#dom-i-ogród</span></li>'
    );
  });

  it("refuses what the rule excludes", () => {
    const painted = paintTags("<li>C# and #2 and (#x)</li>");
    expect(painted).toBe("<li>C# and #2 and (#x)</li>");
  });
});

describe("normalizeTwoSpaceNestedLists", () => {
  it("matches the Python output", () => {
    expect(normalizeTwoSpaceNestedLists("- outer\n  - inner\n    - deeper\n")).toBe(
      (golden as any)._normalize.two_space
    );
  });
});

describe("stripRepeatedTitle", () => {
  it("matches the Python output", () => {
    const g = (golden as any)._strip_title;
    expect(stripRepeatedTitle("# My Project\n\nbody here", "My Project")).toBe(g.matching);
    expect(stripRepeatedTitle("# Other\n\nbody", "My Project")).toBe(g.different);
    expect(stripRepeatedTitle("just text", "My Project")).toBe(g.no_heading);
  });
});

describe("projectMarkdown", () => {
  const full = {
    title: "Dom i ogród",
    short_goal: "Keep it liveable.",
    frequency: "Weekends",
    daily_target_minutes: 90,
    long_goal: "# Kitchen\n\n- paint",
  };

  it("carries the name and every card, in the order of the page", () => {
    expect(projectMarkdown(full)).toBe(
      "# Dom i ogród\n\n" +
        "## Thoughts\n\nKeep it liveable.\n\n" +
        "## Frequency\n\nWeekends\n\n" +
        "## Daily target\n\n1h 30m\n\n" +
        "## Plan\n\n# Kitchen\n\n- paint\n"
    );
  });

  it("leaves out a card that has nothing in it", () => {
    expect(
      projectMarkdown({ ...full, short_goal: "  ", frequency: "", daily_target_minutes: null })
    ).toBe("# Dom i ogród\n\n## Plan\n\n# Kitchen\n\n- paint\n");
  });

  it("still names the file when the project has no title", () => {
    expect(projectMarkdown({ ...full, title: " " }).startsWith("# Project\n")).toBe(true);
  });
});

describe("markdownFilename", () => {
  it("folds accents and punctuation into a slug", () => {
    expect(markdownFilename("Dom i ogród")).toBe("dom-i-ogrod.md");
    expect(markdownFilename("  Plan: 2026 / Q1  ")).toBe("plan-2026-q1.md");
  });

  it("falls back when nothing survives", () => {
    expect(markdownFilename("!!!")).toBe("project.md");
  });
});
