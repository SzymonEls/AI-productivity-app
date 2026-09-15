"""
Subscribed calendars: fetching them, keeping the last copy, and answering what
is on which day.

The integration is deliberately one-way and one-field. A calendar is a URL
ending in .ics - the "secret address" from Google, iCloud, Outlook or a plain
file on a web server - and this reads it on a timer. There is no OAuth, no API
client, no token to expire and nothing written back, which is why a public and a
private iCal address behave identically here: the private one simply shows more.

Fetching never happens while a page renders. The schedule and the archive read
the cached copy and nothing else, and the page then asks - once it is on the
screen - whether anything has gone stale; ``refresh_due`` runs in that request,
not in the one the reader is waiting on. Otherwise every thirtieth visit to the
schedule would be a wait on someone else's server.

The rest of the timing follows from that:

* a feed is only re-read once the user's own interval has passed (their
  ``calendar_refresh_minutes``, set on the Integrations page), and a feed that
  failed counts as read for that purpose too, so a dead URL is retried on that
  same interval rather than on every page;
* every fetch has a short timeout and a size cap, the round has a budget, and a
  failure leaves the last good copy in place, so the sheets keep showing the
  calendar they last knew about;
* a calendar is read once, synchronously, when it is added - that is a form
  being submitted, where a wait is what "does this address work?" costs.
"""

import ipaddress
import socket
import time
from collections import OrderedDict
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from sqlalchemy import or_

from ..extensions import db
from ..models import MAX_REFRESH_MINUTES, MIN_REFRESH_MINUTES, CalendarFeed
from ..time_tracking.service import app_timezone, utc_now
from .ical import events_by_day

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


def refresh_after(user):
    """How stale this user lets a calendar get, as a timedelta.

    Their own setting, from the Integrations page, clamped here as well as where
    it is saved - the column outlives whatever the form looked like when the
    number was typed into it.
    """
    minutes = user.calendar_refresh_minutes or MIN_REFRESH_MINUTES
    return timedelta(minutes=max(MIN_REFRESH_MINUTES, min(int(minutes), MAX_REFRESH_MINUTES)))


def stale_cutoff(user):
    """The moment before which a copy counts as stale for this user."""
    return (utc_now() - refresh_after(user)).replace(tzinfo=None)


def has_stale_feeds(user):
    """Is there anything worth re-reading? One count, no network.

    The schedule renders with this rather than with a refresh: it decides
    whether the page bothers asking at all, so a reader with no calendars - or
    with fresh ones - costs nothing beyond the count.
    """
    return bool(
        CalendarFeed.query.filter(
            CalendarFeed.user_id == user.id,
            CalendarFeed.is_enabled.is_(True),
            or_(CalendarFeed.checked_at.is_(None), CalendarFeed.checked_at < stale_cutoff(user)),
        ).count()
    )


def refresh_due(user, force=False):
    """Re-read the feeds that have gone stale. Returns how many were read.

    Called from a request of its own - the one the schedule page makes once it
    is already on the screen, and the button on the integrations page - never
    from a render somebody is waiting on. The budget still applies: a round that
    runs long leaves the rest due, and the next one picks up where it left off.

    ``force`` is the button, which means "now" rather than "when it is due".
    """
    cutoff = stale_cutoff(user)
    due = [
        feed
        for feed in user_feeds(user.id)
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


# Days worked out from one copy of one calendar, kept in the worker that did the
# work. The schedule re-renders far more often than a calendar changes - every
# click on the board is another render of the same five weeks - and the answer
# cannot differ while the text, the window and the zone are the same, so it is
# worked out once per version instead of once per page.
#
# Keyed on ``fetched_at``, so a re-read is a new key and the old one simply ages
# out; there is nothing to invalidate by hand. Entries are never handed out raw -
# events_by_date() copies each line before it goes anywhere near a template - so
# nothing downstream can write into what is cached here.
_EXPANDED = OrderedDict()
# The bound is on entries, because one entry is a window rather than a file: a
# busy calendar's five weeks is about 38 kB of small dicts, so a cache filled to
# here holds roughly 8 MB in the worker that filled it. Reaching that takes ten
# busy calendars and a walk back through fifteen archive pages; the usual state
# of this thing is a handful of entries.
MAX_CACHED_WINDOWS = 200


def _expanded(feed, first_day, last_day, zone):
    """One calendar's days over one window, off the cache when it can be."""
    key = (feed.id, feed.fetched_at, first_day, last_day, str(zone))

    cached = _EXPANDED.get(key)
    if cached is not None:
        _EXPANDED.move_to_end(key)
        return cached

    days = events_by_day(feed.cached_ics, first_day, last_day, zone)
    _EXPANDED[key] = days
    while len(_EXPANDED) > MAX_CACHED_WINDOWS:
        _EXPANDED.popitem(last=False)
    return days


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

        for day, entries in _expanded(feed, first_day, last_day, zone).items():
            for entry in entries:
                # A copy per line, which is also what keeps the cache read-only.
                by_date.setdefault(day, []).append({**entry, "calendar": feed.name})

    # One day's events read in the order the day does, whichever calendars they
    # came from.
    for entries in by_date.values():
        entries.sort(key=lambda entry: (entry["sort_key"], entry["summary"]))
    return by_date
