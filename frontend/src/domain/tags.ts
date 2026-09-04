/**
 * Tags, ported from _collect_tags in app/projects/routes.py.
 *
 * Nothing is stored as a tag: "#shop" is text inside a plan, so this reads
 * every active plan and groups what it finds. On the server that was a full
 * scan per request, which is why the tag page opened on a spinner; here the
 * plans are already on the device and the same work is instant.
 */

import type { Project } from "../sync/types";
import { TAG_PATTERN } from "./markdown";

/** The three list-item forms the plan editor writes. */
const PLAN_LIST_ITEM = /^\s*(?:[-*+]\s+(?:\[(?<done>[xX ])\]\s*)?|\d+\.\s+)(?<text>.*\S)\s*$/;

export interface TagItem {
  projectUid: string;
  projectTitle: string;
  isPrivate: boolean;
  text: string;
  isDone: boolean;
}

export interface Tag {
  name: string;
  count: number;
  items: TagItem[];
}

/** Every list item of a plan, with whether it is ticked off. */
export function planListItems(markdown: string): { text: string; isDone: boolean }[] {
  const items: { text: string; isDone: boolean }[] = [];

  for (const line of (markdown ?? "").split("\n")) {
    const match = PLAN_LIST_ITEM.exec(line);
    if (!match?.groups?.text) continue;
    items.push({
      text: match.groups.text,
      isDone: (match.groups.done ?? "").toLowerCase() === "x",
    });
  }
  return items;
}

function tagsIn(text: string): string[] {
  const found: string[] = [];
  for (const match of text.matchAll(TAG_PATTERN)) {
    found.push(match[2]);
  }
  return found;
}

/**
 * Group every tag across the active plans.
 *
 * The first spelling of a name wins, so "#Shop" and "#shop" are one tag shown
 * the way it was first written.
 */
export function collectTags(projects: Project[]): Tag[] {
  const byKey = new Map<string, Tag>();

  const active = [...projects]
    .filter((project) => !project.is_archived)
    .sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()));

  for (const project of active) {
    for (const item of planListItems(project.long_goal)) {
      for (const name of tagsIn(item.text)) {
        const key = name.toLowerCase();
        let tag = byKey.get(key);
        if (!tag) {
          tag = { name, count: 0, items: [] };
          byKey.set(key, tag);
        }
        tag.count += 1;
        tag.items.push({
          projectUid: project.uid,
          projectTitle: project.title,
          isPrivate: project.is_private,
          text: item.text,
          isDone: item.isDone,
        });
      }
    }
  }

  return [...byKey.values()].sort((a, b) =>
    a.name.toLowerCase().localeCompare(b.name.toLowerCase())
  );
}
