/**
 * The local copy. Every read the interface makes comes from here, never from
 * the network, which is what lets the whole application work with the cable
 * pulled out.
 *
 * Keyed by uid throughout: the server's integer ids never reach this side, and
 * a row created here while offline has to be able to name itself before any
 * server has seen it.
 */

import Dexie, { type Table } from "dexie";

import type {
  DaySlot,
  EntityName,
  Project,
  TimeEntry,
  TimelineGroup,
  TimelineItem,
} from "../sync/types";

/** One change waiting to be sent. */
export interface OutboxEntry {
  id?: number;
  entity: EntityName;
  uid: string;
  op: "create" | "update" | "delete";
  /** The revision this change was written on top of - how a conflict is spotted. */
  base_rev: number | null;
  fields: Record<string, unknown>;
  /** When it happened here, for the human-readable pending list. */
  changed_at: string;
}

/** A conflict the server sent back, waiting for the person to settle it. */
export interface ConflictEntry {
  id?: number;
  entity: EntityName;
  uid: string;
  reason: "stale" | "slot_taken" | "gone" | "already_exists" | "missing_uid";
  server: Record<string, unknown> | null;
  client: Record<string, unknown>;
  seen_at: string;
}

export interface MetaRow {
  key: string;
  value: unknown;
}

export class LocalDatabase extends Dexie {
  projects!: Table<Project, string>;
  timelineGroups!: Table<TimelineGroup, string>;
  timelineItems!: Table<TimelineItem, string>;
  daySlots!: Table<DaySlot, string>;
  timeEntries!: Table<TimeEntry, string>;
  outbox!: Table<OutboxEntry, number>;
  conflicts!: Table<ConflictEntry, number>;
  meta!: Table<MetaRow, string>;

  constructor(name: string) {
    super(name);

    // Booleans are deliberately not indexed: IndexedDB cannot use them as keys,
    // and the collections here are small enough to filter in memory.
    this.version(1).stores({
      projects: "uid, rev",
      timelineGroups: "uid, rev, position",
      timelineItems: "uid, rev, group_uid, project_uid, position",
      daySlots: "uid, rev, slot_date, project_uid, [slot_date+slot]",
      timeEntries: "uid, rev, started_at, project_uid",
      outbox: "++id, [entity+uid], changed_at",
      conflicts: "++id, [entity+uid]",
      meta: "key",
    });
  }
}

/** Which store holds which entity - the one place the mapping lives. */
export function storeFor(database: LocalDatabase, entity: EntityName): Table<any, string> {
  switch (entity) {
    case "project":
      return database.projects;
    case "timeline_group":
      return database.timelineGroups;
    case "timeline_item":
      return database.timelineItems;
    case "day_slot":
      return database.daySlots;
    case "time_entry":
      return database.timeEntries;
  }
}

/** One database per account, so signing in as someone else cannot mix the two. */
export function openDatabase(accountKey: string): LocalDatabase {
  return new LocalDatabase(`productivity:${accountKey}`);
}

export const CURSOR_KEY = "cursor";
export const LAST_SYNC_KEY = "last_sync";

export async function readMeta<T>(
  database: LocalDatabase,
  key: string,
  fallback: T
): Promise<T> {
  const row = await database.meta.get(key);
  return row === undefined ? fallback : (row.value as T);
}

export async function writeMeta(
  database: LocalDatabase,
  key: string,
  value: unknown
): Promise<void> {
  await database.meta.put({ key, value });
}
