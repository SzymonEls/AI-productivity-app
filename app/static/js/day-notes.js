/**
 * The notes at the foot of a calendar sheet, on the schedule board and in the
 * archive alike.
 *
 * One script for both pages because the list behaves the same on either: a note
 * is written about a day rather than planned for it, so a past sheet takes one
 * as readily as a future one - the same reason the archive keeps its ✓ while
 * refusing every booking change.
 *
 * The + reveals an input in place rather than opening a dialog: a note is a
 * line, and a sheet is a few centimetres wide. Clicking a line that is already
 * there does the same thing to it - the text becomes an input where it stands,
 * Enter keeps it and Escape puts it back. Adding, rewriting and removing are
 * applied to the page first and posted afterwards, the way moves and clears are
 * on the board, so a refused one puts itself back instead of reloading the page.
 */
(function () {
    "use strict";

    const root = document.querySelector("[data-schedule], [data-schedule-archive]");
    if (!root) {
        return;
    }

    const ADD_ENDPOINT = "/projects/schedule/notes";
    const UPDATE_ENDPOINT = "/projects/schedule/notes/update";
    const DELETE_ENDPOINT = "/projects/schedule/notes/delete";
    // Whichever of the two pages this is, its one status line.
    const statusOutput = root.querySelector("[data-schedule-status], [data-archive-status]");
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

    /* The × names the line it would take away, so rewriting the line has to
       rewrite the label with it. Worded exactly as the macro words it. */
    function removeLabel(body, dateLabel) {
        return `Remove the note “${body}” from ${dateLabel}`;
    }

    /* Mirrors what the template renders for one note, so a note looks the same
       whether the page drew it or the + just added it. */
    function buildNote(body, dateLabel) {
        const item = document.createElement("li");
        item.className = "day-note";
        item.setAttribute("data-note", "");

        const text = document.createElement("button");
        text.type = "button";
        text.className = "day-note-text";
        text.setAttribute("data-note-text", "");
        text.title = "Click to edit this note";
        text.textContent = body;

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "icon-button day-note-remove";
        remove.setAttribute("data-remove-note", "");
        remove.title = "Remove this note";
        remove.setAttribute("aria-label", removeLabel(body, dateLabel));
        // The same 12px stroke icon the macro renders.
        remove.innerHTML =
            '<svg class="app-icon " width="16" height="16" viewBox="0 0 24 24" fill="none"' +
            ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"' +
            ' aria-hidden="true" focusable="false"><path d="M18 6 6 18M6 6l12 12"/></svg>';

        item.append(text, remove);
        return item;
    }

    function editorOf(footer) {
        return {
            editor: footer.querySelector("[data-note-editor]"),
            input: footer.querySelector("[data-note-input]"),
            list: footer.querySelector("[data-note-list]"),
            addButton: footer.querySelector("[data-add-note]"),
        };
    }

    /* The + and the input are the same control in two states, so exactly one of
       them is on the sheet at a time. */
    function closeEditor(footer) {
        const { editor, input, addButton } = editorOf(footer);
        editor.hidden = true;
        input.value = "";
        addButton.hidden = false;
    }

    function openEditor(footer) {
        // One sheet at a time: an input left open three sheets away is a note
        // about to be written on the wrong day.
        root.querySelectorAll("[data-day-notes]").forEach((other) => {
            if (other !== footer) {
                closeEditor(other);
            }
        });

        const { editor, input, addButton } = editorOf(footer);
        addButton.hidden = true;
        editor.hidden = false;
        input.focus();
    }

    function submitNote(footer) {
        const { input, list, addButton } = editorOf(footer);
        const body = input.value.trim();
        if (!body) {
            closeEditor(footer);
            return;
        }

        const item = buildNote(body, footer.dataset.dateLabel || footer.dataset.date);
        // Dimmed until the server has it, and without an id until then: the ×
        // has nothing to delete yet, and the handler below leaves it alone.
        item.classList.add("is-pending");
        list.append(item);
        input.value = "";
        addButton.disabled = true;
        setStatus("Saving the note…", "");

        postJson(
            ADD_ENDPOINT,
            { date: footer.dataset.date, body },
            "Could not save the note."
        )
            .then((payload) => {
                item.dataset.noteId = payload.note.id;
                item.classList.remove("is-pending");
                setStatus(payload.message, "success");
                // Straight on to the next one: a day being noted usually has
                // more than one thing to say.
                input.focus();
            })
            .catch((error) => {
                item.remove();
                // The text comes back rather than being lost to the error.
                input.value = body;
                setStatus(error.message, "danger");
            })
            .finally(() => {
                addButton.disabled = false;
            });
    }

    function removeNote(button) {
        const item = button.closest("[data-note]");
        const noteId = item?.dataset.noteId;
        if (!item || !noteId) {
            return;
        }

        const list = item.parentElement;
        const next = item.nextElementSibling;
        item.remove();
        setStatus("Removing…", "");

        postJson(DELETE_ENDPOINT, { note_id: noteId }, "Could not remove the note.")
            .then((payload) => setStatus(payload.message, "success"))
            .catch((error) => {
                // Back exactly where it was, rather than at the end of the list.
                list.insertBefore(item, next);
                setStatus(error.message, "danger");
            });
    }

    /**
     * Turn one note's line into an input where it stands.
     *
     * The same shape as the + does it: the sheet never grows a dialog, and the
     * note keeps its place in the list while it is being rewritten. The input
     * lives next to the line it replaces, so putting it away needs nothing but
     * the two of them.
     */
    function editLine(text) {
        finishEveryLine();

        const item = text.closest("[data-note]");
        const original = text.textContent;
        const input = document.createElement("input");
        input.type = "text";
        input.className = "day-note-input";
        input.setAttribute("data-note-edit", "");
        // The same cap the + writes under, taken from the input it opens.
        input.maxLength = item
            .closest("[data-day-notes]")
            .querySelector("[data-note-input]").maxLength;
        input.value = original;
        input.setAttribute("aria-label", `Edit the note “${original}”`);

        text.hidden = true;
        item.insertBefore(input, text);
        input.focus();
        input.select();
    }

    function closeLine(input) {
        input.closest("[data-note]").querySelector("[data-note-text]").hidden = false;
        input.remove();
    }

    /* One line at a time: an input left open on another sheet is a note about
       to be rewritten by accident. What was typed in it is kept rather than
       dropped, which is what clicking away from it does anyway - only Escape
       throws an edit away. */
    function finishEveryLine() {
        root.querySelectorAll("[data-note-edit]").forEach(saveLine);
    }

    function saveLine(input) {
        const item = input.closest("[data-note]");
        const text = item.querySelector("[data-note-text]");
        const dateLabel = item.closest("[data-day-notes]").dataset.dateLabel;
        const remove = item.querySelector("[data-remove-note]");
        const previous = text.textContent;
        const body = input.value.trim();

        closeLine(input);
        // Nothing typed, or nothing changed: the line simply comes back. An
        // emptied note is not a deleted one - that is what the × is for.
        if (!body || body === previous) {
            return;
        }

        text.textContent = body;
        remove.setAttribute("aria-label", removeLabel(body, dateLabel));
        item.classList.add("is-pending");
        setStatus("Saving the note…", "");

        postJson(
            UPDATE_ENDPOINT,
            { note_id: item.dataset.noteId, body },
            "Could not save the note."
        )
            .then((payload) => setStatus(payload.message, "success"))
            .catch((error) => {
                text.textContent = previous;
                remove.setAttribute("aria-label", removeLabel(previous, dateLabel));
                setStatus(error.message, "danger");
            })
            .finally(() => {
                item.classList.remove("is-pending");
            });
    }

    root.addEventListener("click", (event) => {
        const line = event.target.closest("[data-note-text]");
        if (line) {
            event.preventDefault();
            event.stopPropagation();
            // A note still on its way to the server has no id to save against.
            if (line.closest("[data-note]").dataset.noteId) {
                editLine(line);
            }
            return;
        }

        const addButton = event.target.closest("[data-add-note]");
        if (addButton) {
            event.preventDefault();
            // The board picks a block up on a click; the foot of the sheet is
            // not a block, and this must not read as dropping one.
            event.stopPropagation();
            openEditor(addButton.closest("[data-day-notes]"));
            return;
        }

        const removeButton = event.target.closest("[data-remove-note]");
        if (removeButton) {
            event.preventDefault();
            event.stopPropagation();
            removeNote(removeButton);
        }
    });

    // The two keys mean the same in both inputs: Enter commits what is in the
    // one being typed in, Escape leaves it without writing anything.
    root.addEventListener("keydown", (event) => {
        const newNote = event.target.closest("[data-note-input]:not([data-note-edit])");
        const line = event.target.closest("[data-note-edit]");
        if (!newNote && !line) {
            return;
        }

        if (event.key === "Enter") {
            event.preventDefault();
            if (newNote) {
                submitNote(newNote.closest("[data-day-notes]"));
            } else {
                saveLine(line);
            }
        } else if (event.key === "Escape") {
            // Not the board's Escape, which drops a picked-up block.
            event.stopPropagation();
            if (newNote) {
                closeEditor(newNote.closest("[data-day-notes]"));
            } else {
                // The line comes back untouched: Escape is the way out of an
                // edit, so what was typed here is meant to be dropped.
                closeLine(line);
            }
        }
    });

    root.addEventListener(
        "focusout",
        (event) => {
            // A line being rewritten keeps what was typed: clicking away from
            // it is how a note is finished, not how it is abandoned. Escape is.
            const line = event.target.closest("[data-note-edit]");
            if (line) {
                // Enter has already taken the input off the page in this case.
                if (line.isConnected) {
                    saveLine(line);
                }
                return;
            }

            // The new-note input the other way round: an empty one closes
            // itself, and one with a half-written note in it stays, so the
            // click that stole the focus does not eat it.
            const newNote = event.target.closest("[data-note-input]");
            if (!newNote || newNote.value.trim()) {
                return;
            }
            closeEditor(newNote.closest("[data-day-notes]"));
        },
        true
    );
})();
