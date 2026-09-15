"""
Just enough iCalendar to put someone else's events on a day sheet.

Deliberately a reader and nothing else: it takes the text of an .ics file and
answers "what is on, on these days". No library, no VTIMEZONE arithmetic, no
writing, no round trip - the app never sends anything back to the calendar, so
everything an .ics can say that does not change what shows on a day is dropped
on the floor.

What it does understand, because a real calendar is full of it:

* folded lines, quoted parameters and escaped text;
* ``DTSTART``/``DTEND`` as a date (all-day, end exclusive), as a local time, as
  UTC, or with a ``TZID`` naming an IANA zone;
* ``DURATION`` when there is no ``DTEND``;
* ``RRULE`` for the four frequencies, with ``INTERVAL``, ``COUNT``, ``UNTIL``
  and - weekly - ``BYDAY``, plus ``EXDATE``;
* ``RECURRENCE-ID``, as an instance that replaces the one the rule would have
  produced, so a moved meeting shows once rather than twice.

What it does not: ``BYDAY`` on anything but a weekly rule ("the third Thursday"
falls back to the day of the month it started on), ``BYMONTH``/``BYSETPOS``, and
``VTIMEZONE`` definitions for zones the host does not know. Each of those is a
day or two of code for an event or two a year, and the sheet says where it came
from, so a wrong one is visibly the calendar's line rather than a booking.
"""

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# A recurring event is expanded occurrence by occurrence, so a rule with no
# COUNT and no UNTIL needs a stop of its own. Well past any window a page shows.
MAX_OCCURRENCES = 2000
# Weekday codes as RRULE spells them, in Python's Monday-is-0 order.
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# "DTSTART;TZID=Europe/Warsaw:20260915T090000" - the name, its parameters and
# the value, split at the first colon that is not inside a quoted parameter.
PROPERTY_PATTERN = re.compile(r'^([^:;]+)((?:;(?:[^:;"]|"[^"]*")*)*):(.*)$', re.DOTALL)


class Event:
    """One occurrence-producing entry of a calendar.

    ``start``/``end`` are aware datetimes, or dates for an all-day event. The
    end is exclusive, the way iCalendar means it.
    """

    __slots__ = (
        "uid",
        "summary",
        "start",
        "end",
        "all_day",
        "rrule",
        "exdates",
        "recurrence_id",
        "cancelled",
    )

    def __init__(self, uid="", summary="", start=None, end=None, all_day=False):
        self.uid = uid
        self.summary = summary
        self.start = start
        self.end = end
        self.all_day = all_day
        self.rrule = {}
        self.exdates = set()
        self.recurrence_id = None
        self.cancelled = False


def unfold(text):
    """The file's logical lines: a line beginning with a space continues the last.

    iCalendar wraps at 75 octets, so a summary of any length arrives in pieces.
    """
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def parse_property(line):
    """``"DTSTART;VALUE=DATE:20260915"`` → ``("DTSTART", {"VALUE": "DATE"}, "20260915")``."""
    match = PROPERTY_PATTERN.match(line)
    if match is None:
        return None, {}, ""

    name, raw_params, value = match.groups()
    params = {}
    for part in raw_params.split(";")[1:]:
        key, _, param_value = part.partition("=")
        params[key.strip().upper()] = param_value.strip().strip('"')
    return name.strip().upper(), params, value


def unescape_text(value):
    """TEXT values escape their separators; the sheet wants the words back."""
    out = []
    escaped = False
    for char in value:
        if escaped:
            out.append({"n": "\n", "N": "\n"}.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            out.append(char)
    return "".join(out).strip()


def _zone(tzid, default_zone):
    """The named zone, or the app's own when the host has never heard of it."""
    if not tzid:
        return default_zone
    try:
        return ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError):
        return default_zone


def parse_datetime(value, params, default_zone):
    """One DTSTART/DTEND/EXDATE value as a date (all-day) or an aware datetime.

    Three shapes: ``20260915`` is a day, ``20260915T090000Z`` is UTC, and
    ``20260915T090000`` is either the ``TZID`` zone or - a "floating" time -
    whatever zone the reader is in, which here is the app's.
    """
    value = value.strip()
    if not value:
        return None

    if params.get("VALUE") == "DATE" or len(value) == 8:
        try:
            return datetime.strptime(value[:8], "%Y%m%d").date()
        except ValueError:
            return None

    stamp, _, _ = value.partition("Z")
    try:
        parsed = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None

    if value.endswith("Z"):
        return parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.replace(tzinfo=_zone(params.get("TZID"), default_zone))


def parse_duration(value):
    """``PT1H30M`` / ``P2D`` → a timedelta. Nothing understood → None."""
    match = re.fullmatch(
        r"(?P<sign>[+-])?P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
        r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value.strip().upper(),
    )
    if match is None:
        return None

    parts = {key: int(value) for key, value in match.groupdict().items() if key != "sign" and value}
    if not parts:
        return timedelta(0)

    delta = timedelta(
        weeks=parts.get("weeks", 0),
        days=parts.get("days", 0),
        hours=parts.get("hours", 0),
        minutes=parts.get("minutes", 0),
        seconds=parts.get("seconds", 0),
    )
    return -delta if match.group("sign") == "-" else delta


def parse_rrule(value):
    """``FREQ=WEEKLY;BYDAY=MO,WE`` → a dict of the parts this reader acts on."""
    rule = {}
    for part in value.split(";"):
        key, _, raw = part.partition("=")
        key = key.strip().upper()
        raw = raw.strip()
        if not key or not raw:
            continue
        if key in {"COUNT", "INTERVAL"}:
            try:
                rule[key] = max(int(raw), 1)
            except ValueError:
                continue
        elif key == "BYDAY":
            rule[key] = [day.strip().upper()[-2:] for day in raw.split(",") if day.strip()]
        else:
            rule[key] = raw.upper()
    return rule


def parse_events(text, default_zone):
    """Every VEVENT of an .ics file, as Event objects. Junk in, empty list out."""
    events = []
    event = None

    for line in unfold(text or ""):
        stripped = line.strip()
        if stripped == "BEGIN:VEVENT":
            event = Event()
            continue
        if event is None:
            continue
        if stripped == "END:VEVENT":
            # A cancelled entry is dropped here rather than where it says so:
            # STATUS can come before DTSTART, and the properties are read in
            # whatever order the file lists them.
            if event.start is not None and not event.cancelled:
                events.append(event)
            event = None
            continue

        name, params, value = parse_property(line)
        if name == "UID":
            event.uid = value.strip()
        elif name == "SUMMARY":
            event.summary = unescape_text(value)
        elif name == "DTSTART":
            event.start = parse_datetime(value, params, default_zone)
            event.all_day = isinstance(event.start, date) and not isinstance(event.start, datetime)
        elif name == "DTEND":
            event.end = parse_datetime(value, params, default_zone)
        elif name == "DURATION":
            event.end = parse_duration(value)  # Turned into an end below.
        elif name == "RRULE":
            event.rrule = parse_rrule(value)
        elif name == "EXDATE":
            for part in value.split(","):
                excluded = parse_datetime(part, params, default_zone)
                if excluded is not None:
                    event.exdates.add(_day_of(excluded, default_zone))
        elif name == "RECURRENCE-ID":
            event.recurrence_id = parse_datetime(value, params, default_zone)
        elif name == "STATUS":
            event.cancelled = value.strip().upper() == "CANCELLED"

    for entry in events:
        if isinstance(entry.end, timedelta):
            entry.end = entry.start + entry.end
        if entry.end is None:
            # No end and no duration: a day for an all-day entry, a moment
            # otherwise - both of which land it on its start day and no further.
            entry.end = entry.start + timedelta(days=1) if entry.all_day else entry.start
    return events


def _day_of(value, zone):
    """The calendar day a start falls on, in the app's zone."""
    if isinstance(value, datetime):
        return value.astimezone(zone).date()
    return value


def _occurrence_starts(event, until_day, zone):
    """The start of every occurrence of one event up to ``until_day``.

    A non-recurring event has exactly one. A recurring one is walked forward
    from its own start: the window a page asks for is weeks wide at most, so
    counting up to it costs less than the arithmetic to jump straight there,
    and the same walk handles COUNT, UNTIL and the cap together.
    """
    start = event.start
    rule = event.rrule
    if not rule:
        return [start]

    frequency = rule.get("FREQ")
    interval = rule.get("INTERVAL", 1)
    count = rule.get("COUNT")
    until = None
    if rule.get("UNTIL"):
        until = parse_datetime(rule["UNTIL"], {}, zone)

    steps = {
        "DAILY": lambda index: timedelta(days=index * interval),
        "WEEKLY": lambda index: timedelta(weeks=index * interval),
    }
    if frequency in steps:
        step = steps[frequency]
    elif frequency in {"MONTHLY", "YEARLY"}:
        step = None
    else:
        return [start]

    # A weekly rule may fire on several weekdays; the offsets from the week the
    # event starts in are the same every time round.
    weekday_offsets = [0]
    if frequency == "WEEKLY" and rule.get("BYDAY"):
        first = _day_of(start, zone)
        week_start = first - timedelta(days=first.weekday())
        weekday_offsets = sorted(
            (week_start + timedelta(days=WEEKDAYS.index(day)) - first).days
            for day in rule["BYDAY"]
            if day in WEEKDAYS
        ) or [0]

    starts = []
    index = 0
    # Two caps, because the two ways round can each run away: a rule with
    # neither COUNT nor UNTIL, and a monthly one whose day does not exist in
    # most months and so produces nothing to measure the window against.
    while index < MAX_OCCURRENCES and len(starts) < MAX_OCCURRENCES:
        if step is not None:
            base = start + step(index)
        else:
            base = _add_months(start, index * interval * (12 if frequency == "YEARLY" else 1))
            if base is None:
                index += 1
                continue

        # Past the window unless one of this round's days lands inside it. A
        # weekly BYDAY can reach back before its own base, so every offset gets
        # a say before the walk gives up.
        past_window = _day_of(base, zone) > until_day
        for offset in weekday_offsets:
            moment = base + timedelta(days=offset)
            if moment < start:
                continue
            day = _day_of(moment, zone)
            if until is not None and day > _day_of(until, zone):
                return starts
            if day <= until_day:
                past_window = False
            starts.append(moment)
            if count is not None and len(starts) >= count:
                return starts

        if past_window:
            break
        index += 1

    return starts


def _add_months(moment, months):
    """``moment`` ``months`` later, keeping the day of the month.

    A 31st that does not exist in the target month is skipped rather than
    clamped to the 30th - that is what a calendar does with a monthly rule, and
    quietly moving it would put the event on a day it is not on.
    """
    if not months:
        return moment

    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    try:
        return moment.replace(year=year, month=month)
    except ValueError:
        return None


def events_by_day(text, first_day, last_day, zone):
    """``{date: [{"summary", "time_label", "all_day", "sort_key"}, ...]}``.

    Every occurrence between the two dates, inclusive, bucketed by the day it
    falls on in ``zone``. A meeting that runs past midnight, or an all-day entry
    over a long weekend, appears on each day it covers.
    """
    events = parse_events(text, zone)

    # A moved occurrence replaces the one the rule would have produced, rather
    # than showing up beside it.
    overridden = {
        (entry.uid, _day_of(entry.recurrence_id, zone))
        for entry in events
        if entry.recurrence_id is not None and entry.uid
    }

    by_day = {}
    for event in events:
        length = event.end - event.start if event.end and event.end > event.start else timedelta(0)

        for start in _occurrence_starts(event, last_day, zone):
            start_day = _day_of(start, zone)
            if start_day in event.exdates:
                continue
            if event.recurrence_id is None and (event.uid, start_day) in overridden:
                continue

            # All-day ends are exclusive, so a one-day entry covers one day.
            last_covered = _day_of(start + length, zone)
            if event.all_day and length:
                last_covered -= timedelta(days=1)
            last_covered = max(last_covered, start_day)
            if last_covered < first_day or start_day > last_day:
                continue

            day = max(start_day, first_day)
            while day <= min(last_covered, last_day):
                by_day.setdefault(day, []).append(
                    {
                        "summary": event.summary or "(no title)",
                        "all_day": event.all_day,
                        # Only the first day of a longer event shows a time -
                        # on the days after it, the event is simply on.
                        "time_label": ""
                        if event.all_day or day != start_day
                        else start.astimezone(zone).strftime("%H:%M"),
                        "sort_key": (
                            0 if event.all_day else 1,
                            start.astimezone(zone).time() if not event.all_day else time.min,
                        ),
                    }
                )
                day += timedelta(days=1)

    # All-day entries first, then the rest by the clock: the same order a day
    # reads in.
    for entries in by_day.values():
        entries.sort(key=lambda entry: (entry["sort_key"], entry["summary"]))
    return by_day
