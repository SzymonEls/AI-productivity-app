/**
 * The plan, rendered - ported from app/markdown_utils.py.
 *
 * The output has to match what the server produced, because the same CSS styles
 * it and the same JavaScript walks it looking for tags and checkboxes. Rather
 * than hope a JavaScript Markdown library happens to agree with python-markdown,
 * the renderer below is overridden to emit exactly what the Python did, and the
 * result is checked against captured output in markdown.test.ts.
 */

import { Marked } from "marked";

/**
 * The whole definition of a tag, and the third place it has been written.
 *
 * The JavaScript form differs from the Python one on purpose: \w in JavaScript
 * is ASCII-only and would cut "#dom-i-ogród" short, and a captured leading
 * character stands in for a lookbehind. Same rule either way - a tag starts
 * with a letter, and may not follow a word character, a # or an opening
 * bracket, which keeps "C#", "#2" and "(#x)" out.
 */
export const TAG_PATTERN = /(^|[^\p{L}\p{N}_#(])#(\p{L}[\p{L}\p{N}_-]*)/gu;

const LIST_ITEM_PATTERN = /^(\s*)(?:[-*+]\s|\d+\.\s)/;
const TOP_LEVEL_HEADING_PATTERN = /<h1(?<attrs>[^>]*)>[\s\S]*?<\/h1>/g;
const TAG_SPLIT_PATTERN = /(<[^>]+>)/;
const OPEN_LIST_ITEM_PATTERN = /^<li[\s>]/i;

const marked = new Marked({
  gfm: true,
  // nl2br: a single newline inside a paragraph is a line break, as it is in
  // the plan editor the person is typing into.
  breaks: true,
});

marked.use({
  renderer: {
    // marked emits its own checkbox for a task item. The markup below replaces
    // it wholesale, so this has to contribute nothing.
    checkbox() {
      return "";
    },

    // python-markdown writes XHTML-style void tags. Matching it exactly keeps
    // the output byte-for-byte what the server used to send.
    br() {
      return "<br />\n";
    },

    // python-markdown has no task lists; markdown_utils.py post-processes
    // "<li>[ ] text" into this exact markup. The trailing space after
    // "disabled" is not a typo - it is what the Python f-string produced.
    listitem(item) {
      // parse(), not parseInline(): a list item can contain a nested list, and
      // the inline parser has no rule for a block token. The second argument is
      // marked's "top" flag, which decides whether a tight item gets wrapped in
      // a paragraph; its type declaration omits it, hence the cast.
      const parse = this.parser.parse as (tokens: unknown[], top: boolean) => string;
      const text = parse.call(this.parser, item.tokens, !!item.loose);
      if (!item.task) return `<li>${text}</li>\n`;
      return (
        `<li class="task-list-item">` +
        `<input class="task-list-checkbox" type="checkbox" disabled ${item.checked ? "checked" : ""}> ` +
        `${text}</li>\n`
      );
    },
  },
});

/**
 * Re-indent two-space nested lists so they nest.
 *
 * Ported unchanged: the plan editor writes two spaces, python-markdown's
 * sane_lists wants four, and without this a nested list comes out flat.
 */
export function normalizeTwoSpaceNestedLists(value: string): string {
  const lines = value.split("\n");
  const out: string[] = [];
  let inListBlock = false;
  let twoSpaceBlock = false;

  for (let line of lines) {
    let match = LIST_ITEM_PATTERN.exec(line);
    let indent = match ? match[1].replace(/\t/g, "    ").length : null;

    if (match && (indent === 2 || (twoSpaceBlock && indent && indent > 0))) {
      twoSpaceBlock = true;
      line = " ".repeat(indent!) + line;
      match = LIST_ITEM_PATTERN.exec(line);
      indent = match![1].replace(/\t/g, "    ").length;
    }

    out.push(line);

    if (match) {
      inListBlock = true;
      if (indent === 2) twoSpaceBlock = true;
    } else if (!line.trim() && inListBlock) {
      continue;
    } else if (line.trim()) {
      inListBlock = false;
      twoSpaceBlock = false;
    }
  }

  return out.join("\n");
}

/**
 * Wrap the #tags inside list items, and only those.
 *
 * Walks tags and the text between them rather than running the pattern over the
 * whole document: a "#" in an attribute - href="#top" - is not a tag, and
 * neither is a heading.
 */
export function paintTags(html: string): string {
  if (!html.includes("#")) return html;

  const painted: string[] = [];
  let depth = 0;

  for (const part of html.split(TAG_SPLIT_PATTERN)) {
    if (part.startsWith("<")) {
      if (OPEN_LIST_ITEM_PATTERN.test(part)) depth += 1;
      else if (part.toLowerCase().startsWith("</li")) depth = Math.max(depth - 1, 0);
      painted.push(part);
    } else if (depth) {
      painted.push(
        part.replace(TAG_PATTERN, (_whole, lead: string, name: string) =>
          `${lead}<span class="plan-tag">#${name}</span>`
        )
      );
    } else {
      painted.push(part);
    }
  }
  return painted.join("");
}

export function renderMarkdown(value: string | null | undefined): string {
  if (!value) return "";
  const html = marked.parse(normalizeTwoSpaceNestedLists(value), { async: false }) as string;
  return paintTags(html);
}

/**
 * The plan as a stack of coloured section cards - render_project_markdown().
 *
 * Each top-level heading starts a card, and the tone cycles through six so a
 * long plan reads as steps rather than one wall.
 */
export function renderPlan(value: string | null | undefined): string {
  if (!value) return "";

  const html = renderMarkdown(value);
  const sections = [...html.matchAll(TOP_LEVEL_HEADING_PATTERN)];
  if (sections.length === 0) return html;

  const out: string[] = ['<div class="project-section-markdown">'];

  const preface = html.slice(0, sections[0].index).trim();
  if (preface) out.push(`<div class="project-section-preface">${preface}</div>`);

  sections.forEach((match, index) => {
    const start = match.index! + match[0].length;
    const end = index + 1 < sections.length ? sections[index + 1].index! : html.length;
    const body = html.slice(start, end).trim();
    const tone = (index % 6) + 1;

    out.push(`<section class="project-markdown-section project-markdown-section-tone-${tone}">`);
    out.push('<div class="project-markdown-step" aria-hidden="true"></div>');
    out.push('<div class="project-markdown-section-card">');
    out.push(match[0]);
    if (body) out.push(body);
    out.push("</div></section>");
  });

  out.push("</div>");
  return out.join("");
}

/** Drop a leading heading that just repeats the project title. */
export function stripRepeatedTitle(content: string, title: string): string {
  if (!content || !title) return content;

  const lines = content.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const stripped = lines[index].trim();
    if (!stripped) continue;
    if (
      stripped.startsWith("#") &&
      stripped.replace(/^#+/, "").trim().toLowerCase() === title.trim().toLowerCase()
    ) {
      return lines.slice(index + 1).join("\n").replace(/^\s+/, "");
    }
    return content;
  }
  return content;
}
