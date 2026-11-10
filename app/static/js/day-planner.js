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
    // What to do once a session has been booked from the planner: set when
    // the planner was opened to plan the next session before ending today's,
    // so booking one goes straight on to marking today's done or failed.
    let afterBook = null;

    /**
     * Ask before booking a session past its project's deadline.
     *
     * A deadline warns rather than refuses, but the warning comes as a question
     * before anything is sent: a late booking made by accident should never
     * need undoing. The server checks the same rule and would warn again, so
     * once this says yes the answer is reported as a plain success.
     */
    function confirmLate(title, deadlineLabel, dayLabel) {
        return window.confirm(
            `The session deadline for ${title} is ${deadlineLabel}.\n\nPlan it for ${dayLabel} anyway?`
        );
    }

    // "2026-10-16" as the server spells a day: "16 Oct".
    function shortDate(iso) {
        return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    }

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
                const error = new Error(payload.message || "Could not update the schedule.");
                // The server's "plan the next session first" - answered with a
                // question rather than an alert.
                error.needsNextSession = Boolean(payload.needs_next_session);
                throw error;
            }
            return payload;
        });
    }

    /**
     * The question before today's session ends with nothing planned after it.
     *
     * Ending it - done or failed - needs the next session booked, or a
     * deliberate "leave it unplanned". Resolves to "plan", "skip" or null for
     * cancel. Built once, in the planner's own dialog frame.
     */
    let gate = null;
    function askNextSession(kind) {
        if (!gate) {
            gate = document.createElement("div");
            gate.className = "planner-backdrop";
            gate.hidden = true;
            gate.innerHTML = `
                <div class="planner-dialog" role="dialog" aria-modal="true" aria-labelledby="nextSessionGateTitle">
                    <header class="planner-header">
                        <h2 class="h6 mb-0" id="nextSessionGateTitle">No next session planned</h2>
                        <button type="button" class="icon-button" data-gate-answer="" aria-label="Close">&times;</button>
                    </header>
                    <p class="next-session-gate-text" data-gate-text></p>
                    <div class="next-session-gate-actions">
                        <button type="button" class="btn btn-outline-secondary btn-sm" data-gate-answer="">Cancel</button>
                        <button type="button" class="btn btn-outline-danger btn-sm" data-gate-answer="skip" data-gate-skip></button>
                        <button type="button" class="btn btn-primary btn-sm" data-gate-answer="plan">Plan next session</button>
                    </div>
                </div>
            `;
            document.body.appendChild(gate);
        }

        const verb = kind === "failed" ? "failed" : "done";
        gate.querySelector("[data-gate-text]").textContent =
            `Before marking today's session ${verb}, plan the next one - or leave it unplanned on purpose.`;
        gate.querySelector("[data-gate-skip]").textContent = `Skip planning, mark ${verb}`;
        gate.hidden = false;
        gate.querySelector('[data-gate-answer="plan"]').focus();

        return new Promise((resolve) => {
            const finish = (answer) => {
                gate.hidden = true;
                gate.removeEventListener("click", onClick);
                document.removeEventListener("keydown", onKey);
                resolve(answer);
            };
            const onClick = (event) => {
                if (event.target === gate) {
                    finish(null);
                    return;
                }
                const button = event.target.closest("[data-gate-answer]");
                if (button) {
                    finish(button.dataset.gateAnswer || null);
                }
            };
            const onKey = (event) => {
                if (event.key === "Escape") {
                    finish(null);
                }
            };
            gate.addEventListener("click", onClick);
            document.addEventListener("keydown", onKey);
        });
    }

    /**
     * End today's session (done or failed) through the next-session question.
     *
     * ``send(skipNext)`` posts the change. Tried first as it is: with a session
     * already booked after today the server just agrees. When it answers that
     * the next session is missing, the question decides - plan one (the
     * planner opens, and booking a block there sends the change after it), or
     * skip on purpose (sent again with skip_next).
     */
    function endSession(kind, button, send, onDone) {
        button.disabled = true;
        return send(false)
            .then(onDone)
            .catch(async (error) => {
                if (!error.needsNextSession) {
                    window.alert(error.message);
                    return;
                }
                const answer = await askNextSession(kind);
                if (answer === "skip") {
                    return send(true).then(onDone).catch((again) => window.alert(again.message));
                }
                if (answer === "plan") {
                    afterBook = () => send(false).then(() => window.location.reload());
                    openPlanner(button.dataset.projectId, button.dataset.projectTitle);
                }
            })
            .finally(() => {
                button.disabled = false;
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
            row.className = `planner-day${day.is_today ? " planner-day-today" : ""}${
                day.after_deadline ? " planner-day-late" : ""
            }`;

            const label = document.createElement("div");
            label.className = "planner-day-label";
            label.textContent = day.is_today ? `${day.label} · today` : day.label;
            // Still bookable: the deadline asks first, it does not refuse.
            if (day.after_deadline) {
                label.title = `After the session deadline (${payload.deadline_label})`;
            }
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
                    button.addEventListener("click", () => {
                        if (
                            day.after_deadline &&
                            !confirmLate(payload.project_title, payload.deadline_label, shortDate(day.date))
                        ) {
                            return;
                        }
                        takeSlot(day.date, slot.slot);
                    });
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
                // Opened to plan the next session before ending today's: now
                // there is one, so today's is ended and the page reloaded.
                if (afterBook) {
                    const then = afterBook;
                    afterBook = null;
                    setStatus(`${payload.message} Marking today's session…`, "success");
                    then().catch((error) => setStatus(error.message, "danger"));
                }
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
                row.addEventListener("click", () => {
                    if (
                        project.deadline_warning &&
                        !confirmLate(project.title, project.deadline_label, shortDate(date))
                    ) {
                        return;
                    }
                    takeSlotFor(project.id, date, slot);
                });
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
                ? (project.is_private && document.documentElement.getAttribute("data-safe-mode") === "on"
                    ? project.last_session
                    : project.plan_heading || project.last_session)
                : project.reason;
            text.appendChild(note);

            if (project.can_take && project.deadline_warning) {
                const late = document.createElement("span");
                late.className = "picker-row-deadline";
                late.textContent = project.deadline_warning;
                text.appendChild(late);
            }

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
        // Closing without booking leaves today's session as it was.
        afterBook = null;
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
            const applyDone = (payload) => {
                doneButton.dataset.done = payload.is_done ? "1" : "0";
                doneButton.classList.toggle("btn-success", payload.is_done);
                doneButton.classList.toggle("btn-outline-secondary", !payload.is_done);
                doneButton.querySelector("[data-session-done-label]").textContent =
                    payload.is_done ? "Done" : "Mark done";
                // A session done meets the deadline, and the server has just
                // cleared it - the badge saying otherwise goes too. It also
                // ends a failed session and the project being problematic,
                // which the page draws in several places, and moves the plan
                // button on from today's session, so then it is simpler to
                // load the page again.
                if (payload.is_done) {
                    window.location.reload();
                }
            };
            if (!next) {
                // Reopening needs no next session.
                doneButton.disabled = true;
                postJson(`/projects/${doneButton.dataset.projectId}/session-done`, { done: 0 })
                    .then(applyDone)
                    .catch((error) => window.alert(error.message))
                    .finally(() => {
                        doneButton.disabled = false;
                    });
                return;
            }
            endSession(
                "done",
                doneButton,
                (skipNext) =>
                    postJson(`/projects/${doneButton.dataset.projectId}/session-done`, {
                        done: 1,
                        skip_next: skipNext ? 1 : 0,
                    }),
                applyDone
            );
            return;
        }

        // The ⋯ menu's alternative to done. Failing it marks the project
        // problematic - a banner and a switch the server draws - so the page
        // is loaded again rather than patched.
        const failedButton = event.target.closest("[data-session-failed]");
        if (failedButton) {
            event.preventDefault();
            const next = failedButton.dataset.failed === "1" ? 0 : 1;
            if (!next) {
                failedButton.disabled = true;
                postJson(`/projects/${failedButton.dataset.projectId}/session-failed`, { failed: 0 })
                    .then(() => window.location.reload())
                    .catch((error) => {
                        window.alert(error.message);
                        failedButton.disabled = false;
                    });
                return;
            }
            if (!window.confirm("Mark today's session as failed? The project will be marked problematic until a session of it is done.")) {
                return;
            }
            endSession(
                "failed",
                failedButton,
                (skipNext) =>
                    postJson(`/projects/${failedButton.dataset.projectId}/session-failed`, {
                        failed: 1,
                        skip_next: skipNext ? 1 : 0,
                    }),
                () => window.location.reload()
            );
            return;
        }

        const emptySlot = event.target.closest("[data-fill-slot]");
        if (emptySlot) {
            event.preventDefault();
            openSlotPicker(emptySlot.dataset.date, emptySlot.dataset.slot);
        }
    });
})();
