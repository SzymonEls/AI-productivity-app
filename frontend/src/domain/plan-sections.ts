/**
 * Moving a finished section out of a plan and back.
 *
 * Ported from app/projects/routes.py. There is no table behind this: the
 * "archive" is text cut out of long_goal and appended to archived_long_goal,
 * sliced by character offset - which is why the offsets are worked out from the
 * raw source rather than from anything rendered.
 */

export interface SectionRange {
  start: number;
  end: number;
  title: string;
}

/** Where each top-level "# " section begins and ends in the source. */
export function sectionRanges(markdown: string): SectionRange[] {
  const source = markdown ?? "";
  const lines = source.split(/(?<=\n)/);

  const headings: { offset: number; title: string }[] = [];
  let offset = 0;
  for (const line of lines) {
    const title = line.trim().slice(2).trim();
    if (line.startsWith("# ") && title) headings.push({ offset, title });
    offset += line.length;
  }

  return headings.map((heading, index) => ({
    start: heading.offset,
    end: index + 1 < headings.length ? headings[index + 1].offset : source.length,
    title: heading.title,
  }));
}

export class NoSuchSection extends Error {}

/** Cut one section out. Returns the plan left behind and the piece removed. */
export function removeSection(
  markdown: string,
  index: number
): { plan: string; section: string } {
  const source = markdown ?? "";
  const ranges = sectionRanges(source);

  if (ranges.length === 0) throw new NoSuchSection("This plan has no section # to archive.");
  if (index < 0 || index >= ranges.length) throw new NoSuchSection("The selected section was not found.");

  const { start, end } = ranges[index];
  return {
    section: source.slice(start, end).trim(),
    plan: `${source.slice(0, start).replace(/\s+$/, "")}\n\n${source.slice(end).replace(/^\s+/, "")}`.trim(),
  };
}

export function appendSection(markdown: string, section: string): string {
  const current = (markdown ?? "").trim();
  const piece = (section ?? "").trim();
  if (!current) return piece;
  return `${current}\n\n${piece}`;
}
