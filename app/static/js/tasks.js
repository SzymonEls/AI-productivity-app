/**
 * Tasks, wherever they are on the page: the Tasks page, the sheets on the
 * schedule and in the archive, and today's box on the home page.
 *
 * One script for all of them because a task is the same thing on each and is
 * edited the same way: the circle ticks it off, clicking the text rewrites it
 * where it stands (Enter keeps it, Escape puts it back), and the ⋯ - or a right
 * click, or a long press on a phone - opens a menu that moves it to today,
 * tomorrow, the day after, the weekend, next week or any day picked, takes its
 * day away, sets it repeating, or deletes it.
 *
 * A repeating task is one row. Ticking it off is answered with the next
 * occurrence the server has just written ("next"), which is placed like any
 * moved task; taking the tick back is answered with the id of the one it
 * removed again ("removed_id").
 *
 * Every change is applied to the page first and posted afterwards, the way the
 * day notes and the board do it, and a refused one puts itself back. Where a
 * moved task lands depends on the page: the Tasks page keeps the whole list in
 * memory and redraws its groups, while a page of day sheets looks for the sheet
 * of the new day and takes the row off this one - a task moved past the edge of
 * the schedule simply leaves it.
 *
 * buildTask() mirrors task_row() in templates/tasks/_tasks.html. Change one,
 * change the other.
 */
(function () {
    "use strict";

    const todayHost = document.querySelector("[data-tasks-today]");
    if (!todayHost) {
        return;
    }

    const ENDPOINT = "/tasks";
    const TODAY = parseIso(todayHost.dataset.tasksToday);
    const TODAY_ISO = toIso(TODAY);
    const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const CHECK_ICON =
        '<svg class="app-icon " width="12" height="12" viewBox="0 0 24 24" fill="none"' +
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"' +
        ' aria-hidden="true" focusable="false"><path d="M20 6 9 17l-5-5"/></svg>';
    const MORE_ICON =
        '<svg class="app-icon " width="16" height="16" viewBox="0 0 24 24" fill="none"' +
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"' +
        ' aria-hidden="true" focusable="false"><circle cx="5" cy="12" r="1"/>' +
        '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>';
    // Mirrors REPEAT_RULES in app/tasks/routes.py - change both together.
    const REPEAT_LABELS = {
        daily: "Every day",
        weekdays: "Every weekday",
        weekly: "Every week",
        biweekly: "Every 2 weeks",
        monthly: "Every month",
        yearly: "Every year",
    };
    const REPEAT_ICON =
        '<svg class="app-icon " width="12" height="12" viewBox="0 0 24 24" fill="none"' +
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"' +
        ' aria-hidden="true" focusable="false"><path d="m17 2 4 4-4 4"/>' +
        '<path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/>' +
        '<path d="M21 13v1a4 4 0 0 1-4 4H3"/></svg>';
    const PLUS_ICON =
        '<svg class="app-icon " width="12" height="12" viewBox="0 0 24 24" fill="none"' +
        ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"' +
        ' aria-hidden="true" focusable="false"><path d="M12 5v14M5 12h14"/></svg>';

    // The Tasks page holds the whole list and draws it; every other page only
    // has rows the server rendered.
    const page = document.querySelector("[data-tasks-page]");
    const groupsHost = page ? page.querySelector("[data-task-groups]") : null;
    let tasks = page ? JSON.parse(page.querySelector("[data-tasks-json]").textContent) : null;
    const maxLength = Number(
        document.querySelector("[data-task-input], [data-task-quick-title]")?.maxLength || 300
    );

    /* ---------------------------------------------------------------- dates */

    function parseIso(value) {
        const [year, month, day] = value.split("-").map(Number);
        return new Date(year, month - 1, day);
    }

    function toIso(date) {
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${date.getFullYear()}-${month}-${day}`;
    }

    function addDays(date, days) {
        return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
    }

    /* "Thu 02 Oct", which is what strftime("%a %d %b") gives the template. */
    function dayLabel(iso) {
        const date = parseIso(iso);
        return `${WEEKDAYS[date.getDay()]} ${String(date.getDate()).padStart(2, "0")} ${MONTHS[date.getMonth()]}`;
    }

    /**
     * The quick moves, counted from the server's today.
     *
     * The weekend is the coming Saturday; on a Saturday or a Sunday that is
     * already the weekend being lived in, so it means the next one. Next week is
     * the coming Monday.
     */
    function quickChoices() {
        const weekday = TODAY.getDay();
        const inWeekend = weekday === 6 || weekday === 0;
        const toSaturday = inWeekend ? (weekday === 6 ? 7 : 6) : 6 - weekday;
        const toMonday = (8 - weekday) % 7 || 7;
        return [
            { label: "Today", date: TODAY_ISO },
            { label: "Tomorrow", date: toIso(addDays(TODAY, 1)) },
            { label: "Day after tomorrow", date: toIso(addDays(TODAY, 2)) },
            { label: inWeekend ? "Next weekend" : "This weekend", date: toIso(addDays(TODAY, toSaturday)) },
            { label: "Next week", date: toIso(addDays(TODAY, toMonday)) },
        ];
    }

    /* --------------------------------------------------------------- status */

    const statusOutput = document.querySelector(
        "[data-task-status], [data-schedule-status], [data-archive-status]"
    );
    let statusTimer = null;

    function setStatus(message, tone) {
        if (!statusOutput) {
            return;
        }
        window.clearTimeout(statusTimer);
        statusOutput.textContent = message || "";
        statusOutput.className = `schedule-status${tone ? ` schedule-status-${tone}` : ""}`;
        if (message) {
            statusTimer = window.setTimeout(() => setStatus("", ""), 4000);
        }
    }

    function postJson(url, body, fallbackMessage) {
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
                throw new Error(payload.message || fallbackMessage);
            }
            return payload;
        });
    }

    /* ----------------------------------------------------------------- rows */

    function buildTask(task, listDate) {
        const item = document.createElement("li");
        item.className = `task${task.is_done ? " is-done" : ""}`;
        item.setAttribute("data-task", "");
        if (task.id) {
            item.dataset.taskId = task.id;
        }
        item.dataset.due = task.due_date || "";
        item.dataset.done = task.is_done ? "1" : "0";
        item.dataset.repeat = task.repeat || "";

        const check = document.createElement("button");
        check.type = "button";
        check.className = "task-check";
        check.setAttribute("data-task-toggle", "");
        check.setAttribute("role", "checkbox");
        check.setAttribute("aria-checked", task.is_done ? "true" : "false");
        check.setAttribute("aria-label", `Done: ${task.title}`);
        check.innerHTML = CHECK_ICON;

        const title = document.createElement("button");
        title.type = "button";
        title.className = "task-title";
        title.setAttribute("data-task-title", "");
        title.title = "Click to edit";
        title.textContent = task.title;

        item.append(check, title);

        if (task.repeat) {
            const repeat = document.createElement("span");
            repeat.className = "task-repeat";
            repeat.setAttribute("data-task-repeat", "");
            repeat.setAttribute("role", "img");
            const label = `Repeats: ${(REPEAT_LABELS[task.repeat] || task.repeat).toLowerCase()}`;
            repeat.title = label;
            repeat.setAttribute("aria-label", label);
            repeat.innerHTML = REPEAT_ICON;
            item.append(repeat);
        }

        if (task.due_date && task.due_date !== (listDate || null)) {
            const due = document.createElement("span");
            due.className = `task-due${!task.is_done && task.due_date < TODAY_ISO ? " is-overdue" : ""}`;
            due.setAttribute("data-task-due", "");
            due.textContent = dayLabel(task.due_date);
            item.append(due);
        }

        const menuButton = document.createElement("button");
        menuButton.type = "button";
        menuButton.className = "icon-button task-menu-button";
        menuButton.setAttribute("data-task-menu", "");
        menuButton.setAttribute("aria-haspopup", "menu");
        menuButton.title = "Move or delete";
        menuButton.setAttribute("aria-label", `Options for ${task.title}`);
        menuButton.innerHTML = MORE_ICON;
        item.append(menuButton);

        return item;
    }

    function rowOf(element) {
        return element.closest("[data-task]");
    }

    function listDateOf(row) {
        return row.closest("[data-task-list]")?.dataset.date || null;
    }

    /* What the page knows about a row: off the model on the Tasks page, off the
       row's own attributes everywhere else. */
    function taskOf(row) {
        const id = Number(row.dataset.taskId);
        if (tasks) {
            const found = tasks.find((task) => task.id === id);
            if (found) {
                return { ...found };
            }
        }
        return {
            id,
            title: row.querySelector("[data-task-title]").textContent,
            due_date: row.dataset.due || null,
            is_done: row.dataset.done === "1",
            repeat: row.dataset.repeat || null,
        };
    }

    /* The list a task belongs in on a page of day sheets: its own day's, or -
       on the home page - today's when its day has gone and it is still open.
       None when the page does not show that day at all. */
    function listFor(task) {
        if (!task.due_date) {
            return null;
        }
        const exact = document.querySelector(`[data-task-list][data-date="${task.due_date}"]`);
        if (exact) {
            return exact;
        }
        if (!task.is_done && task.due_date < TODAY_ISO) {
            return document.querySelector("[data-task-list][data-accepts-overdue]");
        }
        return null;
    }

    /* Still-open tasks above finished ones, each half in the order written. */
    function insertRow(list, row, task) {
        const items = list.querySelector("[data-task-items]");
        const firstDone = task.is_done ? null : items.querySelector(":scope > .is-done");
        items.insertBefore(row, firstDone);
    }

    function flash(row) {
        row.classList.remove("is-arrived");
        // Restart the animation if the row was flashed a moment ago.
        void row.offsetWidth;
        row.classList.add("is-arrived");
        window.setTimeout(() => row.classList.remove("is-arrived"), 1400);
    }

    /**
     * Put a task where it now belongs, after its day or its state changed.
     *
     * Returns the row now standing for it, if any, so the caller can hand the
     * focus back to it.
     */
    function place(row, task) {
        if (tasks) {
            upsert(task);
            render();
            const placed = groupsHost.querySelector(`[data-task-id="${task.id}"]`);
            if (placed) {
                flash(placed);
            }
            return placed;
        }

        const current = row?.closest("[data-task-list]");
        const target = listFor(task);
        if (target && target === current) {
            const fresh = buildTask(task, target.dataset.date);
            row.replaceWith(fresh);
            return fresh;
        }

        row?.remove();
        if (!target) {
            return null;
        }
        const fresh = buildTask(task, target.dataset.date);
        insertRow(target, fresh, task);
        flash(fresh);
        return fresh;
    }

    /* ---------------------------------------------------- the Tasks page */

    function upsert(task) {
        const index = tasks.findIndex((entry) => entry.id === task.id);
        if (index === -1) {
            tasks.push(task);
        } else {
            tasks[index] = task;
        }
    }

    function groupSection({ title, subtitle, date, items, addable, tone }) {
        const section = document.createElement("section");
        section.className = `task-group${tone ? ` task-group-${tone}` : ""}`;
        if (addable) {
            section.setAttribute("data-task-list", "");
            section.dataset.date = date || "";
        }

        const header = document.createElement("header");
        header.className = "task-group-header";
        const heading = document.createElement("h2");
        heading.className = "task-group-title";
        heading.textContent = title;
        header.append(heading);
        if (subtitle) {
            const sub = document.createElement("span");
            sub.className = "task-group-subtitle";
            sub.textContent = subtitle;
            header.append(sub);
        }
        const count = document.createElement("span");
        count.className = "task-group-count";
        count.setAttribute("data-task-count", "");
        count.textContent = items.length ? String(items.length) : "";
        header.append(count);
        section.append(header);

        const list = document.createElement("ul");
        list.className = "task-list";
        list.setAttribute("data-task-items", "");
        items.forEach((task) => list.append(buildTask(task, date || null)));
        section.append(list);

        if (addable) {
            const add = document.createElement("button");
            add.type = "button";
            add.className = "day-note-add task-add";
            add.setAttribute("data-task-add", "");
            add.innerHTML = `${PLUS_ICON}<span class="day-note-add-label">Task</span>`;
            add.title = date ? `Add a task to ${dayLabel(date)}` : "Add a task with no day";

            const editor = document.createElement("div");
            editor.className = "task-editor";
            editor.setAttribute("data-task-editor", "");
            editor.hidden = true;
            const input = document.createElement("input");
            input.type = "text";
            input.className = "day-note-input";
            input.setAttribute("data-task-input", "");
            input.maxLength = maxLength;
            input.placeholder = date ? `Task for ${dayLabel(date)}` : "Task with no day";
            input.setAttribute("aria-label", input.placeholder);
            editor.append(input);
            section.append(add, editor);
        }

        return section;
    }

    /* Overdue, today, every later day that has something on it, no day, and
       what is finished - in that order, which is the order they need doing. */
    function render() {
        const open = tasks.filter((task) => !task.is_done);
        const done = tasks.filter((task) => task.is_done);
        const byId = (a, b) => a.id - b.id;

        const overdue = open
            .filter((task) => task.due_date && task.due_date < TODAY_ISO)
            .sort((a, b) => a.due_date.localeCompare(b.due_date) || byId(a, b));
        const someday = open.filter((task) => !task.due_date).sort(byId);
        const byDay = new Map();
        open
            .filter((task) => task.due_date && task.due_date >= TODAY_ISO)
            .forEach((task) => {
                if (!byDay.has(task.due_date)) {
                    byDay.set(task.due_date, []);
                }
                byDay.get(task.due_date).push(task);
            });
        // Today always has a group, so there is always somewhere to add to.
        if (!byDay.has(TODAY_ISO)) {
            byDay.set(TODAY_ISO, []);
        }

        const tomorrowIso = toIso(addDays(TODAY, 1));
        const fragment = document.createDocumentFragment();

        if (overdue.length) {
            fragment.append(groupSection({ title: "Overdue", items: overdue, tone: "overdue" }));
        }
        [...byDay.keys()].sort().forEach((iso) => {
            let title = dayLabel(iso);
            let subtitle = "";
            if (iso === TODAY_ISO) {
                title = "Today";
                subtitle = dayLabel(iso);
            } else if (iso === tomorrowIso) {
                title = "Tomorrow";
                subtitle = dayLabel(iso);
            }
            fragment.append(
                groupSection({
                    title,
                    subtitle,
                    date: iso,
                    items: byDay.get(iso).sort(byId),
                    addable: true,
                })
            );
        });
        fragment.append(groupSection({ title: "No date", items: someday, addable: true }));

        if (done.length) {
            const details = document.createElement("details");
            details.className = "task-done-group";
            details.open = Boolean(groupsHost.querySelector(".task-done-group[open]"));
            const summary = document.createElement("summary");
            summary.textContent = `Completed (${done.length})`;
            details.append(summary, groupSection({ title: "Completed", items: done, tone: "done" }));
            fragment.append(details);
        }

        groupsHost.replaceChildren(fragment);
    }

    function refreshCounts() {
        if (!groupsHost) {
            return;
        }
        groupsHost.querySelectorAll(".task-group").forEach((group) => {
            const count = group.querySelectorAll("[data-task]").length;
            group.querySelector("[data-task-count]").textContent = count ? String(count) : "";
        });
    }

    /* ------------------------------------------------------- ticking off */

    function toggle(row) {
        if (!row.dataset.taskId) {
            return;
        }
        const before = taskOf(row);
        const after = { ...before, is_done: !before.is_done };

        // The circle answers at once; on the Tasks page the row then leaves for
        // Completed (or back to its day) a moment later, once the tick has been
        // seen.
        applyDone(row, after.is_done);
        if (tasks) {
            upsert(after);
            if (after.is_done) {
                // Newest finished first, which is how the server lists them.
                tasks = [after, ...tasks.filter((task) => task.id !== after.id)];
            }
            window.setTimeout(() => {
                const current = tasks.find((task) => task.id === after.id);
                if (current && current.is_done === after.is_done) {
                    render();
                }
            }, 450);
        }

        postJson(
            `${ENDPOINT}/${before.id}/update`,
            { is_done: after.is_done },
            "Could not save the task."
        )
            .then((payload) => {
                if (payload.next) {
                    placeOccurrence(payload.next);
                }
                if (payload.removed_id) {
                    dropTask(payload.removed_id);
                }
                setStatus(payload.message, "success");
            })
            .catch((error) => {
                if (tasks) {
                    upsert(before);
                    render();
                } else if (row.isConnected) {
                    applyDone(row, before.is_done);
                }
                setStatus(error.message, "danger");
            });
    }

    function applyDone(row, isDone) {
        row.classList.toggle("is-done", isDone);
        row.dataset.done = isDone ? "1" : "0";
        row.querySelector("[data-task-toggle]").setAttribute("aria-checked", isDone ? "true" : "false");
        row.querySelector("[data-task-due]")?.classList.toggle(
            "is-overdue",
            !isDone && Boolean(row.dataset.due) && row.dataset.due < TODAY_ISO
        );
    }

    /* The occurrence a tick has just written. It may already be on the page -
       ticking, unticking and ticking again hands back the same one - so any
       row standing for it goes first. */
    function placeOccurrence(task) {
        const existing = document.querySelector(`[data-task][data-task-id="${task.id}"]`);
        if (tasks) {
            upsert(task);
            render();
            return;
        }
        existing?.remove();
        place(null, task);
    }

    function dropTask(taskId) {
        if (tasks) {
            tasks = tasks.filter((task) => task.id !== taskId);
            render();
            return;
        }
        document.querySelector(`[data-task][data-task-id="${taskId}"]`)?.remove();
    }

    /* ------------------------------------------------- rewriting the text */

    function editTitle(titleButton) {
        finishEditing();
        const row = rowOf(titleButton);
        const input = document.createElement("input");
        input.type = "text";
        input.className = "day-note-input task-title-input";
        input.setAttribute("data-task-edit", "");
        input.maxLength = maxLength;
        input.value = titleButton.textContent;
        input.setAttribute("aria-label", `Edit the task “${titleButton.textContent}”`);

        titleButton.hidden = true;
        row.insertBefore(input, titleButton);
        input.focus();
        input.select();
    }

    function closeTitle(input) {
        rowOf(input).querySelector("[data-task-title]").hidden = false;
        input.remove();
    }

    function finishEditing() {
        document.querySelectorAll("[data-task-edit]").forEach(saveTitle);
    }

    function saveTitle(input) {
        const row = rowOf(input);
        const titleButton = row.querySelector("[data-task-title]");
        const previous = titleButton.textContent;
        const title = input.value.trim();

        closeTitle(input);
        // An emptied task is not a deleted one - that is what Delete is for.
        if (!title || title === previous) {
            return;
        }

        const before = taskOf(row);
        const after = { ...before, title };
        relabel(row, title);
        if (tasks) {
            upsert(after);
        }
        row.classList.add("is-pending");

        postJson(`${ENDPOINT}/${before.id}/update`, { title }, "Could not save the task.")
            .then((payload) => setStatus(payload.message, "success"))
            .catch((error) => {
                relabel(row, previous);
                if (tasks) {
                    upsert(before);
                }
                setStatus(error.message, "danger");
            })
            .finally(() => row.classList.remove("is-pending"));
    }

    function relabel(row, title) {
        row.querySelector("[data-task-title]").textContent = title;
        row.querySelector("[data-task-toggle]").setAttribute("aria-label", `Done: ${title}`);
        row.querySelector("[data-task-menu]").setAttribute("aria-label", `Options for ${title}`);
    }

    /* ------------------------------------------------------- moving, deleting */

    function move(row, dueDate) {
        const before = taskOf(row);
        if (before.due_date === dueDate) {
            return;
        }
        const after = { ...before, due_date: dueDate };
        const placed = place(row, after);
        placed?.querySelector("[data-task-menu]")?.focus({ preventScroll: true });
        if (!placed) {
            // The row has left the page; say where it went.
            setStatus(dueDate ? `Moving to ${dayLabel(dueDate)}…` : "Removing the date…", "");
        }

        postJson(
            `${ENDPOINT}/${before.id}/update`,
            { due_date: dueDate || "" },
            "Could not move the task."
        )
            .then((payload) => setStatus(payload.message, "success"))
            .catch((error) => {
                // Back to the list it came from, wherever the row is by now.
                const current = document.querySelector(`[data-task][data-task-id="${before.id}"]`);
                if (tasks) {
                    place(current, before);
                } else {
                    current?.remove();
                    const home = listFor(before);
                    if (home) {
                        insertRow(home, buildTask(before, home.dataset.date), before);
                    }
                }
                setStatus(error.message, "danger");
            });
    }

    function remove(row) {
        const task = taskOf(row);
        const parent = row.parentElement;
        const next = row.nextElementSibling;
        row.remove();
        if (tasks) {
            tasks = tasks.filter((entry) => entry.id !== task.id);
            refreshCounts();
        }
        setStatus("Deleting…", "");

        postJson(`${ENDPOINT}/${task.id}/delete`, {}, "Could not delete the task.")
            .then((payload) => setStatus(payload.message, "success"))
            .catch((error) => {
                if (tasks) {
                    upsert(task);
                    render();
                } else {
                    parent.insertBefore(row, next);
                }
                setStatus(error.message, "danger");
            });
    }

    /* -------------------------------------------------------------- adding */

    function editorOf(list) {
        return {
            editor: list.querySelector(":scope > [data-task-editor]"),
            input: list.querySelector(":scope > [data-task-editor] [data-task-input]"),
            addButton: list.querySelector(":scope > [data-task-add]"),
        };
    }

    function openAdd(list) {
        document.querySelectorAll("[data-task-list]").forEach((other) => {
            if (other !== list) {
                closeAdd(other);
            }
        });
        const { editor, input, addButton } = editorOf(list);
        addButton.hidden = true;
        editor.hidden = false;
        input.focus();
    }

    function closeAdd(list) {
        const { editor, input, addButton } = editorOf(list);
        if (!editor) {
            return;
        }
        editor.hidden = true;
        input.value = "";
        addButton.hidden = false;
    }

    /* A task added from a list goes on that list's day; the home page's list
       is today's, overdue rows and all. */
    function submitAdd(list) {
        const { input, addButton } = editorOf(list);
        const title = input.value.trim();
        if (!title) {
            closeAdd(list);
            return;
        }

        const dueDate = list.dataset.date || null;
        const draft = { id: null, title, due_date: dueDate, is_done: false };
        const row = buildTask(draft, dueDate);
        row.classList.add("is-pending");
        insertRow(list, row, draft);
        input.value = "";
        addButton.disabled = true;
        setStatus("Saving the task…", "");

        create(title, dueDate)
            .then((task) => {
                row.dataset.taskId = task.id;
                row.classList.remove("is-pending");
                if (tasks) {
                    upsert(task);
                    refreshCounts();
                }
                // Straight on to the next one: a list is written several
                // lines at a time.
                input.focus();
            })
            .catch((error) => {
                row.remove();
                input.value = title;
                setStatus(error.message, "danger");
            })
            .finally(() => {
                addButton.disabled = false;
            });
    }

    function create(title, dueDate, repeat) {
        return postJson(
            ENDPOINT,
            { title, due_date: dueDate || "", repeat: repeat || "" },
            "Could not save the task."
        ).then(
            (payload) => {
                setStatus(payload.message, "success");
                return payload.task;
            }
        );
    }

    /* ---------------------------------------------------------------- menu */

    const menu = document.createElement("div");
    menu.className = "task-menu";
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    document.body.append(menu);
    let menuRow = null;
    let menuAnchor = null;

    function menuItem(label, hint, action, extraClass) {
        const item = document.createElement("button");
        item.type = "button";
        item.className = `task-menu-item${extraClass ? ` ${extraClass}` : ""}`;
        item.setAttribute("role", "menuitem");
        const text = document.createElement("span");
        text.textContent = label;
        item.append(text);
        if (hint) {
            const small = document.createElement("span");
            small.className = "task-menu-hint";
            small.textContent = hint;
            item.append(small);
        }
        item.addEventListener("click", action);
        return item;
    }

    function openMenu(row, anchor) {
        if (!row.dataset.taskId) {
            return;
        }
        finishEditing();
        const task = taskOf(row);
        menuRow = row;
        menuAnchor = anchor;
        menu.replaceChildren();

        const heading = document.createElement("p");
        heading.className = "task-menu-heading";
        heading.textContent = "Move to";
        menu.append(heading);

        quickChoices()
            .filter((choice) => choice.date !== task.due_date)
            .forEach((choice) => {
                menu.append(
                    menuItem(choice.label, dayLabel(choice.date), () => {
                        closeMenu();
                        move(row, choice.date);
                    })
                );
            });

        // A real date input, so the phone's own date wheel comes up for it.
        const picker = document.createElement("input");
        picker.type = "date";
        picker.className = "task-menu-date";
        picker.value = task.due_date || "";
        picker.setAttribute("aria-label", "Pick a day");
        picker.hidden = true;
        picker.addEventListener("change", () => {
            if (picker.value) {
                closeMenu();
                move(row, picker.value);
            }
        });
        const pickItem = menuItem("Pick a date…", "", () => {
            picker.hidden = false;
            picker.focus();
            try {
                picker.showPicker?.();
            } catch (error) {
                // Not every browser lets a script open it; the field is there.
            }
        });
        menu.append(pickItem, picker);

        if (task.due_date) {
            menu.append(
                menuItem("No date", "", () => {
                    closeMenu();
                    move(row, null);
                })
            );
        }

        const rule = document.createElement("hr");
        rule.className = "task-menu-rule";
        menu.append(rule);
        menu.append(
            menuItem("Repeat", task.repeat ? REPEAT_LABELS[task.repeat] || task.repeat : "Never", () =>
                showRepeatChoices(row, task)
            )
        );
        menu.append(
            menuItem(task.is_done ? "Mark as not done" : "Mark as done", "", () => {
                closeMenu();
                toggle(row);
            })
        );
        menu.append(
            menuItem(
                "Delete",
                "",
                () => {
                    closeMenu();
                    remove(row);
                },
                "is-danger"
            )
        );

        menu.hidden = false;
        row.classList.add("is-menu-open");
        anchor.setAttribute("aria-expanded", "true");
        positionMenu();
        menu.querySelector("[role='menuitem']")?.focus({ preventScroll: true });
    }

    /* The menu's second page: how the task comes back. Swapped in place
       rather than opened beside it, which a phone has no room for. */
    function showRepeatChoices(row, task) {
        menu.replaceChildren();
        menu.append(
            menuItem("‹ Back", "", () => openMenu(row, menuAnchor), "is-back")
        );
        const heading = document.createElement("p");
        heading.className = "task-menu-heading";
        heading.textContent = "Repeat";
        menu.append(heading);

        const choices = [["", "Never"], ...Object.entries(REPEAT_LABELS)];
        choices.forEach(([rule, label]) => {
            const current = (task.repeat || "") === rule;
            menu.append(
                menuItem(
                    label,
                    current ? "✓" : "",
                    () => {
                        closeMenu();
                        setRepeat(row, rule || null);
                    },
                    current ? "is-current" : ""
                )
            );
        });
        positionMenu();
        menu.querySelector(".is-current, [role='menuitem']")?.focus({ preventScroll: true });
    }

    /* Saved before it is shown, unlike the other changes: a task with no day
       is given today by the server when it starts repeating, and the row has
       to land wherever that puts it. */
    function setRepeat(row, rule) {
        const before = taskOf(row);
        if ((before.repeat || null) === rule) {
            return;
        }
        row.classList.add("is-pending");
        postJson(`${ENDPOINT}/${before.id}/update`, { repeat: rule || "" }, "Could not save the task.")
            .then((payload) => {
                row.classList.remove("is-pending");
                const placed = place(row, payload.task);
                placed?.querySelector("[data-task-menu]")?.focus({ preventScroll: true });
                setStatus(payload.message, "success");
            })
            .catch((error) => {
                row.classList.remove("is-pending");
                setStatus(error.message, "danger");
            });
    }

    /* Under the ⋯, right-aligned to it, flipped above when there is no room
       below, and kept inside the window either way. */
    function positionMenu() {
        if (menu.hidden || !menuAnchor) {
            return;
        }
        const rect = menuAnchor.getBoundingClientRect();
        const width = menu.offsetWidth;
        const height = menu.offsetHeight;
        const margin = 8;
        let left = rect.right - width;
        let top = rect.bottom + 4;
        if (top + height > window.innerHeight - margin) {
            top = Math.max(margin, rect.top - height - 4);
        }
        left = Math.min(Math.max(margin, left), window.innerWidth - width - margin);
        menu.style.left = `${left}px`;
        menu.style.top = `${top}px`;
    }

    function closeMenu({ restoreFocus = false } = {}) {
        if (menu.hidden) {
            return;
        }
        menu.hidden = true;
        menuRow?.classList.remove("is-menu-open");
        menuAnchor?.setAttribute("aria-expanded", "false");
        if (restoreFocus && menuAnchor?.isConnected) {
            menuAnchor.focus({ preventScroll: true });
        }
        menuRow = null;
        menuAnchor = null;
    }

    menu.addEventListener("keydown", (event) => {
        const items = [...menu.querySelectorAll("[role='menuitem']")];
        const index = items.indexOf(document.activeElement);
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const step = event.key === "ArrowDown" ? 1 : -1;
            items[(index + step + items.length) % items.length]?.focus();
        } else if (event.key === "Home") {
            event.preventDefault();
            items[0]?.focus();
        } else if (event.key === "End") {
            event.preventDefault();
            items[items.length - 1]?.focus();
        } else if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            closeMenu({ restoreFocus: true });
        } else if (event.key === "Tab") {
            closeMenu({ restoreFocus: true });
        }
    });

    document.addEventListener("pointerdown", (event) => {
        if (!menu.hidden && !menu.contains(event.target) && !event.target.closest("[data-task-menu]")) {
            closeMenu();
        }
    });
    window.addEventListener("resize", positionMenu);
    window.addEventListener("scroll", positionMenu, true);

    /* -------------------------------------------------------------- events */

    document.addEventListener("click", (event) => {
        const toggleButton = event.target.closest("[data-task-toggle]");
        const titleButton = event.target.closest("[data-task-title]");
        const menuButton = event.target.closest("[data-task-menu]");
        const addButton = event.target.closest("[data-task-add]");
        const handled = toggleButton || titleButton || menuButton || addButton;
        if (!handled) {
            return;
        }
        // The schedule board picks a block up on a click; nothing in a task
        // list is a block, and this must not read as dropping one.
        event.preventDefault();
        event.stopPropagation();

        if (toggleButton) {
            toggle(rowOf(toggleButton));
        } else if (titleButton) {
            if (rowOf(titleButton).dataset.taskId) {
                editTitle(titleButton);
            }
        } else if (menuButton) {
            const row = rowOf(menuButton);
            if (menuRow === row) {
                closeMenu();
            } else {
                openMenu(row, menuButton);
            }
        } else if (addButton) {
            openAdd(addButton.closest("[data-task-list]"));
        }
    });

    // A right click, or a long press on a phone, opens the same menu.
    document.addEventListener("contextmenu", (event) => {
        const row = event.target.closest("[data-task]");
        if (!row || event.target.closest("input") || !row.dataset.taskId) {
            return;
        }
        event.preventDefault();
        openMenu(row, row.querySelector("[data-task-menu]"));
    });

    document.addEventListener("keydown", (event) => {
        const newTask = event.target.closest("[data-task-input]");
        const editing = event.target.closest("[data-task-edit]");
        if (!newTask && !editing) {
            return;
        }
        if (event.key === "Enter") {
            event.preventDefault();
            if (newTask) {
                submitAdd(newTask.closest("[data-task-list]"));
            } else {
                saveTitle(editing);
            }
        } else if (event.key === "Escape") {
            event.stopPropagation();
            if (newTask) {
                closeAdd(newTask.closest("[data-task-list]"));
            } else {
                closeTitle(editing);
            }
        }
    });

    document.addEventListener(
        "focusout",
        (event) => {
            // Clicking away from a task being rewritten keeps what was typed.
            const editing = event.target.closest("[data-task-edit]");
            if (editing) {
                if (editing.isConnected) {
                    saveTitle(editing);
                }
                return;
            }
            // An empty new-task box closes itself; one with text in it stays.
            const newTask = event.target.closest("[data-task-input]");
            if (newTask && !newTask.value.trim()) {
                closeAdd(newTask.closest("[data-task-list]"));
            }
        },
        true
    );

    /* ------------------------------------------- the Tasks page's quick add */

    if (page) {
        const form = page.querySelector("[data-task-quick-add]");
        const titleInput = form.querySelector("[data-task-quick-title]");
        const dateInput = form.querySelector("[data-task-quick-date]");
        const repeatInput = form.querySelector("[data-task-quick-repeat]");
        const chips = page.querySelector("[data-task-quick-chips]");

        const chipChoices = [
            ...quickChoices().filter((choice) => choice.label !== "Day after tomorrow"),
            { label: "No date", date: "" },
        ];
        chipChoices.forEach((choice) => {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.className = "task-chip";
            chip.dataset.date = choice.date;
            chip.textContent = choice.label;
            chip.title = choice.date ? dayLabel(choice.date) : "On no day";
            chip.addEventListener("click", () => {
                dateInput.value = choice.date;
                syncChips();
                titleInput.focus();
            });
            chips.append(chip);
        });

        function syncChips() {
            chips.querySelectorAll(".task-chip").forEach((chip) => {
                chip.classList.toggle("is-active", chip.dataset.date === dateInput.value);
            });
        }
        dateInput.addEventListener("change", syncChips);
        syncChips();

        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const title = titleInput.value.trim();
            if (!title) {
                titleInput.focus();
                return;
            }
            const submit = form.querySelector("[type='submit']");
            submit.disabled = true;
            setStatus("Saving the task…", "");
            create(title, dateInput.value || null, repeatInput.value || null)
                .then((task) => {
                    titleInput.value = "";
                    // The day stays for the next task, written into the same
                    // day more often than not; a repeat is rarely shared.
                    repeatInput.value = "";
                    upsert(task);
                    render();
                    const placed = groupsHost.querySelector(`[data-task-id="${task.id}"]`);
                    if (placed) {
                        flash(placed);
                    }
                })
                .catch((error) => setStatus(error.message, "danger"))
                .finally(() => {
                    submit.disabled = false;
                    titleInput.focus();
                });
        });

        render();
    }
})();
