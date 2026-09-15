"""
Subscribed calendars: fetching them, keeping the last copy, and answering what
is on which day.

The integration is deliberately one-way and one-field. A calendar is a URL
ending in .ics - the "secret address" from Google, iCloud, Outlook or a plain
file on a web server - and this reads it on a timer. There is no OAuth, no API
client, no token to expire and nothing written back, which is why a public and a
private iCal address behave identically here: the private one simply shows more.

Fetching happens while a page renders, which is why the timing matters:

* a feed is only re-read once every ``REFRESH_AFTER``, and a feed that failed
  counts as read for that purpose too, so a dead URL costs one slow render an
  hour rather than one per page;
* every fetch has a short timeout and a size cap, and a failure leaves the last
  good copy in place, so the sheets keep showing the calendar they knew about.
"""

import ipaddress
import socket
import time
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ..extensions import db
from ..models import CalendarFeed
from ..time_tracking.service import app_timezone, utc_now
from .ical import events_by_day


# How stale a copy may get before a page render goes and re-reads it.
REFRESH_AFTER = timedelta(minutes=30)
# Per fetch. A calendar that cannot answer in this long must not hold a page up.
FETCH_TIMEOUT_SECONDS = 6
# And per render, across all of them: three calendars all timing out would be
# three times the above on one page load. Whatever is left over stays due and is
# picked up by the next render.
REFRESH_BUDGET_SECONDS = 8
# Calendars are text; anything this big is not one this app should be holding.
MAX_FEED_BYTES = 4 * 1024 * 1024
# Enough for the calendars a week is planned around, and a bound on how much
# work one page render can be made to do.
MAX_FEEDS_PER_USER = 10
USER_AGENT = "productivity-app/calendar-feed"


def user_feeds(user_id):
    """Every feed the user has added, oldest first."""
    return (
        CalendarFeed.query.filter_by(user_id=user_id)
        .order_by(CalendarFeed.created_at.asc(), CalendarFeed.id.asc())
        .all()
    )


def normalise_url(raw):
    """The URL to store, or ``(None, why not)``.

    ``webcal://`` is what a calendar hands out to open in a desktop client; it is
    https underneath, and the app is not a desktop client, so it is rewritten
    rather than refused.
    """
    raw = (raw or "").strip()
    if not raw:
        return None, "Paste the calendar's iCal address."

    parts = urlsplit(raw)
    if parts.scheme.lower() == "webcal":
        parts = parts._replace(scheme="https")
    if parts.scheme.lower() not in {"http", "https"}:
        return None, "That has to be an http(s) or webcal address."
    if not parts.netloc:
        return None, "That address has no host in it."
    if len(raw) > 2000:
        return None, "That address is too long."

    return urlunsplit(parts), ""


def _refuse_private_host(url):
    """Refuse an address that points back inside the network, or nowhere.

    The app fetches this URL itself, from wherever it is deployed, so an address
    naming a private host would make it a proxy into a network the person typing
    it cannot otherwise reach. Registration can be open, so that is worth a DNS
    lookup rather than trust.
    """
    host = urlsplit(url).hostname or ""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return "That host could not be looked up."

    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return "That host could not be looked up."
        if (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_reserved
            or parsed.is_multicast
        ):
            return "That address points inside the server's own network."
    return ""


def add_feed(user_id, name, url):
    """Subscribe to one calendar. Returns ``(feed, message)``; the caller commits."""
    name = (name or "").strip()[:120]
    url, problem = normalise_url(url)
    if problem:
        return None, problem

    if CalendarFeed.query.filter_by(user_id=user_id).count() >= MAX_FEEDS_PER_USER:
        return None, f"That is already {MAX_FEEDS_PER_USER} calendars — remove one first."
    if CalendarFeed.query.filter_by(user_id=user_id, url=url).first():
        return None, "That calendar is already on the list."

    problem = _refuse_private_host(url)
    if problem:
        return None, problem

    feed = CalendarFeed(user_id=user_id, name=name or _name_from_url(url), url=url)
    db.session.add(feed)
    # Read straight away rather than at the next page render: pasting an address
    # and being told there and then whether it answers is the whole of setting
    # this up.
    fetch_feed(feed)
    return feed, feed.last_error or f"Added {feed.name}."


def _name_from_url(url):
    """A calendar with no name given takes its host, which is usually enough."""
    return (urlsplit(url).hostname or "Calendar")[:120]


def delete_feed(user_id, feed_id):
    """Unsubscribe. Returns ``(ok, message)``; the caller commits."""
    feed = CalendarFeed.query.filter_by(id=feed_id, user_id=user_id).first()
    if feed is None:
        return False, "That calendar is not on the list."

    db.session.delete(feed)
    return True, f"Removed {feed.name}."


def set_feed_enabled(user_id, feed_id, enabled):
    """Switch a calendar's events off the sheets without forgetting the address."""
    feed = CalendarFeed.query.filter_by(id=feed_id, user_id=user_id).first()
    if feed is None:
        return False, "That calendar is not on the list."

    feed.is_enabled = bool(enabled)
    return True, f"{feed.name} is {'on' if feed.is_enabled else 'off'} the sheets."


def fetch_feed(feed):
    """Re-read one calendar. Returns True when the copy on the row changed.

    Never raises: a calendar that is down, slow, moved or serving something that
    is not a calendar is a line on the integrations page, not a broken schedule.
    """
    feed.checked_at = utc_now().replace(tzinfo=None)

    try:
        request = Request(feed.url, headers={"User-Agent": USER_AGENT, "Accept": "text/calendar"})
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            # One byte over the cap is enough to know it is over the cap.
            body = response.read(MAX_FEED_BYTES + 1)
    except HTTPError as error:
        # A subclass of URLError, so it has to be caught before it.
        feed.last_error = f"The calendar answered {error.code}."
        return False
    except (URLError, OSError, ValueError) as error:
        # Refused, timed out, DNS, TLS, a redirect loop, an address urllib will
        # not have - all of them are "this calendar did not answer" here.
        feed.last_error = f"Could not read the calendar: {_reason(error)}"
        return False

    if len(body) > MAX_FEED_BYTES:
        feed.last_error = "That calendar is too big to keep."
        return False

    text = body.decode("utf-8", "replace")
    if "BEGIN:VCALENDAR" not in text:
        feed.last_error = "That address did not answer with a calendar."
        return False

    changed = text != feed.cached_ics
    feed.cached_ics = text
    feed.fetched_at = feed.checked_at
    feed.last_error = ""
    return changed


def _reason(error):
    """The short half of an exception, as a line for the integrations page.

    The two that actually happen - a typo in the host and a calendar that will
    not answer - are worth saying in words; anything rarer keeps whatever the
    exception said, trimmed to fit the column.
    """
    reason = getattr(error, "reason", error)
    if isinstance(reason, socket.gaierror):
        return "that host could not be found."
    if isinstance(reason, TimeoutError) or isinstance(error, TimeoutError):
        return "it took too long to answer."
    return str(reason)[:160] or error.__class__.__name__


def refresh_due(user_id, force=False):
    """Re-read the feeds that have gone stale. Returns how many were read.

    Called while the schedule and the archive render, which is the one thing to
    keep in mind here: it may not turn a page load into a wait on someone else's
    server. Hence the budget - once it is spent the rest stay due, and the next
    render picks up where this one left off.

    ``force`` is the button on the integrations page, which means "now" rather
    than "when it is due"; it still keeps the budget.
    """
    cutoff = (utc_now() - REFRESH_AFTER).replace(tzinfo=None)
    due = [
        feed
        for feed in user_feeds(user_id)
        if feed.is_enabled and (force or feed.checked_at is None or feed.checked_at < cutoff)
    ]

    read = 0
    deadline = time.monotonic() + REFRESH_BUDGET_SECONDS
    for feed in due:
        if read and time.monotonic() >= deadline:
            break
        fetch_feed(feed)
        read += 1

    if read:
        db.session.commit()
    return read


def events_by_date(user_id, first_day, last_day, feeds=None):
    """``{date: [event, ...]}`` over a range, from every switched-on calendar.

    Each event carries the calendar it came from, because a sheet showing two
    lines from two calendars has to be able to say which is which.
    """
    zone = app_timezone()
    by_date = {}

    for feed in feeds if feeds is not None else user_feeds(user_id):
        if not feed.is_enabled or not feed.cached_ics:
            continue

        for day, entries in events_by_day(feed.cached_ics, first_day, last_day, zone).items():
            for entry in entries:
                by_date.setdefault(day, []).append({**entry, "calendar": feed.name})

    # One day's events read in the order the day does, whichever calendars they
    # came from.
    for entries in by_date.values():
        entries.sort(key=lambda entry: (entry["sort_key"], entry["summary"]))
    return by_date
