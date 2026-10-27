/**
 * Today's mood on the home page: the button beside "Inbox", the dialog it
 * opens, and the mood ring in System health.
 *
 * Picking a number posts it straight away (POST /mood) and closes the dialog.
 * The day has one rating, so picking again later rewrites it; the server
 * answers with the week's new average, which is redrawn into the ring here
 * rather than waiting for a reload.
 */
(function () {
    "use strict";

    const ENDPOINT = "/mood";

    const modal = document.getElementById("moodModal");
    const options = modal ? Array.from(modal.querySelectorAll("[data-mood-score]")) : [];
    if (!modal || !options.length) {
        return;
    }

    const status = modal.querySelector("[data-mood-status]");
    const openButton = document.querySelector("[data-mood-open]");
    const buttonText = openButton?.querySelector("[data-mood-button-text]");
    const buttonDot = openButton?.querySelector(".mood-button-dot");
    const summary = document.querySelector("[data-mood-summary]");

    let pending = false;

    function setStatus(message) {
        if (status) {
            status.textContent = message || "";
        }
    }

    function markSelected(score) {
        options.forEach((option) => {
            const selected = Number(option.dataset.moodScore) === score;
            option.classList.toggle("is-selected", selected);
            option.setAttribute("aria-checked", selected ? "true" : "false");
        });
    }

    function updateButton(score) {
        if (buttonText) {
            buttonText.textContent = `Mood ${score}`;
        }
        buttonDot?.classList.remove("is-empty");
        openButton?.setAttribute("aria-label", `Today's mood: ${score} out of 5. Change it`);
    }

    function updateSummary(data) {
        if (!summary || !data) {
            return;
        }
        const ring = summary.querySelector("[data-mood-ring]");
        const average = summary.querySelector("[data-mood-average]");
        const days = summary.querySelector("[data-mood-days]");
        const gauge = summary.querySelector("[data-mood-gauge]");
        const hasAverage = data.average !== null && data.average !== undefined;

        if (ring) {
            ring.hidden = !hasAverage;
            ring.style.strokeDasharray = `${data.percent} 100`;
        }
        if (average) {
            average.textContent = hasAverage ? data.average.toFixed(1) : "–";
        }
        if (days) {
            days.textContent = `${data.rated_days} / ${data.window_days} days`;
        }
        gauge?.setAttribute(
            "aria-label",
            hasAverage ? `Average mood ${data.average.toFixed(1)} out of 5` : `No mood rated in the last ${data.window_days} days`
        );
    }

    function rate(score) {
        if (pending) {
            return;
        }
        pending = true;
        setStatus("");
        options.forEach((option) => (option.disabled = true));

        fetch(ENDPOINT, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({ score }),
        })
            .then(async (response) => {
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.message || "Could not save the mood.");
                }
                return payload;
            })
            .then((payload) => {
                markSelected(payload.score);
                updateButton(payload.score);
                updateSummary(payload.summary);
                window.bootstrap?.Modal.getOrCreateInstance(modal).hide();
            })
            .catch((error) => setStatus(error.message))
            .finally(() => {
                pending = false;
                options.forEach((option) => (option.disabled = false));
            });
    }

    options.forEach((option) => {
        option.addEventListener("click", () => rate(Number(option.dataset.moodScore)));
    });

    // A failure from the last attempt is not news the next time it opens.
    modal.addEventListener("show.bs.modal", () => setStatus(""));
})();
