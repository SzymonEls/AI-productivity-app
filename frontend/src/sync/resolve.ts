/**
 * Settling a conflict, once the person has said which version stands.
 *
 * Nothing here decides anything on its own - that is the whole point of the
 * design. Each function takes an answer and carries it out.
 */

import { storeFor, type ConflictEntry, type LocalDatabase } from "../db/schema";

/** Take the server's version and drop what was queued here. */
export async function keepServer(
  database: LocalDatabase,
  conflict: ConflictEntry
): Promise<void> {
  const store = storeFor(database, conflict.entity);

  await database.transaction("rw", store, database.outbox, database.conflicts, async () => {
    const queued = await database.outbox
      .where("[entity+uid]")
      .equals([conflict.entity, conflict.uid])
      .toArray();
    for (const entry of queued) await database.outbox.delete(entry.id!);

    if (conflict.server === null || conflict.server.deleted === true) {
      // It was deleted elsewhere and this device is agreeing to that.
      await store.delete(conflict.uid);
    } else {
      const { deleted: _deleted, ...row } = conflict.server;
      await store.put(row as never);
    }

    await database.conflicts.delete(conflict.id!);
  });
}

/**
 * Keep what was written here, on top of the version the server now holds.
 *
 * The queued change is re-aimed at the server's revision, so the next push is
 * an ordinary edit rather than the same argument again.
 */
export async function keepMine(
  database: LocalDatabase,
  conflict: ConflictEntry
): Promise<void> {
  const store = storeFor(database, conflict.entity);
  const serverRev = Number(conflict.server?.rev ?? 0);

  await database.transaction("rw", store, database.outbox, database.conflicts, async () => {
    const queued = await database.outbox
      .where("[entity+uid]")
      .equals([conflict.entity, conflict.uid])
      .toArray();

    for (const entry of queued) {
      await database.outbox.update(entry.id!, {
        base_rev: serverRev,
        // A row deleted on the server has to be created again to survive.
        op: conflict.reason === "gone" ? "create" : entry.op,
      });
    }

    const row = await store.get(conflict.uid);
    if (row !== undefined) await store.put({ ...row, rev: serverRev });

    await database.conflicts.delete(conflict.id!);
  });
}

/**
 * Keep both versions of a plan, the server's appended below.
 *
 * Only offered for long_goal: two versions of a Markdown plan are both work
 * somebody did, and picking one throws the other away. Two dates cannot be
 * merged like that, so nothing else offers it.
 */
export async function keepBoth(
  database: LocalDatabase,
  conflict: ConflictEntry
): Promise<void> {
  const mine = String(conflict.client?.fields ? (conflict.client.fields as Record<string, unknown>).long_goal ?? "" : "");
  const theirs = String(conflict.server?.long_goal ?? "");
  const merged = `${mine}\n\n# From the other device\n\n${theirs}`.trim();

  const store = storeFor(database, conflict.entity);
  const serverRev = Number(conflict.server?.rev ?? 0);

  await database.transaction("rw", store, database.outbox, database.conflicts, async () => {
    const queued = await database.outbox
      .where("[entity+uid]")
      .equals([conflict.entity, conflict.uid])
      .toArray();

    for (const entry of queued) {
      await database.outbox.update(entry.id!, {
        base_rev: serverRev,
        fields: { ...entry.fields, long_goal: merged },
      });
    }

    const row = await store.get(conflict.uid);
    if (row !== undefined) await store.put({ ...row, rev: serverRev, long_goal: merged } as never);

    await database.conflicts.delete(conflict.id!);
  });
}

/** Whether both versions can sensibly be kept. */
export function canKeepBoth(conflict: ConflictEntry): boolean {
  const fields = (conflict.client?.fields ?? {}) as Record<string, unknown>;
  return conflict.entity === "project" && "long_goal" in fields;
}

/** The fields that actually differ, for showing both sides. */
export function differences(conflict: ConflictEntry): { field: string; mine: unknown; theirs: unknown }[] {
  const fields = (conflict.client?.fields ?? {}) as Record<string, unknown>;
  return Object.entries(fields).map(([field, mine]) => ({
    field,
    mine,
    theirs: conflict.server?.[field],
  }));
}
