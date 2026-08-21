/**
 * The archive's one live control: ticking a past session off.
 *
 * Everything else on the page is a record - a day that has been cannot be
 * booked, moved or freed - but whether a session happened is decided on the day
 * and often only remembered later, so the ✓ on a booked block stays clickable
 * here. The block is flipped on the page first and the request follows, the way
 * the schedule board does it, so a refused change puts itself back.
 */
(function () {
    "use strict";

    const root = document.querySelector("[data-schedule-archive]");
    if (!root) {
        return;
    }

    const DONE_ENDPOINT = "/projects/schedule/session-done";
    const statusOutput = root.querySelector("[data-archive-status]");
    let statusTimer = null;

    function setStatus(message, tone) {
        window.clearTimeout(statusTimer);
        statusOutput.textContent = message || "";
        statusOutput.className = `schedule-status${tone ? ` schedule-status-${tone}` : ""}`;
        if (message) {
            statusTimer = window.setTimeout(() => setStatus("", ""), 4000);
        }
    }

    /* Mirrors what the template renders for a done block, so a ticked session
       looks the same whether the page drew it or a click did. */
    function paint(button, done) {
        button.dataset.done = done ? "1" : "0";
        button.setAttribute("aria-pressed", done ? "true" : "false");
        button.title = done ? "Session done — click to reopen" : "Mark this session done";
        button.closest(".day-slot").classList.toggle("is-done", done);
    }

    root.addEventListener("click", (event) => {
        const button = event.target.closest("[data-toggle-done]");
        if (!button) {
            return;
        }
        event.preventDefault();

        const wasDone = button.dataset.done === "1";
        paint(button, !wasDone);
        button.disabled = true;

        fetch(DONE_ENDPOINT, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({
                date: button.dataset.date,
                slot: button.dataset.slot,
                done: wasDone ? 0 : 1,
            }),
        })
            .then(async (response) => {
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.message || "Could not update the session.");
                }
                paint(button, payload.is_done);
                setStatus(payload.message, "success");
            })
            .catch((error) => {
                paint(button, wasDone);
                setStatus(error.message, "danger");
            })
            .finally(() => {
                button.disabled = false;
            });
    });
})();
