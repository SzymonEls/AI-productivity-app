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

// ---------------------------------------------------------------------------
// Calendar windows and the two-block rule.
//
// Everything below is pure: it works out what should change and hands it back,
// leaving the caller to write it through db/mutate.ts. The server versions
// mutated a session directly, which is what made them impossible to test
// without a database.
// ---------------------------------------------------------------------------

export const SCHEDULE_WINDOW_DAYS = 14;
export const DAYS_PER_WEEK = 7;
export const SCHEDULE_WEEKS = 5;
export const ARCHIVE_WEEKS = 3;
export const MAX_CALENDAR_WEEKS = 12;

/** Monday is 0, matching Python's date.weekday(). */
export function weekday(day: string): number {
  return (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7;
}

export function formatDay(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });
}

export interface CalendarDay {
  date: string;
  slots: SlotMap;
}

/**
 * The schedule page: weeks of days, each with its three slots.
 *
 * Weeks run Monday to Sunday, but the first starts today rather than on its
 * Monday - a day that has passed cannot be booked, so there is nothing to show
 * there. Empty days are kept: the page is a strip of sheets to drop a project
 * onto, so an empty one is a target rather than something to leave out.
 */
export function calendarWeeks(
  slots: DaySlot[],
  weeks: number = SCHEDULE_WEEKS,
  startDay: string = today()
): CalendarDay[][] {
  const firstWeekDays = DAYS_PER_WEEK - weekday(startDay);
  const calendar: CalendarDay[][] = [];
  let day = startDay;

  for (let index = 0; index < weeks; index += 1) {
    const length = index === 0 ? firstWeekDays : DAYS_PER_WEEK;
    const week: CalendarDay[] = [];
    for (let offset = 0; offset < length; offset += 1) {
      const date = addDays(day, offset);
      week.push({ date, slots: slotsForDate(slots, date) });
    }
    calendar.push(week);
    day = addDays(day, length);
  }
  return calendar;
}

/**
 * The archive: weeks up to and including endDay, newest week first.
 *
 * The mirror of calendarWeeks(). There the short week is the first because it
 * starts today; here it is the newest, because it ends on endDay.
 */
export function pastCalendarWeeks(
  slots: DaySlot[],
  weeks: number = ARCHIVE_WEEKS,
  endDay: string = addDays(today(), -1)
): CalendarDay[][] {
  const newestWeekDays = weekday(endDay) + 1;
  const calendar: CalendarDay[][] = [];
  let lastDay = endDay;

  for (let index = 0; index < weeks; index += 1) {
    const length = index === 0 ? newestWeekDays : DAYS_PER_WEEK;
    const monday = addDays(lastDay, -(length - 1));
    const week: CalendarDay[] = [];
    for (let offset = 0; offset < length; offset += 1) {
      const date = addDays(monday, offset);
      week.push({ date, slots: slotsForDate(slots, date) });
    }
    calendar.push(week);
    lastDay = addDays(monday, -1);
  }
  return calendar;
}

export function lastBookedDay(slots: DaySlot[]): string | null {
  return slots.reduce<string | null>(
    (latest, slot) => (latest === null || slot.slot_date > latest ? slot.slot_date : latest),
    null
  );
}

export function firstBookedDay(slots: DaySlot[]): string | null {
  return slots.reduce<string | null>(
    (earliest, slot) => (earliest === null || slot.slot_date < earliest ? slot.slot_date : earliest),
    null
  );
}

/**
 * How many weeks the schedule has to show to reach the furthest booking.
 *
 * A day off pushes bookings past the page's edge; the window grows to keep the
 * last one in view rather than hiding it.
 */
export function weeksToCover(
  slots: DaySlot[],
  startDay: string = today(),
  minimum: number = SCHEDULE_WEEKS,
  maximum: number = MAX_CALENDAR_WEEKS
): number {
  const last = lastBookedDay(slots);
  if (last === null || last <= startDay) return minimum;

  const firstWeekDays = DAYS_PER_WEEK - weekday(startDay);
  const daysNeeded =
    Math.round(
      (new Date(`${last}T00:00:00Z`).getTime() - new Date(`${startDay}T00:00:00Z`).getTime()) /
        86400000
    ) + 1;

  const weeks =
    daysNeeded <= firstWeekDays
      ? 1
      : 1 + Math.ceil((daysNeeded - firstWeekDays) / DAYS_PER_WEEK);

  return Math.max(minimum, Math.min(weeks, maximum));
}

export type BookingPair = [DaySlot | null, DaySlot | null];

/** A project's slots from today on, as (today, future) - project_bookings(). */
export function projectBookings(
  slots: DaySlot[],
  projectUid: string,
  day: string = today(),
  ignore: ReadonlySet<string> = new Set()
): BookingPair {
  const mine = slots
    .filter(
      (slot) =>
        slot.project_uid === projectUid && slot.slot_date >= day && !ignore.has(slot.uid)
    )
    .sort((a, b) => a.slot_date.localeCompare(b.slot_date));

  return [
    mine.find((slot) => slot.slot_date === day) ?? null,
    mine.find((slot) => slot.slot_date > day) ?? null,
  ];
}

/** The bulk form, so the picker does not ask once per project. */
export function bookingsByProject(
  slots: DaySlot[],
  day: string = today()
): Map<string, BookingPair> {
  const byProject = new Map<string, BookingPair>();

  for (const slot of [...slots]
    .filter((slot) => slot.slot_date >= day && slot.project_uid)
    .sort((a, b) => a.slot_date.localeCompare(b.slot_date))) {
    const key = slot.project_uid!;
    const [todaySlot, futureSlot] = byProject.get(key) ?? [null, null];
    if (slot.slot_date === day) {
      byProject.set(key, [todaySlot ?? slot, futureSlot]);
    } else if (futureSlot === null) {
      byProject.set(key, [todaySlot, slot]);
    }
  }
  return byProject;
}

/**
 * Which of a project's two bookings stands in the way on a day.
 *
 * A project gets at most two: one today and one in the future. The rule lives
 * here alone, so the single-project and bulk paths cannot drift apart.
 */
export function blockerForDay(
  bookings: BookingPair,
  day: string,
  todayDay: string = today()
): DaySlot | null {
  const [todaySlot, futureSlot] = bookings;
  return day === todayDay ? todaySlot : futureSlot;
}

export function blockedReason(
  blocker: DaySlot | null,
  day: string,
  todayDay: string
): string {
  if (blocker === null) return "";
  if (day === todayDay) return `Already in today's slot ${blocker.slot}.`;
  return `Already planned for ${formatDay(blocker.slot_date)} in slot ${blocker.slot}.`;
}
