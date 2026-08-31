"""The clock, and the one time zone the application reasons in.

Extracted from time_tracking/service.py when that file moved to the client.
What is left on the server needs only these three: instants are stored naive
UTC, and the configured zone decides which calendar day a slot belongs to.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app

DEFAULT_TIMEZONE = "Europe/Warsaw"


def app_timezone():
    name = current_app.config.get("CALENDAR_TIMEZONE", DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def utc_now():
    return datetime.now(timezone.utc)


def today_local():
    """Today in CALENDAR_TIMEZONE, which is what a day slot is keyed on."""
    return utc_now().astimezone(app_timezone()).date()
