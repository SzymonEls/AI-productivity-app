/**
 * The schedule's calendar view: "Show more weeks" without a reload.
 *
 * The page opens on the weeks the server rendered and ends in
 * [data-schedule-autoload], which carries the Monday after its last day. Its
 * button asks for the next weeks and appends them above it - the same week
 * sections the page itself is made of, so the board, the notes and the tasks,
 * all bound to the page rather than to a sheet, work on them as they arrived.
 *
 * The sheets view hides this and keeps its own "Show more weeks" link.
 */
(function () {
    "use strict";

    const root = document.querySelector("[data-schedule]");
    const autoload = root && root.querySelector("[data-schedule-autoload]");
    if (!autoload) {
        return;
    }

    const ENDPOINT = "/projects/schedule/weeks";
    const WEEKS_PER_LOAD = 2;
    const host = root.querySelector("[data-schedule-weeks]");
    const button = autoload.querySelector("[data-schedule-autoload-button]");
    const spinner = autoload.querySelector("[data-schedule-autoload-spinner]");
    const statusOutput = root.querySelector("[data-schedule-status]");
    let loading = false;

    function setStatus(message) {
        if (!statusOutput) {
            return;
        }
        statusOutput.textContent = message;
        statusOutput.className = "schedule-status schedule-status-danger";
        window.setTimeout(() => {
            statusOutput.textContent = "";
            statusOutput.className = "schedule-status";
        }, 4000);
    }

    function loadMore() {
        const from = autoload.dataset.nextFrom;
        if (loading || !from) {
            return;
        }
        loading = true;
        spinner.hidden = false;
        button.disabled = true;

        const url = `${ENDPOINT}?from=${encodeURIComponent(from)}&weeks=${WEEKS_PER_LOAD}`;
        fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(async (response) => {
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.message || "Could not load more weeks.");
                }
                return payload;
            })
            .then((payload) => {
                host.insertAdjacentHTML("beforeend", payload.html);
                if (payload.next_from) {
                    autoload.dataset.nextFrom = payload.next_from;
                } else {
                    // A year ahead: nothing further is worth a sheet.
                    autoload.remove();
                }
            })
            .catch((error) => setStatus(error.message))
            .finally(() => {
                loading = false;
                spinner.hidden = true;
                button.disabled = false;
            });
    }

    button.addEventListener("click", loadMore);
})();
