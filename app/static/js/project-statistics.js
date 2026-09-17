/**
 * The Statistics card on a project page: three weeks of sessions, worked out
 * only when someone asks for them.
 *
 * The card is rendered empty and this fills it in place - no reload, a spinner
 * while the server counts. That is the whole reason it works this way: the
 * figures mean reading every booking and every timer entry of the last three
 * weeks, and the project page is opened far more often than the numbers are
 * wanted, so making the page pay for them on every visit would be paying for
 * nothing nearly every time.
 *
 * Asking again re-reads rather than showing what was fetched before: a session
 * finished in another tab, or the timer stopped a minute ago, should show up.
 */
(function () {
    "use strict";

    const card = document.querySelector("[data-project-statistics]");
    if (!card) {
        return;
    }

    const endpoint = card.dataset.statisticsUrl || "";
    const button = card.querySelector("[data-statistics-load]");
    const hint = card.querySelector("[data-statistics-hint]");
    const loading = card.querySelector("[data-statistics-loading]");
    const figures = card.querySelector("[data-statistics-figures]");
    const perWeek = card.querySelector("[data-statistics-per-week]");
    const average = card.querySelector("[data-statistics-average]");
    const note = card.querySelector("[data-statistics-note]");

    let pending = false;

    function show(element, visible) {
        if (element) {
            element.classList.toggle("d-none", !visible);
        }
    }

    function setNote(message, tone) {
        if (!note) {
            return;
        }
        note.textContent = message || "";
        note.className = `statistics-note mb-0${tone ? ` statistics-note-${tone}` : ""}${
            message ? "" : " d-none"
        }`;
    }

    function setLoading(on) {
        pending = on;
        show(loading, on);
        if (button) {
            button.disabled = on;
        }
        if (on) {
            show(hint, false);
            show(figures, false);
            setNote("", "");
        }
    }

    function render(statistics) {
        if (perWeek) {
            perWeek.textContent = statistics.sessions_per_week_label;
        }
        if (average) {
            average.textContent = statistics.average_label;
        }
        show(figures, true);

        // A session is a day the project was worked on, so the count is what the
        // two averages are built from - without it "0.0 a week" and "0m" read as
        // a failure rather than as an empty three weeks.
        if (!statistics.sessions) {
            setNote("No sessions in the last three weeks.", "quiet");
            return;
        }
        const sessions = statistics.sessions === 1 ? "1 session" : `${statistics.sessions} sessions`;
        setNote(`${sessions} over the last three weeks, ${statistics.tracked_label} tracked.`, "quiet");
    }

    function load() {
        if (pending || !endpoint) {
            return;
        }
        setLoading(true);

        fetch(endpoint, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(async (response) => {
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.message || "Could not work out the statistics.");
                }
                return payload.statistics;
            })
            .then((statistics) => {
                setLoading(false);
                render(statistics);
                if (button) {
                    button.textContent = "Refresh";
                }
            })
            .catch((error) => {
                setLoading(false);
                show(hint, true);
                setNote(error.message, "bad");
            });
    }

    button?.addEventListener("click", load);
})();
