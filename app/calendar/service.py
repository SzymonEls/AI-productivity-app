from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import recurring_ical_events
import requests
from icalendar import Calendar
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning


disable_warnings(InsecureRequestWarning)


def fetch_daily_plan(subscriptions, target_date, timezone_name, timeout=10):
    """Collect and merge iCal events for one day across all user subscriptions."""

    timezone = ZoneInfo(timezone_name)
    range_start = datetime.combine(target_date, time.min, timezone)
    range_end = range_start + timedelta(days=1)

    events = []
    errors = []

    for subscription in subscriptions:
        try:
            response = requests.get(subscription.ical_url, timeout=timeout, verify=False)
            response.raise_for_status()
            calendar = Calendar.from_ical(response.content)

            for component in recurring_ical_events.of(calendar).between(range_start, range_end):
                parsed_event = _parse_ical_event(
                    component=component,
                    calendar_name=subscription.name,
                    day_start=range_start,
                    day_end=range_end,
                    timezone=timezone,
                )
                if parsed_event:
                    events.append(parsed_event)
        except requests.RequestException as exc:
            errors.append(f"{subscription.name}: nie udalo sie pobrac kalendarza ({exc})")
        except Exception as exc:
            errors.append(f"{subscription.name}: nie udalo sie odczytac danych iCal ({exc})")

    events.sort(key=lambda item: (item["sort_start"], not item["is_all_day"], item["title"].lower()))
    return events, errors


def normalize_requested_date(raw_value):
    """Turn `YYYY-MM-DD` query input into a safe date value."""

    if not raw_value:
        return date.today()

    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return date.today()


def _parse_ical_event(component, calendar_name, day_start, day_end, timezone):
    raw_start = component.decoded("DTSTART")
    start = _to_local_datetime(raw_start, timezone)
    end = _to_local_datetime(component.decoded("DTEND"), timezone) if component.get("DTEND") else None
    title = str(component.get("SUMMARY", "Bez tytulu"))
    is_all_day = isinstance(raw_start, date) and not isinstance(raw_start, datetime)

    if is_all_day and end is None:
        end = start + timedelta(days=1)
    elif not is_all_day and end is None:
        end = start

    if not start or not end or end <= day_start or start >= day_end:
        return None

    display_start = max(start, day_start)
    display_end = min(end, day_end)

    return {
        "title": title,
        "calendar_name": calendar_name,
        "start": start,
        "end": end,
        "display_start": display_start,
        "display_end": display_end,
        "is_all_day": is_all_day,
        "sort_start": start if not is_all_day else day_start,
    }


def _to_local_datetime(value, timezone):
    if isinstance(value, datetime):
        if value.tzinfo:
            return value.astimezone(timezone)
        return value.replace(tzinfo=timezone)

    if isinstance(value, date):
        return datetime.combine(value, time.min, timezone)

    return None
