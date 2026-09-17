/**
 * The schedule page as a board.
 *
 * The three weeks of day sheets are always live: a booked block can be dragged
 * onto any other block, and dropping it on a taken one swaps the two. The same
 * move works by tapping - pick a block, then tap where it goes - which is what
 * keeps this usable on a phone, where HTML5 drag events do not fire.
 *
 * There is no edit mode to switch on. It used to be one, and every action that
 * reloaded the page threw it away; a board that is simply always a board has no
 * state to lose. The cost is that a block's title no longer opens the project -
 * on the board a click means "move this".
 *
 * Moves and clears are applied to the page first and posted afterwards; a
 * refused one (the "one block today plus one in the future" rule) is undone
 * again, so the page never has to reload to stay truthful.
 */
(function () {
    "use strict";

    const root = document.querySelector("[data-schedule]");
    if (!root) {
        return;
    }

    const MOVE_ENDPOINT = "/projects/schedule/move";
    const CLEAR_ENDPOINT = "/projects/schedule/clear";
    const DAY_OFF_ENDPOINT = "/projects/schedule/day-off";
    // A day off reloads the page, which would throw away the one line saying what
    // it did - including which blocks it would not move.
    const DAY_OFF_MESSAGE_KEY = "schedule-day-off-message";
    const statusOutput = root.querySelector("[data-schedule-status]");

    let pickedCell = null;
    let draggedContent = null;
    let statusTimer = null;

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

    function setStatus(message, tone) {
        window.clearTimeout(statusTimer);
        statusOutput.textContent = message || "";
        statusOutput.className = `schedule-status${tone ? ` schedule-status-${tone}` : ""}`;
        if (message) {
            statusTimer = window.setTimeout(() => setStatus("", ""), 4000);
        }
    }

    function cells() {
        return root.querySelectorAll("[data-slot-cell]");
    }

    function contentOf(cell) {
        return cell.querySelector("[data-slot-content]");
    }

    function isBooked(cell) {
        return Boolean(contentOf(cell).dataset.projectId);
    }

    // The same arithmetic slots.py does, kept in step here so the optimistic
    // redraw below shows the colour the move is about to be given. The count
    // runs on; only the colour stops, at MAX_POSTPONED_LEVEL - which is why a
    // block put off four times takes four moves back to come off red.
    const MAX_POSTPONED_LEVEL = 2;

    function postponedOf(content) {
        return Number(content.dataset.postponed) || 0;
    }

    function postponedLevel(count) {
        return Math.min(count, MAX_POSTPONED_LEVEL);
    }

    function postponementAfter(count, fromDate, toDate) {
        if (toDate > fromDate) {
            return count + 1;
        }
        if (toDate < fromDate) {
            return Math.max(count - 1, 0);
        }
        return count;
    }

    // Mirrors the postponed_title() macro, down to the wording: the two read
    // side by side on a page the board has only partly redrawn.
    function postponedTitle(count) {
        const times = count === 1 ? "once" : count === 2 ? "twice" : `${count} times`;
        return `Put off ${times} — moved to a later day`;
    }

    /* The ! on a block that has been put off: added, updated or taken away to
       match the count the block is now carrying. It sits between the content and
       the block's own buttons, which is where the template renders it. */
    function setWarn(cell, count, done) {
        const existing = cell.querySelector("[data-slot-warn]");
        if (!count || done) {
            existing?.remove();
            return;
        }

        const title = postponedTitle(count);
        const warn = existing || document.createElement("span");
        if (!existing) {
            warn.className = "day-slot-warn";
            warn.setAttribute("data-slot-warn", "");
            warn.setAttribute("role", "img");
            warn.textContent = "!";
            contentOf(cell).after(warn);
        }
        warn.title = title;
        warn.setAttribute("aria-label", title);
    }

    /* Mirrors the classes the template renders, so a block looks the same
       whether the page drew it or a move put the project there. */
    function refreshCell(cell) {
        const content = contentOf(cell);
        const booked = Boolean(content.dataset.projectId);
        const done = booked && content.dataset.done === "1";
        const postponed = booked ? postponedOf(content) : 0;
        const level = postponedLevel(postponed);

        cell.classList.toggle("is-booked", booked);
        cell.classList.toggle("is-free", !booked);
        cell.classList.toggle("is-done", done);
        cell.classList.toggle("is-postponed-1", level === 1);
        cell.classList.toggle("is-postponed-2", level === 2);
        setWarn(cell, postponed, done);
        cell.querySelector("[data-clear-slot]").classList.toggle("d-none", !booked);
        cell.querySelector("[data-fill-slot]").classList.toggle("d-none", booked);
        content.draggable = booked;
    }

    function setDone(content, done) {
        content.dataset.done = done ? "1" : "0";
        const mark = content.querySelector("[data-slot-done]");

        if (done && !mark) {
            const added = document.createElement("span");
            added.className = "day-slot-done";
            added.setAttribute("data-slot-done", "");
            added.title = "Session done";
            added.textContent = "✓";
            content.querySelector(".day-slot-title")?.after(added);
        } else if (!done && mark) {
            mark.remove();
        }
    }

    function moveContentInto(cell, content) {
        // Straight after the letter, which is the first thing in every block.
        // Anchoring on the letter rather than on the × matters now that the !
        // sits between the two: inserting before the × would put the content
        // after a ! the block has not shed yet.
        cell.querySelector(".day-slot-letter").after(content);
    }

    /**
     * Swap the contents of two blocks and return the function that puts them back.
     *
     * "Done" marks a day's session, so it survives a move inside one sheet and is
     * dropped when the project lands on another date - the same rule the server
     * applies, kept in step here so the page does not lie until the next reload.
     *
     * The postponement count follows the same idea and the other half of that
     * rule: the two blocks pass each other, so in a swap across days one goes a
     * step later and the other a step earlier. Dates are ISO strings, which sort
     * as the days they name.
     */
    function applyMove(fromCell, toCell) {
        const fromContent = contentOf(fromCell);
        const toContent = contentOf(toCell);
        const wasDone = [fromContent.dataset.done === "1", toContent.dataset.done === "1"];
        const wasPostponed = [postponedOf(fromContent), postponedOf(toContent)];
        const fromDate = fromCell.dataset.date;
        const toDate = toCell.dataset.date;
        const sameDay = fromDate === toDate;

        moveContentInto(toCell, fromContent);
        moveContentInto(fromCell, toContent);
        setDone(fromContent, wasDone[0] && sameDay);
        setDone(toContent, wasDone[1] && sameDay);
        fromContent.dataset.postponed = postponementAfter(wasPostponed[0], fromDate, toDate);
        toContent.dataset.postponed = postponementAfter(wasPostponed[1], toDate, fromDate);
        refreshCell(fromCell);
        refreshCell(toCell);

        return function undo() {
            moveContentInto(fromCell, fromContent);
            moveContentInto(toCell, toContent);
            setDone(fromContent, wasDone[0]);
            setDone(toContent, wasDone[1]);
            fromContent.dataset.postponed = wasPostponed[0];
            toContent.dataset.postponed = wasPostponed[1];
            refreshCell(fromCell);
            refreshCell(toCell);
        };
    }

    function requestMove(fromCell, toCell) {
        if (fromCell === toCell) {
            return;
        }

        const undo = applyMove(fromCell, toCell);
        setStatus("Moving…", "");

        postJson(
            MOVE_ENDPOINT,
            {
                from_date: fromCell.dataset.date,
                from_slot: fromCell.dataset.slot,
                to_date: toCell.dataset.date,
                to_slot: toCell.dataset.slot,
            },
            "Could not move the block."
        )
            .then((payload) => setStatus(payload.message, "success"))
            .catch((error) => {
                undo();
                setStatus(error.message, "danger");
            });
    }

    /**
     * Empty a block on the page and return the function that fills it back in.
     *
     * The same shape as applyMove: the page changes first and the request
     * follows, so a refused clear can be put back where it was. Freeing a block
     * used to reload the page, which threw away edit mode along with it - only
     * the Edit button ends that now.
     */
    function applyClear(cell) {
        const content = contentOf(cell);
        const previous = {
            projectId: content.dataset.projectId,
            done: content.dataset.done,
            postponed: content.dataset.postponed,
            nodes: Array.from(content.childNodes),
        };

        // What the template puts in an empty block.
        const free = document.createElement("span");
        free.className = "day-slot-free";
        free.textContent = "Free";

        content.dataset.projectId = "";
        content.dataset.done = "0";
        // Freeing the block throws the booking away, and with it the record of
        // how often it was put off - whatever is booked here next starts clean.
        content.dataset.postponed = "0";
        content.replaceChildren(free);
        refreshCell(cell);

        return function undo() {
            content.dataset.projectId = previous.projectId;
            content.dataset.done = previous.done;
            content.dataset.postponed = previous.postponed;
            content.replaceChildren(...previous.nodes);
            refreshCell(cell);
        };
    }

    function requestClear(button) {
        const cell = button.closest("[data-slot-cell]");
        if (!cell || !isBooked(cell)) {
            return;
        }
        // A block on its way out cannot stay picked up for a move.
        if (pickedCell === cell) {
            clearPick();
        }

        const undo = applyClear(cell);
        button.disabled = true;
        setStatus("Freeing…", "");

        postJson(
            CLEAR_ENDPOINT,
            { date: cell.dataset.date, slot: cell.dataset.slot },
            "Could not free the block."
        )
            .then((payload) => setStatus(payload.message, "success"))
            .catch((error) => {
                undo();
                setStatus(error.message, "danger");
            })
            // The button belongs to the position, not the project: it is hidden
            // now, but the next booking to land here needs it working again.
            .finally(() => {
                button.disabled = false;
            });
    }

    function clearPick() {
        pickedCell?.classList.remove("is-picked");
        pickedCell = null;
    }

    function pick(cell) {
        clearPick();
        pickedCell = cell;
        cell.classList.add("is-picked");
        setStatus("Now tap the block it should go to.", "");
    }

    // The template renders every block in its final state; only "draggable"
    // belongs to the script, so the board is set up in one pass.
    cells().forEach(refreshCell);

    // Pick up what the day off had to say before it reloaded the page. It is
    // worth carrying: "1 stayed put" is the answer to why the day you took off
    // still has a block on it.
    try {
        const carried = window.sessionStorage.getItem(DAY_OFF_MESSAGE_KEY);
        if (carried) {
            window.sessionStorage.removeItem(DAY_OFF_MESSAGE_KEY);
            setStatus(carried, "success");
        }
    } catch (error) {
        /* No session storage: nothing to carry. */
    }

    /**
     * Take a day off: the day named in the dialog, and every day after it, move
     * one day later.
     *
     * The date is typed rather than clicked on a sheet - the day being freed is
     * usually one you already know, and it can be past the edge of the page.
     * Unlike a move or a clear this touches sheets all over the page, and pushes
     * the last of them out by a day, so it reloads instead of trying to redraw
     * the board in place.
     */
    const dayOffDialog = root.querySelector("[data-day-off-dialog]");
    const dayOffDate = root.querySelector("[data-day-off-date]");
    const dayOffStatus = root.querySelector("[data-day-off-status]");
    const dayOffSubmit = root.querySelector("[data-day-off-submit]");

    function setDayOffStatus(message, tone) {
        dayOffStatus.textContent = message || "";
        dayOffStatus.className = `planner-status${tone ? ` planner-status-${tone}` : ""}`;
    }

    function openDayOff() {
        clearPick();
        setDayOffStatus("", "");
        dayOffDialog.hidden = false;
        dayOffDate.focus();
    }

    function closeDayOff() {
        dayOffDialog.hidden = true;
        dayOffSubmit.disabled = false;
    }

    function requestDayOff() {
        const date = dayOffDate.value;
        if (!date) {
            setDayOffStatus("Pick a day first.", "danger");
            return;
        }

        dayOffSubmit.disabled = true;
        setDayOffStatus("Moving the plan…", "");

        postJson(DAY_OFF_ENDPOINT, { date }, "Could not take the day off.")
            .then((payload) => {
                try {
                    window.sessionStorage.setItem(DAY_OFF_MESSAGE_KEY, payload.message || "");
                } catch (error) {
                    /* No session storage: the board just comes back quiet. */
                }
                window.location.reload();
            })
            .catch((error) => {
                dayOffSubmit.disabled = false;
                setDayOffStatus(error.message, "danger");
            });
    }

    dayOffDialog.addEventListener("click", (event) => {
        if (event.target === dayOffDialog || event.target.closest("[data-day-off-close]")) {
            closeDayOff();
        } else if (event.target.closest("[data-day-off-submit]")) {
            requestDayOff();
        }
    });

    // Enter in the date field is the same "yes" as the button.
    dayOffDate.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            requestDayOff();
        }
    });

    // Its own listener rather than a branch of the one below, which steps aside
    // for these buttons.
    root.addEventListener("click", (event) => {
        if (event.target.closest("[data-day-off-open]")) {
            event.preventDefault();
            openDayOff();
            return;
        }

        const clearButton = event.target.closest("[data-clear-slot]");
        if (!clearButton) {
            return;
        }
        event.preventDefault();
        requestClear(clearButton);
    });

    // Escape closes the day-off dialog, or drops a block that was picked up.
    // There is no longer a mode behind either of them to leave.
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") {
            return;
        }
        if (!dayOffDialog.hidden) {
            closeDayOff();
            return;
        }
        if (!pickedCell) {
            return;
        }
        clearPick();
        setStatus("", "");
    });

    root.addEventListener("click", (event) => {
        if (event.target.closest("[data-clear-slot]")) {
            return;
        }

        const cell = event.target.closest("[data-slot-cell]");
        if (!cell) {
            return;
        }

        // Titles are links; on the board a click means "move this", not "open it".
        if (event.target.closest(".day-slot-title")) {
            event.preventDefault();
        }

        if (pickedCell) {
            // The picker behind an empty block must not open on the drop tap.
            event.preventDefault();
            event.stopPropagation();
            const from = pickedCell;
            clearPick();
            if (from !== cell) {
                requestMove(from, cell);
            } else {
                setStatus("", "");
            }
            return;
        }

        if (isBooked(cell)) {
            event.stopPropagation();
            pick(cell);
        }
        // An empty block with nothing picked up falls through to the project
        // picker, so the board fills a day as well as rearranging it.
    });

    root.addEventListener("dragstart", (event) => {
        const content = event.target.closest("[data-slot-content]");
        if (!content || !content.dataset.projectId) {
            event.preventDefault();
            return;
        }
        clearPick();
        draggedContent = content;
        content.closest("[data-slot-cell]").classList.add("is-dragging");
        event.dataTransfer.effectAllowed = "move";
        // Firefox only starts a drag once the payload is set.
        event.dataTransfer.setData("text/plain", content.dataset.projectId);
    });

    root.addEventListener("dragover", (event) => {
        const cell = event.target.closest("[data-slot-cell]");
        if (!draggedContent || !cell || cell.contains(draggedContent)) {
            return;
        }
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        cell.classList.add("is-drag-over");
    });

    root.addEventListener("dragleave", (event) => {
        const cell = event.target.closest("[data-slot-cell]");
        if (cell && !cell.contains(event.relatedTarget)) {
            cell.classList.remove("is-drag-over");
        }
    });

    root.addEventListener("drop", (event) => {
        const cell = event.target.closest("[data-slot-cell]");
        if (!draggedContent || !cell) {
            return;
        }
        event.preventDefault();
        cell.classList.remove("is-drag-over");

        const fromCell = draggedContent.closest("[data-slot-cell]");
        draggedContent = null;
        requestMove(fromCell, cell);
    });

    root.addEventListener("dragend", () => {
        draggedContent = null;
        root.querySelectorAll(".is-dragging, .is-drag-over").forEach((node) => {
            node.classList.remove("is-dragging", "is-drag-over");
        });
    });
})();
