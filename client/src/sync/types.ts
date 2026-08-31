/**
 * The shape of what crosses the wire.
 *
 * Mirrors app/api/protocol.py. Two rules from that file matter here: references
 * are uids, never row ids, and values arrive raw - a date rather than "Tuesday",
 * an integer rather than "2 h 15 m" - because this side has to render them in
 * its own locale anyway.
 */

/** Columns every synchronised row carries. */
export interface SyncedRow {
  uid: string;
  rev: number;
  updated_at: string;
}

export interface Project extends SyncedRow {
  title: string;
  short_goal: string;
  frequency: string;
  long_goal: string;
  archived_long_goal: string;
  daily_target_minutes: number | null;
  is_starred: boolean;
  is_private: boolean;
  is_archived: boolean;
}

export interface TimelineGroup extends SyncedRow {
  name: string | null;
  position: number;
  is_backlog: boolean;
}

export interface TimelineItem extends SyncedRow {
  item_type: "project" | "note";
  title: string | null;
  body: string | null;
  is_private: boolean;
  position: number;
  group_uid: string | null;
  project_uid: string | null;
}

export interface DaySlot extends SyncedRow {
  slot_date: string;
  slot: "A" | "B" | "C";
  is_done: boolean;
  project_uid: string | null;
}

export interface TimeEntry extends SyncedRow {
  started_at: string;
  ended_at: string | null;
  description: string | null;
  project_title_snapshot: string | null;
  project_uid: string | null;
}

/** Entity names, in the order the server applies a push. */
export const ENTITIES = [
  "project",
  "timeline_group",
  "timeline_item",
  "day_slot",
  "time_entry",
] as const;

export type EntityName = (typeof ENTITIES)[number];

/** A row as it arrives. A tombstone carries nothing but the fact it is gone. */
export type IncomingRow = SyncedRow & { deleted: boolean } & Record<string, unknown>;

export interface ChangesResponse {
  ok: true;
  rev: number;
  changes: Record<EntityName, IncomingRow[]>;
}

export interface CursorTooOld {
  ok: false;
  reason: "cursor_too_old";
  tombstone_floor: number;
}

export interface Me {
  ok: true;
  csrf_token: string;
  user: { username: string; email: string };
  app_version: string;
  demo_mode: boolean;
  timezone: string;
  rev: number;
}
