/**
 * Keeping the subscribed calendars up to date without making anyone wait for
 * them.
 *
 * The schedule and the archive render from the copy of each calendar the server
 * already has, which costs no network at all. Re-reading one does - it is a
 * request to somebody else's server, and it can time out - so it happens here
 * instead: once the page is on the screen, and only when the server said on the
 * way out that something had gone stale.
 *
 * Nothing is redrawn unless the round actually read something and the days came
 * back different, so the usual case is one small request and no repaint. Only
 * the event lines are touched; the notes below them are the reader's and may
 * well be half-written at that moment.
 */
(function () {
    "use strict";

    const root = document.querySelector("[data-calendar-refresh]");
    if (!root) {
        // No calendars, or nothing due: the page said so, and it has the
        // database to say it with.
        return;
    }

    const ENDPOINT = "/integrations/calendars/refresh-due";
    const statusOutput = document.querySelector("[data-schedule-status], [data-archive-status]");

    function setStatus(message, tone) {
        if (!statusOutput || !message) {
            return;
        }
        statusOutput.textContent = message;
        statusOutput.className = `schedule-status${tone ? ` schedule-status-${tone}` : ""}`;
        window.setTimeout(() => {
            statusOutput.textContent = "";
            statusOutput.className = "schedule-status";
        }, 4000);
    }

    /* The same line the day sheet macro renders for one event. */
    function buildEvent(event) {
        const item = document.createElement("li");
        item.className = `day-event${event.all_day ? " day-event-all-day" : ""}`;
        item.title = `${event.summary} — ${event.calendar}`;

        if (event.time_label) {
            const time = document.createElement("span");
            time.className = "day-event-time";
            time.textContent = event.time_label;
            item.append(time);
        }

        const title = document.createElement("span");
        title.className = "day-event-title";
        title.textContent = event.summary;
        item.append(title);
        return item;
    }

    /* Whether a sheet's lines already say what the server just sent, so an
       unchanged calendar - much the commonest answer - repaints nothing. */
    function sameAsRendered(list, events) {
        const rendered = Array.from(list.children).map((item) => item.title);
        return (
            rendered.length === events.length &&
            rendered.every((title, index) => title === `${events[index].summary} — ${events[index].calendar}`)
        );
    }

    function paint(days) {
        let changed = 0;

        Object.entries(days).forEach(([date, events]) => {
            const footer = document.querySelector(`[data-day-notes][data-date="${date}"]`);
            const list = footer?.querySelector("[data-event-list]");
            if (!list || sameAsRendered(list, events)) {
                return;
            }

            list.replaceChildren(...events.map(buildEvent));
            changed += 1;
        });
        return changed;
    }

    // After the page is up, and out of the way of everything it is still doing.
    window.setTimeout(() => {
        fetch(ENDPOINT, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({ from: root.dataset.calendarFrom, to: root.dataset.calendarTo }),
        })
            .then(async (response) => {
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.message || "Could not read the calendars.");
                }
                return payload;
            })
            .then((payload) => {
                if (!payload.days) {
                    return;
                }
                const changed = paint(payload.days);
                if (changed) {
                    setStatus("Calendars updated.", "success");
                }
            })
            .catch(() => {
                /* The sheets already show the last copy the server had, which is
                   the right thing to be looking at when a calendar cannot be
                   reached. The integrations page is where that is reported. */
            });
    }, 250);
})();
