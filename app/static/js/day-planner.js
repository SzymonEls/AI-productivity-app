/**
 * Seven-day session planner.
 *
 * Opened from anything carrying [data-plan-session] (the dashboard slots, the
 * "not scheduled" list, the project page). Renders a day x slot grid and books
 * a free slot without leaving the page.
 *
 * Also wires [data-clear-slot] buttons on the schedule page, which share the
 * same endpoint.
 */
(function () {
    "use strict";

    const SLOT_ENDPOINTS = {
        window: (projectId) => `/projects/${projectId}/schedule-window`,
        candidates: (date, slot) =>
            `/projects/schedule/candidates?date=${encodeURIComponent(date)}&slot=${encodeURIComponent(slot)}`,
        assign: "/projects/schedule/assign",
        clear: "/projects/schedule/clear",
    };

    let dialog = null;
    let currentProjectId = null;

    function getJson(url) {
        return fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(async (response) => {
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "Could not load the schedule.");
            }
            return payload;
        });
    }

    function postJson(url, body) {
        return fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify(body),
        }).then(async (response) => {
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "Could not update the schedule.");
            }
            return payload;
        });
    }

    function buildDialog() {
        const element = document.createElement("div");
        element.className = "planner-backdrop";
        element.hidden = true;
        element.innerHTML = `
            <div class="planner-dialog" role="dialog" aria-modal="true" aria-labelledby="plannerTitle">
                <header class="planner-header">
                    <h2 class="h6 mb-0" id="plannerTitle">Plan next session</h2>
                    <button type="button" class="icon-button" data-planner-close aria-label="Close">&times;</button>
                </header>
                <p class="planner-status" data-planner-status role="status"></p>
                <div class="planner-grid" data-planner-grid></div>
            </div>
        `;
        document.body.appendChild(element);

        element.addEventListener("click", (event) => {
            if (event.target === element || event.target.closest("[data-planner-close]")) {
                closeDialog();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !element.hidden) {
                closeDialog();
            }
        });
        return element;
    }

    function ensureDialog() {
        if (!dialog) {
            dialog = buildDialog();
        }
        return dialog;
    }

    function setStatus(message, tone) {
        const status = ensureDialog().querySelector("[data-planner-status]");
        status.textContent = message || "";
        status.className = `planner-status${tone ? ` planner-status-${tone}` : ""}`;
    }

    function renderGrid(days) {
        const grid = ensureDialog().querySelector("[data-planner-grid]");
        grid.innerHTML = "";
        // The same reason applies to every day once both blocks are used, so it
        // is printed on the first day it appears rather than seven times.
        let lastReason = "";

        days.forEach((day) => {
            const row = document.createElement("div");
            row.className = `planner-day${day.is_today ? " planner-day-today" : ""}`;

            const label = document.createElement("div");
            label.className = "planner-day-label";
            label.textContent = day.is_today ? `${day.label} · today` : day.label;
            row.appendChild(label);

            const slots = document.createElement("div");
            slots.className = "planner-day-slots";

            day.slots.forEach((slot) => {
                const cell = document.createElement("div");
                cell.className = "planner-slot";

                const letter = document.createElement("span");
                letter.className = "planner-slot-letter";
                letter.textContent = slot.slot;
                cell.appendChild(letter);

                if (slot.project_id) {
                    cell.classList.add("planner-slot-taken");
                    if (slot.is_this_project) {
                        cell.classList.add("planner-slot-mine");
                    }
                    const name = document.createElement("span");
                    name.className = "planner-slot-name";
                    name.textContent = slot.project_title;
                    cell.appendChild(name);
                } else if (slot.can_take) {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "btn btn-outline-secondary btn-sm planner-take";
                    button.textContent = "Take";
                    button.addEventListener("click", () => takeSlot(day.date, slot.slot));
                    cell.appendChild(button);
                } else {
                    cell.classList.add("planner-slot-blocked");
                    const note = document.createElement("span");
                    note.className = "planner-slot-name";
                    note.textContent = "—";
                    cell.appendChild(note);
                }

                slots.appendChild(cell);
            });

            row.appendChild(slots);

            if (day.blocked_reason && day.blocked_reason !== lastReason) {
                const reason = document.createElement("div");
                reason.className = "planner-day-reason";
                reason.textContent = day.blocked_reason;
                row.appendChild(reason);
            }
            lastReason = day.blocked_reason;

            grid.appendChild(row);
        });
    }

    function takeSlot(date, slot) {
        setStatus("Saving…", "");
        postJson(SLOT_ENDPOINTS.assign, { project_id: currentProjectId, date, slot })
            .then((payload) => {
                renderGrid(payload.days);
                setStatus(payload.message, "success");
                // The dashboard, the switcher and the schedule page all read
                // from the server, so refresh once the user closes the dialog.
                dialog.dataset.dirty = "true";
            })
            .catch((error) => setStatus(error.message, "danger"));
    }

    function renderCandidates(projects, date, slot) {
        const grid = ensureDialog().querySelector("[data-planner-grid]");
        grid.innerHTML = "";

        if (!projects.length) {
            setStatus("You have no active projects yet.", "");
            return;
        }

        const list = document.createElement("div");
        list.className = "picker-list";

        projects.forEach((project) => {
            const row = document.createElement(project.can_take ? "button" : "div");
            row.className = `picker-row${project.can_take ? "" : " picker-row-blocked"}`;
            if (project.can_take) {
                row.type = "button";
                row.addEventListener("click", () => takeSlotFor(project.id, date, slot));
            }

            const text = document.createElement("span");
            text.className = "picker-row-text";

            const title = document.createElement("span");
            title.className = "picker-row-title";
            title.textContent = project.title;
            if (project.is_starred) {
                const star = document.createElement("span");
                star.className = "switcher-badge";
                star.setAttribute("aria-hidden", "true");
                star.textContent = "★";
                title.appendChild(star);
            }
            text.appendChild(title);

            const note = document.createElement("span");
            note.className = "picker-row-note";
            note.textContent = project.can_take
                ? project.plan_heading || project.last_session
                : project.reason;
            text.appendChild(note);

            row.appendChild(text);
            list.appendChild(row);
        });

        grid.appendChild(list);
    }

    function takeSlotFor(projectId, date, slot) {
        setStatus("Saving…", "");
        postJson(SLOT_ENDPOINTS.assign, { project_id: projectId, date, slot })
            .then(() => window.location.reload())
            .catch((error) => setStatus(error.message, "danger"));
    }

    function openSlotPicker(date, slot) {
        const element = ensureDialog();
        element.hidden = false;
        delete element.dataset.dirty;
        element.querySelector("#plannerTitle").textContent = `Choose a project for slot ${slot}`;
        element.querySelector("[data-planner-grid]").innerHTML = "";
        setStatus("Loading…", "");

        getJson(SLOT_ENDPOINTS.candidates(date, slot))
            .then((payload) => {
                renderCandidates(payload.projects, payload.date, payload.slot);
                setStatus("", "");
            })
            .catch((error) => setStatus(error.message, "danger"));
    }

    function openPlanner(projectId, projectTitle) {
        currentProjectId = projectId;
        const element = ensureDialog();
        element.hidden = false;
        delete element.dataset.dirty;
        element.querySelector("#plannerTitle").textContent = projectTitle
            ? `Plan next session · ${projectTitle}`
            : "Plan next session";
        element.querySelector("[data-planner-grid]").innerHTML = "";
        setStatus("Loading…", "");

        fetch(SLOT_ENDPOINTS.window(projectId), {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        })
            .then(async (response) => {
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.message || "Could not load the schedule.");
                }
                return payload;
            })
            .then((payload) => {
                renderGrid(payload.days);
                setStatus("", "");
            })
            .catch((error) => setStatus(error.message, "danger"));
    }

    function closeDialog() {
        if (!dialog) {
            return;
        }
        dialog.hidden = true;
        if (dialog.dataset.dirty === "true") {
            window.location.reload();
        }
    }

    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-plan-session]");
        if (trigger) {
            event.preventDefault();
            openPlanner(trigger.dataset.projectId, trigger.dataset.projectTitle);
            return;
        }

        const doneButton = event.target.closest("[data-session-done]");
        if (doneButton) {
            event.preventDefault();
            const next = doneButton.dataset.done === "1" ? 0 : 1;
            doneButton.disabled = true;
            postJson(`/projects/${doneButton.dataset.projectId}/session-done`, { done: next })
                .then((payload) => {
                    doneButton.dataset.done = payload.is_done ? "1" : "0";
                    doneButton.classList.toggle("btn-success", payload.is_done);
                    doneButton.classList.toggle("btn-outline-secondary", !payload.is_done);
                    doneButton.querySelector("[data-session-done-label]").textContent =
                        payload.is_done ? "Done" : "Mark done";
                })
                .catch((error) => window.alert(error.message))
                .finally(() => {
                    doneButton.disabled = false;
                });
            return;
        }

        const emptySlot = event.target.closest("[data-fill-slot]");
        if (emptySlot) {
            event.preventDefault();
            openSlotPicker(emptySlot.dataset.date, emptySlot.dataset.slot);
            return;
        }

        const clearButton = event.target.closest("[data-clear-slot]");
        if (!clearButton) {
            return;
        }
        event.preventDefault();
        clearButton.disabled = true;
        postJson(SLOT_ENDPOINTS.clear, {
            date: clearButton.dataset.date,
            slot: clearButton.dataset.slot,
        })
            .then(() => window.location.reload())
            .catch((error) => {
                clearButton.disabled = false;
                window.alert(error.message);
            });
    });
})();
