/**
 * Day slots, ported from app/projects/slots.py.
 *
 * The constants are copied, not reconsidered: the weights and thresholds in
 * the health score are a convention this application already settled on, and
 * changing them here would quietly change what the ring means.
 */

import type { DaySlot, Project } from "../sync/types";
import { today } from "./time";

export const SLOTS = ["A", "B", "C"] as const;
export type SlotName = (typeof SLOTS)[number];

/** Slot C has no time target, so the home page never shows a figure for it. */
export const TIMED_SLOTS = ["A", "B"] as const;

// The window ends yesterday. Today is still being worked on, and counting its
// bookings would open every morning with a drop the day then undoes.
export const HEALTH_WINDOW_DAYS = 7;
export const HEALTH_SESSIONS_WEIGHT = 0.6;
export const HEALTH_PLANNING_WEIGHT = 0.4;
export const HEALTH_GOOD_PERCENT = 75;
export const HEALTH_WARN_PERCENT = 50;

export function addDays(day: string, count: number): string {
  const moved = new Date(`${day}T00:00:00Z`);
  moved.setUTCDate(moved.getUTCDate() + count);
  return moved.toISOString().slice(0, 10);
}

export type SlotMap = Record<SlotName, DaySlot | null>;

/** {"A": …, "B": …, "C": …} for one day - slots_for_date(). */
export function slotsForDate(slots: DaySlot[], day: string): SlotMap {
  const filled: SlotMap = { A: null, B: null, C: null };
  for (const slot of slots) {
    if (slot.slot_date === day && slot.slot in filled) {
      filled[slot.slot as SlotName] = slot;
    }
  }
  return filled;
}

/**
 * Active projects with no slot after today - unscheduled_projects().
 *
 * Today is deliberately excluded: a project being worked on right now but with
 * nothing lined up afterwards still needs planning.
 */
export function unscheduledProjects(
  projects: Project[],
  slots: DaySlot[],
  day: string = today()
): Project[] {
  const planned = new Set(
    slots.filter((slot) => slot.slot_date > day).map((slot) => slot.project_uid)
  );

  return projects
    .filter((project) => !project.is_archived && !planned.has(project.uid))
    .sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()));
}

/** (booked, done) across an inclusive date range - session_counts_since(). */
export function sessionCounts(
  slots: DaySlot[],
  firstDay: string,
  lastDay: string
): { booked: number; done: number } {
  let booked = 0;
  let done = 0;
  for (const slot of slots) {
    if (slot.slot_date < firstDay || slot.slot_date > lastDay) continue;
    booked += 1;
    if (slot.is_done) done += 1;
  }
  return { booked, done };
}

export interface Health {
  percent: number;
  level: "good" | "warn" | "bad";
  windowDays: number;
  doneSessions: number;
  bookedSessions: number;
  plannedProjects: number;
  activeProjects: number;
  unplannedProjects: number;
}

/** One 0-100 figure for "is this system being used" - system_health(). */
export function systemHealth(
  projects: Project[],
  slots: DaySlot[],
  day: string = today()
): Health {
  const yesterday = addDays(day, -1);
  const { booked, done } = sessionCounts(
    slots,
    addDays(yesterday, -(HEALTH_WINDOW_DAYS - 1)),
    yesterday
  );

  // A week with nothing booked scores zero rather than full marks: there is no
  // completion rate to read off it, and an empty week is not a healthy one.
  const sessionsScore = booked ? done / booked : 0;

  const unplanned = unscheduledProjects(projects, slots, day);
  const active = projects.filter((project) => !project.is_archived).length;
  const planned = Math.max(active - unplanned.length, 0);
  // No projects at all is not a failure to plan them, so it scores full marks;
  // the sessions half already says the system is idle.
  const planningScore = active ? planned / active : 1;

  const percent = Math.round(
    (sessionsScore * HEALTH_SESSIONS_WEIGHT + planningScore * HEALTH_PLANNING_WEIGHT) * 100
  );

  const level = percent >= HEALTH_GOOD_PERCENT ? "good" : percent >= HEALTH_WARN_PERCENT ? "warn" : "bad";

  return {
    percent,
    level,
    windowDays: HEALTH_WINDOW_DAYS,
    doneSessions: done,
    bookedSessions: booked,
    plannedProjects: planned,
    activeProjects: active,
    unplannedProjects: unplanned.length,
  };
}
