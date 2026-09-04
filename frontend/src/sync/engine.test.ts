/**
 * Push, against a stubbed server.
 *
 * The case that matters here was found by using the application: create a row,
 * send it, then edit it. Without recording the revision the server assigned,
 * the edit is sent against the revision the row was created with and comes back
 * as a conflict that nobody else caused.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { createRow, updateRow } from "../db/mutate";
import { LocalDatabase } from "../db/schema";
import { push } from "./engine";
import type { TimeEntry } from "./types";

let database: LocalDatabase;
let counter = 0;

const entry = {
  started_at: "2026-06-15T09:00:00Z",
  ended_at: null,
  description: null,
  project_title_snapshot: "A project",
  project_uid: "p1",
} satisfies Omit<TimeEntry, "uid" | "rev" | "updated_at">;

/** A server that accepts everything and numbers it. */
function serverAccepting(rev: number) {
  return vi.fn(async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body));
    return {
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        rev,
        applied: body.ops.map((op: { uid: string }) => op.uid),
        conflicts: [],
      }),
    } as unknown as Response;
  });
}

beforeEach(async () => {
  counter += 1;
  database = new LocalDatabase(`engine-${counter}`);
  await database.open();
  vi.stubGlobal("document", { cookie: "csrf_token=t" });
});

describe("push", () => {
  it("empties the outbox for everything the server accepted", async () => {
    vi.stubGlobal("fetch", serverAccepting(7));
    await createRow<TimeEntry>(database, "time_entry", entry);

    const result = await push(database);

    expect(result.applied).toBe(1);
    expect(await database.outbox.count()).toBe(0);
  });

  it("records the revision the server assigned", async () => {
    vi.stubGlobal("fetch", serverAccepting(7));
    const uid = await createRow<TimeEntry>(database, "time_entry", entry);

    await push(database);

    expect((await database.timeEntries.get(uid))!.rev).toBe(7);
  });

  it("sends a later edit against that revision, not the one it was created with", async () => {
    vi.stubGlobal("fetch", serverAccepting(7));
    const uid = await createRow<TimeEntry>(database, "time_entry", entry);
    await push(database);

    await updateRow<TimeEntry>(database, "time_entry", uid, {
      ended_at: "2026-06-15T09:30:00Z",
    });

    const queued = await database.outbox.toArray();
    expect(queued[0].base_rev, "stale here is a conflict nobody caused").toBe(7);
  });

  it("keeps a rejected change queued", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          rev: 9,
          applied: [],
          conflicts: [{ entity: "time_entry", uid: "x", reason: "stale", server: {}, client: {} }],
        }),
      }) as unknown as Response)
    );
    await createRow<TimeEntry>(database, "time_entry", entry);

    const result = await push(database);

    expect(result.conflicts).toBe(1);
    expect(await database.outbox.count(), "the change is still the person's").toBe(1);
    expect(await database.conflicts.count()).toBe(1);
  });

  it("does not discard the queue when the server refuses the write", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 403,
        json: async () => ({ ok: false, message: "This demo is read-only." }),
      }) as unknown as Response)
    );
    await createRow<TimeEntry>(database, "time_entry", entry);

    const result = await push(database);

    expect(result.refused).toBe("This demo is read-only.");
    expect(await database.outbox.count()).toBe(1);
  });
});
