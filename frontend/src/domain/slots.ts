/**
 * Day slots, ported from app/projects/slots.py.
 *
 * The constants are copied, not reconsidered: the weights and thresholds in
 * the health score are a convention this application already settled on, and
 * changing them here would quietly change what the ring means.
 */

import type { DaySlot, Project } from "../sync/types";
import { addDays, firstPlanSectionTitle, lastSessionLabel, today } from "./time";

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

// Calendar arithmetic lives with the rest of it in time.ts; the schedule reads
// dates through this module, so it goes back out from here.
export { addDays };

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

// ---------------------------------------------------------------------------
// The operations, as plans rather than writes.
//
// Each returns what should change and why it may not. The caller writes it
// through db/mutate.ts, so the rules can be tested without a database and the
// same answer serves an optimistic redraw and the queued change.
// ---------------------------------------------------------------------------

export interface Change {
  uid: string;
  changes: Partial<DaySlot>;
}

export interface Plan {
  ok: boolean;
  message: string;
  create?: Omit<DaySlot, "uid" | "rev" | "updated_at">;
  updates?: Change[];
  removals?: string[];
}

/** Book a project into a slot - assign_slot(). */
export function planAssign(
  projects: Project[],
  slots: DaySlot[],
  projectUid: string,
  day: string,
  slot: string,
  todayDay: string = today()
): Plan {
  if (!(SLOTS as readonly string[]).includes(slot)) return { ok: false, message: "Unknown slot." };
  if (day < todayDay) return { ok: false, message: "That day is in the past." };

  const project = projects.find((candidate) => candidate.uid === projectUid);
  if (!project) return { ok: false, message: "Project not found." };
  if (project.is_archived) return { ok: false, message: "Archived projects cannot be scheduled." };

  const taken = slots.find((entry) => entry.slot_date === day && entry.slot === slot);
  if (taken) {
    if (taken.project_uid === projectUid) return { ok: true, message: "Already scheduled here." };
    const other = projects.find((candidate) => candidate.uid === taken.project_uid);
    return { ok: false, message: `Slot ${slot} is taken by ${other?.title ?? "another project"}.` };
  }

  const blocker = blockerForDay(projectBookings(slots, projectUid, todayDay), day, todayDay);
  if (blocker) return { ok: false, message: blockedReason(blocker, day, todayDay) };

  return {
    ok: true,
    message: `Scheduled in slot ${slot}.`,
    create: { slot_date: day, slot: slot as SlotName, is_done: false, project_uid: projectUid },
  };
}

/**
 * Move a booking, swapping with whatever is already there - move_booking().
 *
 * "Done" describes a day's session, so it travels within a day and is dropped
 * when a booking lands on another date.
 */
export function planMove(
  projects: Project[],
  slots: DaySlot[],
  fromDay: string,
  fromSlot: string,
  toDay: string,
  toSlot: string,
  todayDay: string = today()
): Plan {
  if (!(SLOTS as readonly string[]).includes(toSlot)) return { ok: false, message: "Unknown slot." };
  if (toDay < todayDay) return { ok: false, message: "That day is in the past." };

  const source = slots.find((entry) => entry.slot_date === fromDay && entry.slot === fromSlot);
  if (!source) return { ok: false, message: "That slot is empty." };
  if (fromDay === toDay && fromSlot === toSlot) return { ok: true, message: "Nothing to do." };

  const target = slots.find((entry) => entry.slot_date === toDay && entry.slot === toSlot) ?? null;

  // Both rows are leaving their spots, so neither may count as a blocker - for
  // itself or for the other - while the rule is checked.
  const ignore = new Set([source.uid, ...(target ? [target.uid] : [])]);
  const moves: [DaySlot, string][] = [[source, toDay]];
  if (target) moves.push([target, fromDay]);

  for (const [entry, day] of moves) {
    if (!entry.project_uid) continue;
    const blocker = blockerForDay(
      projectBookings(slots, entry.project_uid, todayDay, ignore),
      day,
      todayDay
    );
    if (blocker) {
      const project = projects.find((candidate) => candidate.uid === entry.project_uid);
      return {
        ok: false,
        message: `${project?.title ?? "That project"}: ${blockedReason(blocker, day, todayDay)}`,
      };
    }
  }

  const updates: Change[] = [
    {
      uid: source.uid,
      changes: {
        slot_date: toDay,
        slot: toSlot as SlotName,
        ...(toDay !== fromDay ? { is_done: false } : {}),
      },
    },
  ];

  if (target) {
    updates.push({
      uid: target.uid,
      changes: {
        slot_date: fromDay,
        slot: fromSlot as SlotName,
        ...(toDay !== fromDay ? { is_done: false } : {}),
      },
    });
    const other = projects.find((candidate) => candidate.uid === target.project_uid);
    return { ok: true, message: `Swapped with ${other?.title ?? "the other booking"}.`, updates };
  }

  return { ok: true, message: `Moved to ${formatDay(toDay)}, slot ${toSlot}.`, updates };
}

/**
 * Take a day off - shift_bookings_forward().
 *
 * A finished session stays exactly where it is: it happened, and "done" belongs
 * to a date. Anything that would land on a spot held by one is held back too,
 * and holds back the booking behind it in turn.
 *
 * Rows are walked newest first, the same order the server uses, because each
 * booking lands on the date the one after it has just left.
 */
export function planDayOff(
  slots: DaySlot[],
  fromDay: string,
  days = 1,
  todayDay: string = today()
): Plan & { moved: number } {
  if (days < 1) return { ok: false, message: "A day off is at least one day.", moved: 0 };
  if (fromDay < todayDay) return { ok: false, message: "That day is in the past.", moved: 0 };

  const affected = slots
    .filter((slot) => slot.slot_date >= fromDay)
    .sort((a, b) => b.slot_date.localeCompare(a.slot_date) || a.slot.localeCompare(b.slot));

  if (affected.length === 0) {
    return { ok: true, message: `${formatDay(fromDay)} was already free.`, moved: 0, updates: [] };
  }

  const updates: Change[] = [];
  // The (date, slot) spots nothing may move onto: a finished session, or a
  // booking stuck behind one.
  const staying = new Set<string>();

  for (const slot of affected) {
    const targetDate = addDays(slot.slot_date, days);
    const targetKey = `${targetDate}|${slot.slot}`;

    if (slot.is_done || staying.has(targetKey)) {
      staying.add(`${slot.slot_date}|${slot.slot}`);
      continue;
    }

    updates.push({ uid: slot.uid, changes: { slot_date: targetDate } });
  }

  return {
    ok: true,
    message: dayOffMessage(fromDay, updates.length, staying.size),
    moved: updates.length,
    updates,
  };
}

function dayOffMessage(fromDay: string, moved: number, stayed: number): string {
  if (!moved) return "Nothing moved — a finished session stays on the day it happened.";

  let message = `Day off on ${formatDay(fromDay)} — ${moved} ${moved === 1 ? "block" : "blocks"} moved a day later.`;
  if (stayed) message += ` ${stayed} stayed put: a finished session does not move.`;
  return message;
}

export interface Candidate {
  uid: string;
  title: string;
  planHeading: string;
  /** "Last session: 3 wk ago" - the note shown when the plan has no heading. */
  lastSession: string;
  isStarred: boolean;
  canTake: boolean;
  reason: string;
}

/**
 * Every active project, annotated with whether it can take this slot.
 *
 * Projects the rule rules out are listed too, with the reason: "where did that
 * project go" is worse than a greyed-out row that explains itself.
 */
export function slotCandidates(
  projects: Project[],
  slots: DaySlot[],
  day: string,
  slot: string,
  todayDay: string = today(),
  lastSessionOf: Map<string, string> = new Map()
): Candidate[] {
  const taken = slots.find((entry) => entry.slot_date === day && entry.slot === slot) ?? null;
  const takenBy = taken
    ? projects.find((candidate) => candidate.uid === taken.project_uid)?.title
    : null;
  const bookings = taken ? new Map<string, BookingPair>() : bookingsByProject(slots, todayDay);

  return [...projects]
    .filter((project) => !project.is_archived)
    .sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()))
    .map((project) => {
      const reason = taken
        ? `Slot ${slot} is taken by ${takenBy ?? "another project"}.`
        : blockedReason(
            blockerForDay(bookings.get(project.uid) ?? [null, null], day, todayDay),
            day,
            todayDay
          );

      return {
        uid: project.uid,
        title: project.title,
        planHeading: firstPlanSectionTitle(project.long_goal),
        lastSession: lastSessionLabel(lastSessionOf.get(project.uid)),
        isStarred: project.is_starred,
        canTake: !reason,
        reason,
      };
    })
    // Available ones first; the rest keep their alphabetical order underneath.
    .sort((a, b) => Number(!a.canTake) - Number(!b.canTake));
}

// ---------------------------------------------------------------------------
// The home page's three cards, and how much of today's plan is done.
// ---------------------------------------------------------------------------

/** "45m" / "2h" / "1h 20m" - _minutes_label(). */
export function minutesLabel(minutes: number | null | undefined, zero = ""): string {
  if (!minutes) return zero;
  const hours = Math.floor(minutes / 60);
  const rest = Math.trunc(minutes) % 60;
  if (hours && rest) return `${hours}h ${String(rest).padStart(2, "0")}m`;
  if (hours) return `${hours}h`;
  return `${rest}m`;
}

export interface SlotCard {
  slot: SlotName;
  booking: DaySlot | null;
  project: Project | null;
  isDone: boolean;
  planHeading: string;
  /** Slot C deliberately carries no time. */
  showsTime: boolean;
  trackedLabel: string;
  targetLabel: string;
  trackedMinutes: number;
  targetMinutes: number;
}

export function slotCards(
  filled: SlotMap,
  projects: Map<string, Project>,
  totals: Map<string | null, number>
): SlotCard[] {
  return SLOTS.map((slot) => {
    const booking = filled[slot];
    const project = booking?.project_uid ? projects.get(booking.project_uid) ?? null : null;

    if (!project) {
      return {
        slot, booking, project: null, isDone: false, planHeading: "",
        showsTime: false, trackedLabel: "", targetLabel: "",
        trackedMinutes: 0, targetMinutes: 0,
      };
    }

    const showsTime = (TIMED_SLOTS as readonly string[]).includes(slot);
    const trackedMinutes = showsTime ? Math.floor((totals.get(project.uid) ?? 0) / 60) : 0;
    const targetMinutes = showsTime ? project.daily_target_minutes ?? 0 : 0;

    return {
      slot,
      booking,
      project,
      isDone: Boolean(booking?.is_done),
      planHeading: firstPlanSectionTitle(project.long_goal),
      showsTime,
      // The same compact format on both sides of the slash: "45m / 2h".
      trackedLabel: showsTime ? minutesLabel(trackedMinutes, "0m") : "",
      targetLabel: minutesLabel(targetMinutes),
      trackedMinutes,
      targetMinutes,
    };
  });
}

/**
 * How much of today's planned time is done - day_progress().
 *
 * Only slots with a target count, on both sides of the ratio: time spent on a
 * project you never set a target for is not progress against a plan. Null when
 * nothing is targeted, so the caller leaves the spot empty.
 */
export function dayProgress(
  cards: SlotCard[]
): { percent: number; trackedLabel: string; targetLabel: string } | null {
  const targeted = cards.filter((card) => card.targetMinutes);
  if (targeted.length === 0) return null;

  const tracked = targeted.reduce((sum, card) => sum + card.trackedMinutes, 0);
  const target = targeted.reduce((sum, card) => sum + card.targetMinutes, 0);

  return {
    percent: Math.round((tracked / target) * 100),
    trackedLabel: minutesLabel(tracked, "0m"),
    targetLabel: minutesLabel(target),
  };
}

// ---------------------------------------------------------------------------
// What the schedule and archive headers say.
// ---------------------------------------------------------------------------

const WEEK_LABELS = ["This week", "Next week", "In two weeks", "In three weeks", "In four weeks"];

// The archive counts the other way, and says so from the week's own dates rather
// than its place on the page - "Last week" has to mean last week on every page.
const PAST_WEEK_LABELS: Record<number, string> = {
  0: "Earlier this week",
  1: "Last week",
  2: "Two weeks ago",
  3: "Three weeks ago",
};

export function weekLabel(index: number): string {
  return WEEK_LABELS[index] ?? `In ${index} weeks`;
}

export function pastWeekLabel(weekStart: string, todayDay: string = today()): string {
  const thisMonday = addDays(todayDay, -weekday(todayDay));
  const weeksAgo = Math.round(
    (new Date(`${thisMonday}T00:00:00Z`).getTime() - new Date(`${weekStart}T00:00:00Z`).getTime()) /
      (86400000 * DAYS_PER_WEEK)
  );
  return PAST_WEEK_LABELS[weeksAgo] ?? `${weeksAgo} weeks ago`;
}

/** "12 Aug" / "12–18 Aug" / "28 Aug – 03 Sep" - _date_range_label(). */
export function dateRangeLabel(first: string, last: string): string {
  const from = new Date(`${first}T00:00:00Z`);
  const to = new Date(`${last}T00:00:00Z`);
  const month = (at: Date) =>
    new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" }).format(at);

  // The current week can be down to a single day, on a Sunday.
  if (first === last) return formatDay(first).replace(/^0/, "");
  if (from.getUTCMonth() === to.getUTCMonth()) {
    return `${from.getUTCDate()}–${to.getUTCDate()} ${month(to)}`;
  }
  return `${formatDay(first)} – ${formatDay(last)}`;
}

export interface SheetSlot {
  slot: SlotName;
  booking: DaySlot | null;
  project: Project | null;
  planHeading: string;
  isDone: boolean;
  /** C is the spare slot; it stays visibly secondary once it is filled. */
  isOptional: boolean;
}

export interface Sheet {
  date: string;
  isToday: boolean;
  isWeekend: boolean;
  slots: SheetSlot[];
  bookedCount: number;
}

/** One calendar sheet, plus what its header has to show. */
export function scheduleSheet(
  day: CalendarDay,
  projects: Map<string, Project>,
  todayDay: string = today()
): Sheet {
  const slots = SLOTS.map((slot) => {
    const booking = day.slots[slot];
    const project = booking?.project_uid ? projects.get(booking.project_uid) ?? null : null;
    return {
      slot,
      booking,
      project,
      planHeading: project ? firstPlanSectionTitle(project.long_goal) : "",
      isDone: Boolean(booking?.is_done),
      isOptional: !(TIMED_SLOTS as readonly string[]).includes(slot),
    };
  });

  return {
    date: day.date,
    isToday: day.date === todayDay,
    isWeekend: weekday(day.date) >= 5,
    slots,
    bookedCount: slots.filter((entry) => entry.project).length,
  };
}

// ---------------------------------------------------------------------------
// The session planner: a fortnight of slots, and where a project already stands.
// ---------------------------------------------------------------------------

export interface WindowSlot {
  slot: SlotName;
  /** The booking itself, so the planner can free a block it is showing. */
  bookingUid: string | null;
  projectUid: string | null;
  projectTitle: string;
  isThisProject: boolean;
  canTake: boolean;
  isDone: boolean;
  /** C is the spare slot; it stays visibly secondary once it is filled. */
  isOptional: boolean;
}

export interface WindowDay {
  date: string;
  label: string;
  isToday: boolean;
  slots: WindowSlot[];
}

/**
 * The planner grid - schedule_window().
 *
 * A fortnight rather than a week: a week was short enough that a project with
 * a booking in it had nowhere left to go, and the dialog scrolls anyway.
 */
export function scheduleWindow(
  projects: Project[],
  slots: DaySlot[],
  projectUid: string,
  days: number = SCHEDULE_WINDOW_DAYS,
  todayDay: string = today()
): WindowDay[] {
  const byUid = new Map(projects.map((project) => [project.uid, project]));
  // The project's own two bookings do not change from day to day, so they are
  // read once for the whole grid rather than per row.
  const bookings = projectBookings(slots, projectUid, todayDay);

  const window: WindowDay[] = [];
  for (let offset = 0; offset < days; offset += 1) {
    const date = addDays(todayDay, offset);
    const blocker = blockerForDay(bookings, date, todayDay);
    const filled = slotsForDate(slots, date);

    window.push({
      date,
      label: new Intl.DateTimeFormat("en-GB", {
        weekday: "short",
        day: "2-digit",
        month: "short",
        timeZone: "UTC",
      }).format(new Date(`${date}T00:00:00Z`)),
      isToday: date === todayDay,
      slots: SLOTS.map((slot) => {
        const booking = filled[slot];
        return {
          slot,
          bookingUid: booking?.uid ?? null,
          projectUid: booking?.project_uid ?? null,
          projectTitle: booking?.project_uid ? byUid.get(booking.project_uid)?.title ?? "" : "",
          isThisProject: booking?.project_uid === projectUid,
          canTake: booking === null && blocker === null,
          isDone: Boolean(booking?.is_done),
          isOptional: !(TIMED_SLOTS as readonly string[]).includes(slot),
        };
      }),
    });
  }
  return window;
}

/**
 * Where this project already stands, as the one line the planner shows.
 *
 * The two-block rule blocks whole days at a time, so saying it per day - or
 * once per booking - only repeats itself.
 */
export function bookingNote(
  slots: DaySlot[],
  projectUid: string,
  todayDay: string = today()
): string {
  const [todaySlot, futureSlot] = projectBookings(slots, projectUid, todayDay);

  const booked: string[] = [];
  if (todaySlot) booked.push(`today in slot ${todaySlot.slot}`);
  if (futureSlot) booked.push(`${formatDay(futureSlot.slot_date)} in slot ${futureSlot.slot}`);
  if (booked.length === 0) return "";

  return (
    `Already planned for ${booked.join(" and ")} — ` +
    "a project takes at most one block today and one later."
  );
}

/**
 * Where the archive's two links go - the pagination from schedule_archive().
 *
 * Both are worked out from the page's own edges rather than by stepping a fixed
 * three weeks from the cursor, which is what keeps the pages gapless whatever
 * weekday the first one starts on.
 */
export function archivePaging(
  slots: DaySlot[],
  until: string,
  todayDay: string = today()
): { firstDay: string; lastDay: string; earlierUntil: string | null; laterUntil: string | null } {
  const yesterday = addDays(todayDay, -1);
  const weeks = pastCalendarWeeks(slots, ARCHIVE_WEEKS, until);

  // The weeks run newest first.
  const firstDay = weeks[weeks.length - 1][0].date;
  const lastWeek = weeks[0];
  const lastDay = lastWeek[lastWeek.length - 1].date;

  const earliest = firstBookedDay(slots);

  return {
    firstDay,
    lastDay,
    // No point offering a page older than the first booking there has ever been.
    earlierUntil: earliest !== null && earliest < firstDay ? addDays(firstDay, -1) : null,
    laterUntil:
      lastDay < yesterday
        ? (() => {
            const candidate = addDays(lastDay, ARCHIVE_WEEKS * DAYS_PER_WEEK);
            return candidate > yesterday ? yesterday : candidate;
          })()
        : null,
  };
}
