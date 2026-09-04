/**
 * The scheduling rules, as app/projects/slots.py states them in its own
 * comments. Each test names the rule it pins rather than the code path.
 */

import { describe, expect, it } from "vitest";

import { addDays, slotsForDate, sessionCounts, systemHealth, unscheduledProjects } from "./slots";
import type { DaySlot, Project } from "../sync/types";

const TODAY = "2026-06-15";

function project(uid: string, over: Partial<Project> = {}): Project {
  return {
    uid,
    rev: 1,
    updated_at: "2026-06-01T00:00:00Z",
    title: uid,
    short_goal: "",
    frequency: "daily",
    long_goal: "",
    archived_long_goal: "",
    daily_target_minutes: null,
    is_starred: false,
    is_private: false,
    is_archived: false,
    ...over,
  };
}

function slot(uid: string, day: string, name: "A" | "B" | "C", over: Partial<DaySlot> = {}): DaySlot {
  return {
    uid,
    rev: 1,
    updated_at: "2026-06-01T00:00:00Z",
    slot_date: day,
    slot: name,
    is_done: false,
    project_uid: "p1",
    ...over,
  };
}

describe("slotsForDate", () => {
  it("returns all three slots, empty ones included", () => {
    const filled = slotsForDate([slot("s1", TODAY, "B")], TODAY);
    expect(filled.A).toBeNull();
    expect(filled.B?.uid).toBe("s1");
    expect(filled.C).toBeNull();
  });

  it("ignores other days", () => {
    expect(slotsForDate([slot("s1", "2026-06-14", "A")], TODAY).A).toBeNull();
  });
});

describe("unscheduledProjects", () => {
  it("excludes today, because a project with nothing after today still needs planning", () => {
    const booked = [slot("s1", TODAY, "A", { project_uid: "p1" })];
    const listed = unscheduledProjects([project("p1")], booked, TODAY).map((p) => p.uid);
    expect(listed).toEqual(["p1"]);
  });

  it("counts a booking after today as planned", () => {
    const booked = [slot("s1", addDays(TODAY, 1), "A", { project_uid: "p1" })];
    expect(unscheduledProjects([project("p1")], booked, TODAY)).toEqual([]);
  });

  it("leaves archived projects out and sorts by title, case-insensitively", () => {
    const projects = [
      project("p1", { title: "zebra" }),
      project("p2", { title: "Apple" }),
      project("p3", { title: "gone", is_archived: true }),
    ];
    expect(unscheduledProjects(projects, [], TODAY).map((p) => p.title)).toEqual([
      "Apple",
      "zebra",
    ]);
  });
});

describe("sessionCounts", () => {
  it("counts booked and done across an inclusive range", () => {
    const booked = [
      slot("s1", "2026-06-10", "A", { is_done: true }),
      slot("s2", "2026-06-12", "A"),
      slot("s3", "2026-06-20", "A", { is_done: true }),
    ];
    expect(sessionCounts(booked, "2026-06-10", "2026-06-12")).toEqual({ booked: 2, done: 1 });
  });
});

describe("systemHealth", () => {
  it("scores an empty week zero on the sessions half, not full marks", () => {
    const health = systemHealth([project("p1")], [], TODAY);
    // No sessions (0 of 0.6) and one unplanned project (0 of 0.4).
    expect(health.percent).toBe(0);
    expect(health.level).toBe("bad");
  });

  it("gives full marks for planning when there are no projects at all", () => {
    const health = systemHealth([], [], TODAY);
    expect(health.percent).toBe(40); // the planning half only
  });

  it("leaves today out of the window", () => {
    const todaysBooking = [slot("s1", TODAY, "A", { is_done: false })];
    const health = systemHealth([], todaysBooking, TODAY);
    expect(health.bookedSessions, "today is still being worked on").toBe(0);
  });

  it("counts the seven days ending yesterday", () => {
    const inside = slot("in", addDays(TODAY, -7), "A", { is_done: true });
    const outside = slot("out", addDays(TODAY, -8), "A", { is_done: true });
    const health = systemHealth([], [inside, outside], TODAY);
    expect(health.bookedSessions).toBe(1);
    expect(health.doneSessions).toBe(1);
  });

  it("reaches 100 when every session was done and everything is planned", () => {
    const projects = [project("p1")];
    const booked = [
      slot("s1", addDays(TODAY, -1), "A", { is_done: true, project_uid: "p1" }),
      slot("s2", addDays(TODAY, 1), "A", { project_uid: "p1" }),
    ];
    const health = systemHealth(projects, booked, TODAY);
    expect(health.percent).toBe(100);
    expect(health.level).toBe("good");
  });

  it("bands at 75 and 50", () => {
    // Half the sessions done, everything planned: 0.5*60 + 40 = 70 -> warn.
    const projects = [project("p1")];
    const booked = [
      slot("s1", addDays(TODAY, -1), "A", { is_done: true, project_uid: "p1" }),
      slot("s2", addDays(TODAY, -2), "B", { is_done: false, project_uid: "p1" }),
      slot("s3", addDays(TODAY, 1), "A", { project_uid: "p1" }),
    ];
    const health = systemHealth(projects, booked, TODAY);
    expect(health.percent).toBe(70);
    expect(health.level).toBe("warn");
  });
});
