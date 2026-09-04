/**
 * The only way anything is written locally.
 *
 * Every change does two things at once: it updates the row the interface reads
 * from, and it appends the operation that will carry the change to the server.
 * Both happen in one IndexedDB transaction, because a tab closed between them
 * leaves a change that exists on this device and will never be sent - the kind
 * of loss nothing later can detect.
 */

import type { Table } from "dexie";

import { newUlid } from "../lib/ulid";
import type { EntityName, SyncedRow } from "../sync/types";
import { type LocalDatabase, type OutboxEntry, storeFor } from "./schema";

/** Rows carry these; a caller never sets them. */
type Managed = "uid" | "rev" | "updated_at";

function nowIso(): string {
  return new Date().toISOString();
}

/**
 * Fold a new operation into whatever is already queued for the same row.
 *
 * Ten edits to one plan are one thing to send and one line in the pending list,
 * not ten. The oldest base_rev is the one kept: it names the version the person
 * actually started from, which is what a conflict has to be measured against.
 */
async function enqueue(
  database: LocalDatabase,
  entry: Omit<OutboxEntry, "id" | "changed_at">
): Promise<void> {
  const existing = await database.outbox
    .where("[entity+uid]")
    .equals([entry.entity, entry.uid])
    .first();

  if (existing === undefined) {
    await database.outbox.add({ ...entry, changed_at: nowIso() });
    return;
  }

  // A row created here and then deleted here has never existed anywhere else.
  // Sending "create" followed by "delete" would be two round trips to reach the
  // state of having done nothing.
  if (existing.op === "create" && entry.op === "delete") {
    await database.outbox.delete(existing.id!);
    return;
  }

  await database.outbox.update(existing.id!, {
    // A create that is later edited is still a create.
    op: existing.op === "create" ? "create" : entry.op,
    fields: entry.op === "delete" ? {} : { ...existing.fields, ...entry.fields },
    changed_at: nowIso(),
  });
}

export async function createRow<T extends SyncedRow>(
  database: LocalDatabase,
  entity: EntityName,
  fields: Omit<T, Managed>
): Promise<string> {
  const uid = newUlid();
  const row = { ...fields, uid, rev: 0, updated_at: nowIso() } as unknown as T;
  const store = storeFor(database, entity) as Table<T, string>;

  await database.transaction("rw", store, database.outbox, async () => {
    await store.put(row);
    await enqueue(database, {
      entity,
      uid,
      op: "create",
      base_rev: null,
      fields: fields as Record<string, unknown>,
    });
  });

  return uid;
}

export async function updateRow<T extends SyncedRow>(
  database: LocalDatabase,
  entity: EntityName,
  uid: string,
  changes: Partial<Omit<T, Managed>>
): Promise<void> {
  const store = storeFor(database, entity) as Table<T, string>;

  await database.transaction("rw", store, database.outbox, async () => {
    const current = await store.get(uid);
    if (current === undefined) return;

    await store.put({ ...current, ...changes, updated_at: nowIso() });
    await enqueue(database, {
      entity,
      uid,
      op: "update",
      base_rev: current.rev,
      fields: changes as Record<string, unknown>,
    });
  });
}

export async function deleteRow(
  database: LocalDatabase,
  entity: EntityName,
  uid: string
): Promise<void> {
  const store = storeFor(database, entity);

  await database.transaction("rw", store, database.outbox, async () => {
    const current = await store.get(uid);
    if (current === undefined) return;

    await store.delete(uid);
    await enqueue(database, {
      entity,
      uid,
      op: "delete",
      base_rev: current.rev,
      fields: {},
    });
  });
}

export async function pendingCount(database: LocalDatabase): Promise<number> {
  return database.outbox.count();
}
