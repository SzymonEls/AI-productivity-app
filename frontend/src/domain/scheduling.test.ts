/**
 * The scheduling rules as slots.py states them, pinned as behaviour.
 *
 * The day-off cascade in particular is subtle enough that the Python file
 * spends a paragraph on it: a finished session does not move, and whatever
 * would land on it is held back too.
 */

import { describe, expect, it } from "vitest";

import { addDays, archivePaging, planAssign, planDayOff, planMove, slotCandidates } from "./slots";
import type { DaySlot, Project } from "../sync/types";

const TODAY = "2026-06-15";
const TOMORROW = addDays(TODAY, 1);

function project(uid: string, over: Partial<Project> = {}): Project {
  return {
    uid, rev: 1, updated_at: "2026-06-01T00:00:00Z",
    title: uid, short_goal: "", frequency: "daily",
    long_goal: "", archived_long_goal: "", daily_target_minutes: null,
    is_starred: false, is_private: false, is_archived: false,
    ...over,
  };
}

function slot(uid: string, day: string, name: "A" | "B" | "C", over: Partial<DaySlot> = {}): DaySlot {
  return {
    uid, rev: 1, updated_at: "2026-06-01T00:00:00Z",
    slot_date: day, slot: name, is_done: false, project_uid: "p1",
    ...over,
  };
}

describe("planAssign", () => {
  const projects = [project("p1", { title: "alpha" }), project("p2", { title: "beta" })];

  it("books a free slot", () => {
    const plan = planAssign(projects, [], "p1", TOMORROW, "A", TODAY);
    expect(plan.ok).toBe(true);
    expect(plan.create).toMatchObject({ slot_date: TOMORROW, slot: "A", project_uid: "p1" });
  });

  it("refuses a day that has gone", () => {
    const plan = planAssign(projects, [], "p1", addDays(TODAY, -1), "A", TODAY);
    expect(plan).toMatchObject({ ok: false, message: "That day is in the past." });
  });

  it("refuses an archived project", () => {
    const archived = [project("p3", { title: "old", is_archived: true })];
    expect(planAssign(archived, [], "p3", TOMORROW, "A", TODAY).ok).toBe(false);
  });

  it("names the project already holding the slot", () => {
    const booked = [slot("s1", TOMORROW, "A", { project_uid: "p1" })];
    const plan = planAssign(projects, booked, "p2", TOMORROW, "A", TODAY);
    expect(plan.ok).toBe(false);
    expect(plan.message).toContain("alpha");
  });

  it("allows one booking today and one in the future, but no more", () => {
    const booked = [slot("s1", TODAY, "A", { project_uid: "p1" })];
    // Today is taken, but the future is still open.
    expect(planAssign(projects, booked, "p1", TOMORROW, "B", TODAY).ok).toBe(true);

    const both = [...booked, slot("s2", TOMORROW, "B", { project_uid: "p1" })];
    const plan = planAssign(projects, both, "p1", addDays(TODAY, 2), "A", TODAY);
    expect(plan.ok).toBe(false);
    expect(plan.message).toContain("Already planned");
  });

  it("is happy when the booking already exists", () => {
    const booked = [slot("s1", TOMORROW, "A", { project_uid: "p1" })];
    expect(planAssign(projects, booked, "p1", TOMORROW, "A", TODAY)).toMatchObject({
      ok: true,
      message: "Already scheduled here.",
    });
  });
});

describe("planMove", () => {
  const projects = [project("p1", { title: "alpha" }), project("p2", { title: "beta" })];

  it("moves into a free slot", () => {
    const booked = [slot("s1", TOMORROW, "A", { project_uid: "p1" })];
    const plan = planMove(projects, booked, TOMORROW, "A", TOMORROW, "B", TODAY);
    expect(plan.ok).toBe(true);
    expect(plan.updates).toEqual([{ uid: "s1", changes: { slot_date: TOMORROW, slot: "B" } }]);
  });

  it("swaps with whatever is already there", () => {
    const booked = [
      slot("s1", TOMORROW, "A", { project_uid: "p1" }),
      slot("s2", TOMORROW, "B", { project_uid: "p2" }),
    ];
    const plan = planMove(projects, booked, TOMORROW, "A", TOMORROW, "B", TODAY);
    expect(plan.ok).toBe(true);
    expect(plan.message).toContain("Swapped with beta");
    expect(plan.updates).toHaveLength(2);
  });

  it("keeps done when the booking stays on its day", () => {
    const booked = [slot("s1", TOMORROW, "A", { is_done: true })];
    const plan = planMove(projects, booked, TOMORROW, "A", TOMORROW, "B", TODAY);
    expect(plan.updates![0].changes).not.toHaveProperty("is_done");
  });

  it("drops done when the booking changes day", () => {
    const booked = [slot("s1", TOMORROW, "A", { is_done: true })];
    const plan = planMove(projects, booked, TOMORROW, "A", addDays(TOMORROW, 1), "A", TODAY);
    expect(plan.updates![0].changes.is_done).toBe(false);
  });

  it("does not let a booking block itself", () => {
    const booked = [slot("s1", TOMORROW, "A", { project_uid: "p1" })];
    expect(planMove(projects, booked, TOMORROW, "A", addDays(TOMORROW, 3), "A", TODAY).ok).toBe(true);
  });
});

describe("planDayOff", () => {
  it("pushes everything from the day on one day later", () => {
    const booked = [
      slot("s1", TOMORROW, "A"),
      slot("s2", addDays(TOMORROW, 1), "A"),
    ];
    const plan = planDayOff(booked, TOMORROW, 1, TODAY);
    expect(plan.moved).toBe(2);
    expect(plan.updates).toEqual([
      { uid: "s2", changes: { slot_date: addDays(TOMORROW, 2) } },
      { uid: "s1", changes: { slot_date: addDays(TOMORROW, 1) } },
    ]);
  });

  it("walks newest first, so nothing lands on a spot not yet vacated", () => {
    const booked = [slot("s1", TOMORROW, "A"), slot("s2", addDays(TOMORROW, 1), "A")];
    const plan = planDayOff(booked, TOMORROW, 1, TODAY);
    expect(plan.updates!.map((u) => u.uid)).toEqual(["s2", "s1"]);
  });

  it("leaves a finished session where it happened", () => {
    const booked = [slot("s1", TOMORROW, "A", { is_done: true })];
    const plan = planDayOff(booked, TOMORROW, 1, TODAY);
    expect(plan.moved).toBe(0);
    expect(plan.message).toContain("finished session");
  });

  it("holds back a booking that would land on a finished one", () => {
    const booked = [
      slot("done", addDays(TOMORROW, 1), "A", { is_done: true }),
      slot("behind", TOMORROW, "A"),
    ];
    const plan = planDayOff(booked, TOMORROW, 1, TODAY);
    expect(plan.moved, "there is nowhere for it to land").toBe(0);
    expect(plan.updates).toEqual([]);
  });

  it("refuses a day that has gone", () => {
    expect(planDayOff([], addDays(TODAY, -1), 1, TODAY).ok).toBe(false);
  });
});

describe("slotCandidates", () => {
  it("lists blocked projects too, with the reason", () => {
    const projects = [project("p1", { title: "alpha" }), project("p2", { title: "beta" })];
    const booked = [slot("s1", addDays(TODAY, 2), "A", { project_uid: "p1" })];

    const candidates = slotCandidates(projects, booked, addDays(TODAY, 3), "B", TODAY);
    const alpha = candidates.find((c) => c.uid === "p1")!;

    expect(alpha.canTake).toBe(false);
    expect(alpha.reason).toContain("Already planned");
    expect(candidates.find((c) => c.uid === "p2")!.canTake).toBe(true);
  });

  it("puts the available ones first", () => {
    const projects = [project("p1", { title: "aaa" }), project("p2", { title: "zzz" })];
    const booked = [slot("s1", addDays(TODAY, 2), "A", { project_uid: "p1" })];
    const candidates = slotCandidates(projects, booked, addDays(TODAY, 3), "B", TODAY);
    expect(candidates[0].uid).toBe("p2");
  });

  it("says who holds a slot that is already taken", () => {
    const projects = [project("p1", { title: "alpha" })];
    const booked = [slot("s1", TOMORROW, "A", { project_uid: "p1" })];
    const candidates = slotCandidates(projects, booked, TOMORROW, "A", TODAY);
    expect(candidates[0].reason).toContain("taken by alpha");
  });
});

describe("archivePaging", () => {
  const YESTERDAY = addDays(TODAY, -1);

  it("steps back from the page's own edge, not a fixed three weeks from the cursor", () => {
    // A booking well before the window, so "Earlier" has somewhere to go.
    const old = [slot("s1", addDays(TODAY, -90), "A")];
    const paging = archivePaging(old, YESTERDAY, TODAY);

    expect(paging.earlierUntil).toBe(addDays(paging.firstDay, -1));
  });

  it("offers nothing older than the first booking there has ever been", () => {
    const recent = [slot("s1", addDays(TODAY, -2), "A")];
    expect(archivePaging(recent, YESTERDAY, TODAY).earlierUntil).toBeNull();
  });

  it("offers no Later on the newest page", () => {
    expect(archivePaging([], YESTERDAY, TODAY).laterUntil).toBeNull();
  });

  it("stops Later at yesterday rather than reaching into the schedule", () => {
    const older = addDays(TODAY, -30);
    const paging = archivePaging([], older, TODAY);
    expect(paging.laterUntil).not.toBeNull();
    expect(paging.laterUntil! <= YESTERDAY).toBe(true);
  });

  it("pages meet with no gap", () => {
    const long = [slot("s1", addDays(TODAY, -120), "A")];
    const first = archivePaging(long, YESTERDAY, TODAY);
    const second = archivePaging(long, first.earlierUntil!, TODAY);
    // The older page ends the day before the newer one begins.
    expect(addDays(second.lastDay, 1)).toBe(first.firstDay);
  });
});
