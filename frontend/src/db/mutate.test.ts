/** The write path: a change must reach the outbox, or it never leaves. */

import { beforeEach, describe, expect, it } from "vitest";

import { LocalDatabase } from "./schema";
import { createRow, deleteRow, pendingCount, updateRow } from "./mutate";
import type { Project } from "../sync/types";

let database: LocalDatabase;
let counter = 0;

beforeEach(async () => {
  counter += 1;
  database = new LocalDatabase(`test-${counter}`);
  await database.open();
});

const project = {
  title: "A project",
  short_goal: "goal",
  frequency: "daily",
  long_goal: "# Plan",
  archived_long_goal: "",
  daily_target_minutes: null,
  is_starred: false,
  is_private: false,
  is_archived: false,
} satisfies Omit<Project, "uid" | "rev" | "updated_at">;

describe("createRow", () => {
  it("stores the row and queues it in one go", async () => {
    const uid = await createRow<Project>(database, "project", project);

    const stored = await database.projects.get(uid);
    expect(stored?.title).toBe("A project");
    expect(uid).toHaveLength(26);

    const queued = await database.outbox.toArray();
    expect(queued).toHaveLength(1);
    expect(queued[0]).toMatchObject({ entity: "project", uid, op: "create", base_rev: null });
  });
});

describe("updateRow", () => {
  it("folds repeated edits into one pending change", async () => {
    const uid = await createRow<Project>(database, "project", project);
    await database.outbox.clear();
    await database.projects.update(uid, { rev: 7 });

    await updateRow<Project>(database, "project", uid, { title: "First" });
    await updateRow<Project>(database, "project", uid, { title: "Second" });
    await updateRow<Project>(database, "project", uid, { short_goal: "changed" });

    const queued = await database.outbox.toArray();
    expect(queued, "three edits to one row are one thing to send").toHaveLength(1);
    expect(queued[0].fields).toEqual({ title: "Second", short_goal: "changed" });
  });

  it("keeps the oldest base revision, which is the version the person started from", async () => {
    const uid = await createRow<Project>(database, "project", project);
    await database.outbox.clear();
    await database.projects.update(uid, { rev: 4 });

    await updateRow<Project>(database, "project", uid, { title: "First" });
    await database.projects.update(uid, { rev: 9 });
    await updateRow<Project>(database, "project", uid, { title: "Second" });

    const queued = await database.outbox.toArray();
    expect(queued[0].base_rev).toBe(4);
  });

  it("leaves a row it does not know alone", async () => {
    await updateRow<Project>(database, "project", "nosuchuid", { title: "x" });
    expect(await pendingCount(database)).toBe(0);
  });
});

describe("deleteRow", () => {
  it("removes the row and queues the deletion", async () => {
    const uid = await createRow<Project>(database, "project", project);
    await database.outbox.clear();
    await database.projects.update(uid, { rev: 3 });

    await deleteRow(database, "project", uid);

    expect(await database.projects.get(uid)).toBeUndefined();
    const queued = await database.outbox.toArray();
    expect(queued[0]).toMatchObject({ op: "delete", base_rev: 3 });
  });

  it("cancels out a row that was created and deleted before any sync", async () => {
    const uid = await createRow<Project>(database, "project", project);
    await deleteRow(database, "project", uid);

    expect(await database.projects.get(uid)).toBeUndefined();
    expect(
      await pendingCount(database),
      "the server never heard of it, so there is nothing to tell it"
    ).toBe(0);
  });

  it("keeps an edit-then-delete as a delete", async () => {
    const uid = await createRow<Project>(database, "project", project);
    await database.outbox.clear();
    await database.projects.update(uid, { rev: 2 });

    await updateRow<Project>(database, "project", uid, { title: "renamed" });
    await deleteRow(database, "project", uid);

    const queued = await database.outbox.toArray();
    expect(queued).toHaveLength(1);
    expect(queued[0].op).toBe("delete");
    expect(queued[0].fields).toEqual({});
  });
});
