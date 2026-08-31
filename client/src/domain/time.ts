/**
 * Time and time zones, ported from app/time_tracking/service.py.
 *
 * The rule that file states and this one keeps: instants are stored and moved
 * as UTC, and converted to the configured zone only to be shown or to decide
 * which day something falls on. ARCHITECTURE.md flags this as a place not to
 * mix the two, and every subtle bug here is a session landing on the wrong day.
 */

import type { TimeEntry } from "../sync/types";

export const DEFAULT_TIMEZONE = "Europe/Warsaw";

let configuredTimezone = DEFAULT_TIMEZONE;

export function useTimezone(name: string | undefined): void {
  if (!name) return;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: name });
    configuredTimezone = name;
  } catch {
    configuredTimezone = DEFAULT_TIMEZONE;
  }
}

export function timezone(): string {
  return configuredTimezone;
}

/** How far the zone is from UTC at a given instant, in milliseconds. */
function offsetAt(instant: Date, zone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(instant);

  const field = (type: string) => Number(parts.find((part) => part.type === type)!.value);
  const asIfUtc = Date.UTC(
    field("year"),
    field("month") - 1,
    field("day"),
    field("hour") % 24,
    field("minute"),
    field("second"),
    // formatToParts stops at seconds. Without carrying the milliseconds across,
    // the difference below is not an offset but an offset minus a fraction of a
    // second - which pushed the end of a day past midnight.
    instant.getUTCMilliseconds()
  );
  return asIfUtc - instant.getTime();
}

/**
 * The instant at which a wall-clock time occurs in the configured zone.
 *
 * Checked twice on purpose: the first guess uses the offset in force at the
 * wrong instant, which lands an hour out on the two days a year the clocks
 * change.
 */
function zonedToInstant(day: string, clock: string, zone = configuredTimezone): Date {
  const naive = new Date(`${day}T${clock}Z`);
  const firstGuess = new Date(naive.getTime() - offsetAt(naive, zone));
  const settled = offsetAt(firstGuess, zone);
  return new Date(naive.getTime() - settled);
}

/** The calendar date an instant falls on, in the configured zone. */
export function localDate(instant: Date = new Date(), zone = configuredTimezone): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(instant);
}

export function today(): string {
  return localDate();
}

/** First and last instant of a local day, as UTC - day_bounds_utc(). */
export function dayBounds(day: string): [Date, Date] {
  return [zonedToInstant(day, "00:00:00.000"), zonedToInstant(day, "23:59:59.999")];
}

export function parseInstant(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** "HH:MM:SS", zero-padded and never negative - format_duration(). */
export function formatDuration(totalSeconds: number): string {
  const total = Math.max(Math.trunc(totalSeconds || 0), 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

export function elapsedSeconds(entry: TimeEntry, now: Date = new Date()): number {
  const started = parseInstant(entry.started_at);
  if (!started) return 0;
  const ended = parseInstant(entry.ended_at) ?? now;
  return Math.max(Math.trunc((ended.getTime() - started.getTime()) / 1000), 0);
}

/**
 * How much of an entry falls inside a window - entry_overlap_seconds().
 *
 * This is the only reason a timer left running across midnight is counted
 * against both days correctly rather than landing entirely on one.
 */
export function overlapSeconds(
  entry: TimeEntry,
  rangeStart: Date,
  rangeEnd: Date,
  now: Date = new Date()
): number {
  const started = parseInstant(entry.started_at);
  if (!started) return 0;
  const ended = parseInstant(entry.ended_at) ?? now;

  const overlapStart = Math.max(started.getTime(), rangeStart.getTime());
  const overlapEnd = Math.min(ended.getTime(), rangeEnd.getTime());
  return Math.max(Math.trunc((overlapEnd - overlapStart) / 1000), 0);
}

/** Entries touching a window, newest first - entries_for_range(). */
export function entriesForRange(
  entries: TimeEntry[],
  rangeStart: Date,
  rangeEnd: Date,
  projectUid?: string | null
): TimeEntry[] {
  return entries
    .filter((entry) => {
      const started = parseInstant(entry.started_at);
      if (!started || started.getTime() > rangeEnd.getTime()) return false;
      const ended = parseInstant(entry.ended_at);
      if (ended && ended.getTime() < rangeStart.getTime()) return false;
      if (projectUid && entry.project_uid !== projectUid) return false;
      return true;
    })
    .sort((a, b) => b.started_at.localeCompare(a.started_at));
}

/** Seconds tracked per project on one local day - daily_totals_by_project(). */
export function dailyTotalsByProject(
  entries: TimeEntry[],
  day: string,
  now: Date = new Date()
): Map<string | null, number> {
  const [rangeStart, rangeEnd] = dayBounds(day);
  const totals = new Map<string | null, number>();

  for (const entry of entriesForRange(entries, rangeStart, rangeEnd)) {
    const seconds = overlapSeconds(entry, rangeStart, rangeEnd, now);
    totals.set(entry.project_uid, (totals.get(entry.project_uid) ?? 0) + seconds);
  }
  return totals;
}

export function activeEntry(entries: TimeEntry[]): TimeEntry | null {
  return (
    entries
      .filter((entry) => entry.ended_at === null)
      .sort((a, b) => b.started_at.localeCompare(a.started_at))[0] ?? null
  );
}

/** The first "# " heading of a plan - first_plan_section_title(). */
export function firstPlanSectionTitle(markdown: string | null | undefined): string {
  for (const line of (markdown ?? "").split("\n")) {
    if (line.startsWith("# ") && line.trim().slice(2).trim()) {
      return line.trim().slice(2).trim();
    }
  }
  return "";
}

/** human_last_session_label(), thresholds copied rather than reinvented. */
export function lastSessionLabel(value: string | null | undefined, now: Date = new Date()): string {
  const timestamp = parseInstant(value);
  if (!timestamp) return "Last session: none";

  const seconds = Math.max(Math.trunc((now.getTime() - timestamp.getTime()) / 1000), 0);

  if (seconds < 60) return "Last session: just now";
  if (seconds < 3600) return `Last session: ${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `Last session: ${Math.floor(seconds / 3600)} hr ago`;
  if (seconds < 172800) return "Last session: yesterday";
  if (seconds < 604800) return `Last session: ${Math.floor(seconds / 86400)} days ago`;
  if (seconds < 1209600) return "Last session: a week ago";
  if (seconds < 2592000) return `Last session: ${Math.floor(seconds / 604800)} wk ago`;
  if (seconds < 31536000) return `Last session: ${Math.floor(seconds / 2592000)} mo ago`;

  const years = Math.floor(seconds / 31536000);
  return years === 1 ? "Last session: a year ago" : `Last session: ${years} years ago`;
}
