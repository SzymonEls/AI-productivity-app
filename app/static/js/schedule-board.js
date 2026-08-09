/**
 * Edit mode for the schedule page.
 *
 * "Edit" turns the three weeks of day sheets into a board: a booked block can be
 * dragged onto any other block, and dropping it on a taken one swaps the two.
 * The same move works by tapping - pick a block, then tap where it goes - which
 * is what keeps this usable on a phone, where HTML5 drag events do not fire.
 *
 * The move is applied to the page first and posted afterwards; a rejected move
 * (the "one block today plus one in the future" rule) is undone again, so the
 * page never has to reload to stay truthful.
 */
(function () {
    "use strict";

    const root = document.querySelector("[data-schedule]");
    if (!root) {
        return;
    }

    const MOVE_ENDPOINT = "/projects/schedule/move";
    const editButton = root.querySelector("[data-schedule-edit]");
    const editLabel = root.querySelector("[data-schedule-edit-label]");
    const hint = root.querySelector("[data-schedule-hint]");
    const statusOutput = root.querySelector("[data-schedule-status]");

    let editMode = false;
    let pickedCell = null;
    let draggedContent = null;
    let statusTimer = null;

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
                throw new Error(payload.message || "Could not move the block.");
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

    /* Mirrors the classes the template renders, so a block looks the same
       whether the page drew it or a move put the project there. */
    function refreshCell(cell) {
        const content = contentOf(cell);
        const booked = Boolean(content.dataset.projectId);

        cell.classList.toggle("is-booked", booked);
        cell.classList.toggle("is-free", !booked);
        cell.classList.toggle("is-done", booked && content.dataset.done === "1");
        cell.querySelector("[data-clear-slot]").classList.toggle("d-none", !booked);
        cell.querySelector("[data-fill-slot]").classList.toggle("d-none", booked);
        content.draggable = editMode && booked;
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
        // Always between the letter and the buttons, which belong to the block.
        cell.insertBefore(content, cell.querySelector("[data-clear-slot]"));
    }

    /**
     * Swap the contents of two blocks and return the function that puts them back.
     *
     * "Done" marks a day's session, so it survives a move inside one sheet and is
     * dropped when the project lands on another date - the same rule the server
     * applies, kept in step here so the page does not lie until the next reload.
     */
    function applyMove(fromCell, toCell) {
        const fromContent = contentOf(fromCell);
        const toContent = contentOf(toCell);
        const wasDone = [fromContent.dataset.done === "1", toContent.dataset.done === "1"];
        const sameDay = fromCell.dataset.date === toCell.dataset.date;

        moveContentInto(toCell, fromContent);
        moveContentInto(fromCell, toContent);
        setDone(fromContent, wasDone[0] && sameDay);
        setDone(toContent, wasDone[1] && sameDay);
        refreshCell(fromCell);
        refreshCell(toCell);

        return function undo() {
            moveContentInto(fromCell, fromContent);
            moveContentInto(toCell, toContent);
            setDone(fromContent, wasDone[0]);
            setDone(toContent, wasDone[1]);
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

        postJson(MOVE_ENDPOINT, {
            from_date: fromCell.dataset.date,
            from_slot: fromCell.dataset.slot,
            to_date: toCell.dataset.date,
            to_slot: toCell.dataset.slot,
        })
            .then((payload) => setStatus(payload.message, "success"))
            .catch((error) => {
                undo();
                setStatus(error.message, "danger");
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

    function setEditMode(enabled) {
        editMode = enabled;
        root.classList.toggle("is-editing", enabled);
        editButton.classList.toggle("btn-primary", enabled);
        editButton.classList.toggle("btn-outline-secondary", !enabled);
        editLabel.textContent = enabled ? "Done" : "Edit";
        hint.classList.toggle("d-none", !enabled);
        clearPick();
        setStatus("", "");
        cells().forEach(refreshCell);
    }

    editButton.addEventListener("click", () => setEditMode(!editMode));

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || !editMode) {
            return;
        }
        if (pickedCell) {
            clearPick();
            setStatus("", "");
        } else {
            setEditMode(false);
        }
    });

    root.addEventListener("click", (event) => {
        if (!editMode || event.target.closest("[data-clear-slot]")) {
            return;
        }

        const cell = event.target.closest("[data-slot-cell]");
        if (!cell) {
            return;
        }

        // Titles are links; in edit mode a click means "move this", not "open it".
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
        // picker, so edit mode can fill a day as well as rearrange it.
    });

    root.addEventListener("dragstart", (event) => {
        const content = event.target.closest("[data-slot-content]");
        if (!editMode || !content || !content.dataset.projectId) {
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
        if (!editMode || !draggedContent || !cell || cell.contains(draggedContent)) {
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
        if (!editMode || !draggedContent || !cell) {
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
