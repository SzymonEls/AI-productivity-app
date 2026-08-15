/**
 * Seven-day session planner.
 *
 * Opened from anything carrying [data-plan-session] (the dashboard slots, the
 * "not scheduled" list, the project page). Renders a day x slot grid and books
 * a free slot without leaving the page.
 *
 * Freeing a block used to live here too. It moved to schedule-board.js, the only
 * page with those buttons, because emptying a block in place keeps edit mode -
 * the reload this module does after booking would end it.
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
                <p class="planner-note" data-planner-note hidden></p>
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

    /**
     * Where the project already stands, said once above the grid.
     *
     * The rule blocks whole days at a time, so this used to be printed inside a
     * day row - next to an arbitrary date, reading as if that one day were the
     * problem. The server sends it as a single line instead.
     */
    function setNote(text) {
        const note = ensureDialog().querySelector("[data-planner-note]");
        note.textContent = text || "";
        note.hidden = !text;
    }

    function renderGrid(payload) {
        const grid = ensureDialog().querySelector("[data-planner-grid]");
        grid.innerHTML = "";
        setNote(payload.note);

        payload.days.forEach((day) => {
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
                // Same colour language as the A/B/C cards on the home page: amber
                // for a booked block, grey for the spare C, green once the session
                // is done, and dashed grey while the block is still free.
                cell.className = "planner-slot";
                if (slot.is_optional) {
                    cell.classList.add("planner-slot-optional");
                }

                const letter = document.createElement("span");
                letter.className = "planner-slot-letter";
                letter.textContent = slot.slot;
                cell.appendChild(letter);

                if (slot.project_id) {
                    cell.classList.add("planner-slot-taken");
                    if (slot.is_done) {
                        cell.classList.add("planner-slot-done");
                    }
                    if (slot.is_this_project) {
                        cell.classList.add("planner-slot-mine");
                    }

                    const name = document.createElement("span");
                    name.className = "planner-slot-name";
                    name.textContent = slot.project_title;
                    cell.appendChild(name);

                    const remove = document.createElement("button");
                    remove.type = "button";
                    remove.className = "planner-slot-remove";
                    remove.innerHTML = "&times;";
                    remove.title = `Free block ${slot.slot}`;
                    remove.setAttribute(
                        "aria-label",
                        `Remove ${slot.project_title} from block ${slot.slot} on ${day.label}`
                    );
                    remove.addEventListener("click", () => releaseSlot(day.date, slot.slot));
                    cell.appendChild(remove);
                } else if (slot.can_take) {
                    cell.classList.add("planner-slot-free");
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
            grid.appendChild(row);
        });
    }

    function takeSlot(date, slot) {
        setStatus("Saving…", "");
        postJson(SLOT_ENDPOINTS.assign, { project_id: currentProjectId, date, slot })
            .then((payload) => {
                renderGrid(payload);
                setStatus(payload.message, "success");
                // The dashboard, the switcher and the schedule page all read
                // from the server, so refresh once the user closes the dialog.
                dialog.dataset.dirty = "true";
            })
            .catch((error) => setStatus(error.message, "danger"));
    }

    /**
     * Free a block from inside the dialog.
     *
     * Any booked block can go, not just this project's own: the grid shows the
     * whole week, and "that Tuesday belongs to something else" is exactly the
     * thing you want to undo while planning. The endpoint answers with a fresh
     * window when it knows which project the dialog is about, so the grid can be
     * redrawn without closing it.
     */
    function releaseSlot(date, slot) {
        setStatus("Removing…", "");
        postJson(SLOT_ENDPOINTS.clear, { date, slot, project_id: currentProjectId })
            .then((payload) => {
                if (payload.days) {
                    renderGrid(payload);
                }
                setStatus(payload.message, "success");
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
        element.querySelector("[data-planner-note]").hidden = true;
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
        element.querySelector("[data-planner-note]").hidden = true;
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
                renderGrid(payload);
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
        }
    });
})();
