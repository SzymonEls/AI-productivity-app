/**
 * Bringing the local copy and the server back into agreement.
 *
 * Pull never merges silently. A row the server has moved on from, that this
 * device has also changed and not yet sent, is not something to resolve by
 * picking a winner - it goes to the conflicts store for the person to settle.
 * That is the rule the whole design turns on.
 */

import {
  CURSOR_KEY,
  LAST_SYNC_KEY,
  type LocalDatabase,
  readMeta,
  storeFor,
  writeMeta,
} from "../db/schema";
import { ENTITIES, type ChangesResponse, type EntityName, type IncomingRow } from "./types";

export interface PullResult {
  cursor: number;
  applied: number;
  removed: number;
  conflicts: number;
  /** True when the server could not send a difference and the set was refetched. */
  restarted: boolean;
}

class SyncError extends Error {}

async function fetchChanges(since: number): Promise<Response> {
  return fetch(`/api/sync/changes?since=${since}`, {
    headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
    credentials: "same-origin",
  });
}

/**
 * Fetch everything above the cursor and write it in.
 *
 * A 409 means the cursor sits below the server's tombstone floor: the deletions
 * needed to bring this copy up to date have already been cleared away, so a
 * difference would silently leave deleted rows behind. The answer is to take
 * the whole set and drop whatever is not in it.
 */
export async function pull(database: LocalDatabase): Promise<PullResult> {
  const cursor = await readMeta(database, CURSOR_KEY, 0);

  let response = await fetchChanges(cursor);
  let restarted = false;

  if (response.status === 409) {
    const body = await response.json();
    if (body?.reason !== "cursor_too_old") {
      throw new SyncError(body?.message ?? "The server refused the request.");
    }
    restarted = true;
    response = await fetchChanges(0);
  }

  if (response.status === 401) {
    throw new SyncError("Session expired. Please sign in again.");
  }
  if (!response.ok) {
    throw new SyncError(`The server answered ${response.status}.`);
  }

  const payload = (await response.json()) as ChangesResponse;
  return applyChanges(database, payload, restarted);
}

async function applyChanges(
  database: LocalDatabase,
  payload: ChangesResponse,
  restarted: boolean
): Promise<PullResult> {
  let applied = 0;
  let removed = 0;
  let conflicts = 0;

  // Anything this device has changed and not yet sent. Those uids are not the
  // server's to overwrite.
  const pending = new Set(
    (await database.outbox.toArray()).map((entry) => `${entry.entity}:${entry.uid}`)
  );

  for (const entity of ENTITIES) {
    const rows = payload.changes[entity] ?? [];
    const store = storeFor(database, entity);
    const seen = new Set<string>();

    for (const row of rows) {
      seen.add(row.uid);

      if (pending.has(`${entity}:${row.uid}`)) {
        conflicts += await recordConflict(database, entity, row);
        continue;
      }

      if (row.deleted) {
        // The local copy keeps no tombstones: the cursor already records that
        // this deletion has been seen, so the row can simply go.
        const existed = await store.get(row.uid);
        if (existed !== undefined) {
          await store.delete(row.uid);
          removed += 1;
        }
        continue;
      }

      const { deleted: _deleted, ...stored } = row;
      await store.put(stored as never);
      applied += 1;
    }

    // A restart is the only case where absence is meaningful: the server sent
    // its whole live set, so anything here that is not in it is gone.
    if (restarted) {
      const stale = await store
        .filter((local: { uid: string }) => !seen.has(local.uid))
        .toArray();
      for (const local of stale) {
        if (pending.has(`${entity}:${local.uid}`)) continue;
        await store.delete(local.uid);
        removed += 1;
      }
    }
  }

  await writeMeta(database, CURSOR_KEY, payload.rev);
  await writeMeta(database, LAST_SYNC_KEY, new Date().toISOString());

  return { cursor: payload.rev, applied, removed, conflicts, restarted };
}

/**
 * Record that both sides changed the same row.
 *
 * Nothing is decided here. The pending change stays in the outbox and the local
 * row stays as the person last left it, so the interface can show both versions
 * and ask.
 */
async function recordConflict(
  database: LocalDatabase,
  entity: EntityName,
  server: IncomingRow
): Promise<number> {
  const already = await database.conflicts
    .where("[entity+uid]")
    .equals([entity, server.uid])
    .first();
  if (already !== undefined) return 0;

  const mine = await database.outbox
    .where("[entity+uid]")
    .equals([entity, server.uid])
    .first();

  await database.conflicts.add({
    entity,
    uid: server.uid,
    reason: "stale",
    server: server as Record<string, unknown>,
    client: (mine?.fields ?? {}) as Record<string, unknown>,
    seen_at: new Date().toISOString(),
  });
  return 1;
}

/** The token the server set in a readable cookie; echoing it back proves origin. */
function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export interface PushResult {
  cursor: number;
  sent: number;
  applied: number;
  conflicts: number;
  /** Set when the whole push was refused, so nothing was queued away. */
  refused?: string;
}

/**
 * Send what is queued, and file whatever comes back as a question.
 *
 * An operation the server rejects stays in the outbox. That is deliberate: the
 * change is still the person's, still unsent, and dropping it because the
 * server disagreed would lose work without telling anyone.
 */
export async function push(database: LocalDatabase): Promise<PushResult> {
  const queued = await database.outbox.orderBy("changed_at").toArray();
  const cursor = await readMeta(database, CURSOR_KEY, 0);

  if (queued.length === 0) {
    return { cursor, sent: 0, applied: 0, conflicts: 0 };
  }

  const order = new Map(ENTITIES.map((entity, index) => [entity, index]));
  const ops = [...queued]
    .sort((a, b) => (order.get(a.entity) ?? 0) - (order.get(b.entity) ?? 0))
    .map((entry) => ({
      entity: entry.entity,
      uid: entry.uid,
      op: entry.op,
      base_rev: entry.base_rev,
      fields: entry.fields,
      client_ts: entry.changed_at,
    }));

  const response = await fetch("/api/sync/push", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
      "X-CSRF-Token": csrfToken(),
    },
    credentials: "same-origin",
    body: JSON.stringify({ since: cursor, ops }),
  });

  if (response.status === 401) throw new SyncError("Session expired. Please sign in again.");
  if (response.status === 403) {
    // Demo mode refuses writes, and so does a stale CSRF token. Neither is
    // worth discarding the queue over.
    const body = await response.json().catch(() => ({}));
    return { cursor, sent: ops.length, applied: 0, conflicts: 0, refused: body?.message };
  }
  if (!response.ok) throw new SyncError(`The server answered ${response.status}.`);

  const body = await response.json();
  const applied = new Set<string>(body.applied ?? []);

  for (const entry of queued) {
    if (applied.has(entry.uid)) await database.outbox.delete(entry.id!);
  }

  for (const conflict of body.conflicts ?? []) {
    const already = await database.conflicts
      .where("[entity+uid]")
      .equals([conflict.entity, conflict.uid])
      .first();
    if (already !== undefined) continue;

    await database.conflicts.add({
      entity: conflict.entity,
      uid: conflict.uid,
      reason: conflict.reason,
      server: conflict.server,
      client: conflict.client,
      seen_at: new Date().toISOString(),
    });
  }

  await writeMeta(database, CURSOR_KEY, body.rev);
  await writeMeta(database, LAST_SYNC_KEY, new Date().toISOString());

  return {
    cursor: body.rev,
    sent: ops.length,
    applied: applied.size,
    conflicts: (body.conflicts ?? []).length,
  };
}

/** Pull then push, which is the order that lets a conflict be spotted first. */
export async function synchronise(
  database: LocalDatabase
): Promise<{ pulled: PullResult; pushed: PushResult }> {
  const pulled = await pull(database);
  const pushed = await push(database);
  return { pulled, pushed };
}
