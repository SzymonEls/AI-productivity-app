/**
 * The inbox on the home page: thoughts captured without a project, and the
 * picker that files each one.
 *
 * Two halves that only share this script because they share the page. The +
 * beside "Today" puts something in the inbox; the widget in the sidebar takes
 * things out of it, either by appending the text to a project's thoughts or by
 * throwing it away with the ×. Everything here applies the change to the page
 * before the server has answered and puts it back if the answer says no, the
 * way the schedule board does with a move.
 *
 * The widget is hidden rather than absent while the inbox is empty - an empty
 * inbox is nothing to report - which is why this file shows and hides it rather
 * than building it: the row markup and the project list come from the
 * <template> the page rendered, so there is no second copy of either here.
 */
(function () {
    "use strict";

    const ADD_ENDPOINT = "/inbox";
    const FILE_ENDPOINT = (itemId) => `/inbox/${itemId}/file`;
    const DELETE_ENDPOINT = (itemId) => `/inbox/${itemId}/delete`;

    const widget = document.querySelector("[data-inbox]");
    const list = widget ? widget.querySelector("[data-inbox-list]") : null;
    const template = widget ? widget.querySelector("[data-inbox-row-template]") : null;
    const count = widget ? widget.querySelector("[data-inbox-count]") : null;
    const statusOutput = widget ? widget.querySelector("[data-inbox-status]") : null;

    const addButton = document.querySelector("[data-inbox-add]");
    const captureForm = document.querySelector("[data-inbox-capture]");
    const captureField = captureForm ? captureForm.querySelector("[data-inbox-capture-field]") : null;
    const captureCancel = captureForm ? captureForm.querySelector("[data-inbox-capture-cancel]") : null;

    let statusTimer = null;

    function setStatus(message, tone) {
        if (!statusOutput) {
            return;
        }
        window.clearTimeout(statusTimer);
        statusOutput.textContent = message || "";
        statusOutput.className = `inbox-status${tone ? ` inbox-status-${tone}` : ""}`;
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

    /* The count and the whole section follow the list, so nothing has to
       remember to hide the widget when the last thought is filed. */
    function refreshWidget() {
        if (!widget || !list) {
            return;
        }
        const total = list.querySelectorAll("[data-inbox-item]").length;
        if (count) {
            count.textContent = `(${total})`;
        }
        widget.hidden = total === 0;
    }

    /* Worded exactly as the macro words it, because the × on a row the + just
       added has to read the same to a screen reader as one the page rendered. */
    function removeLabel(body) {
        return `Remove the thought \u201c${body}\u201d from the inbox`;
    }

    function buildRow(item) {
        const fragment = template.content.cloneNode(true);
        const row = fragment.querySelector("[data-inbox-item]");
        row.dataset.itemId = String(item.id);
        row.querySelector("[data-inbox-text]").textContent = item.body;
        row.querySelector("[data-inbox-remove]").setAttribute("aria-label", removeLabel(item.body));
        return row;
    }

    function addRow(item) {
        if (!list || !template) {
            return;
        }
        // Newest first, matching the order the page is rendered in.
        list.insertBefore(buildRow(item), list.firstChild);
        refreshWidget();
    }

    function fileItem(row, select) {
        const itemId = row.dataset.itemId;
        const projectId = select.value;
        if (!itemId || !projectId) {
            return;
        }

        // Taken off the page first: choosing a project is the gesture, and
        // waiting for the round trip would leave the row there long enough to
        // look like the choice did not take.
        const anchor = row.nextSibling;
        select.disabled = true;
        row.remove();
        refreshWidget();

        postJson(FILE_ENDPOINT(itemId), { project_id: Number(projectId) }, "The thought was not filed.")
            .then((payload) => {
                setStatus(payload.message || "Filed.", "success");
            })
            .catch((error) => {
                // Put it back exactly where it was, with the picker cleared so
                // the failed choice is not left looking like it stuck.
                select.disabled = false;
                select.value = "";
                list.insertBefore(row, anchor);
                refreshWidget();
                setStatus(error.message, "danger");
            });
    }

    function removeItem(row) {
        const itemId = row.dataset.itemId;
        if (!itemId) {
            return;
        }

        // Off the page first, like filing: the × is the whole gesture and there
        // is nothing to confirm - an item that should not have been captured is
        // not worth a dialog.
        const anchor = row.nextSibling;
        row.remove();
        refreshWidget();

        postJson(DELETE_ENDPOINT(itemId), {}, "The thought was not removed.")
            .then((payload) => {
                setStatus(payload.message || "Removed from the inbox.", "success");
            })
            .catch((error) => {
                list.insertBefore(row, anchor);
                refreshWidget();
                setStatus(error.message, "danger");
            });
    }

    if (list) {
        list.addEventListener("click", (event) => {
            const remove = event.target.closest("[data-inbox-remove]");
            if (!remove) {
                return;
            }
            const row = remove.closest("[data-inbox-item]");
            if (row) {
                removeItem(row);
            }
        });

        list.addEventListener("change", (event) => {
            const select = event.target.closest("[data-inbox-project]");
            if (!select) {
                return;
            }
            const row = select.closest("[data-inbox-item]");
            if (row) {
                fileItem(row, select);
            }
        });
    }

    function closeCapture() {
        if (!captureForm) {
            return;
        }
        captureForm.hidden = true;
        if (captureField) {
            captureField.value = "";
        }
        if (addButton) {
            addButton.setAttribute("aria-expanded", "false");
        }
    }

    function openCapture() {
        if (!captureForm) {
            return;
        }
        captureForm.hidden = false;
        if (addButton) {
            addButton.setAttribute("aria-expanded", "true");
        }
        if (captureField) {
            captureField.focus();
        }
    }

    function submitCapture() {
        if (!captureField) {
            return;
        }
        const body = captureField.value.trim();
        if (!body) {
            closeCapture();
            return;
        }

        captureField.disabled = true;
        postJson(ADD_ENDPOINT, { body }, "The thought was not saved.")
            .then((payload) => {
                addRow(payload.item);
                closeCapture();
                setStatus(payload.message || "Added to the inbox.", "success");
            })
            .catch((error) => {
                setStatus(error.message, "danger");
            })
            .finally(() => {
                captureField.disabled = false;
            });
    }

    if (addButton && captureForm) {
        addButton.setAttribute("aria-expanded", "false");
        addButton.addEventListener("click", () => {
            if (captureForm.hidden) {
                openCapture();
            } else {
                closeCapture();
            }
        });
    }

    if (captureForm) {
        captureForm.addEventListener("submit", (event) => {
            event.preventDefault();
            submitCapture();
        });
    }

    if (captureCancel) {
        captureCancel.addEventListener("click", closeCapture);
    }

    if (captureField) {
        captureField.addEventListener("keydown", (event) => {
            // Enter sends, Shift+Enter breaks the line: a captured thought is
            // usually one sentence, and reaching for a button with a phone in
            // one hand is the slow part.
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submitCapture();
                return;
            }
            if (event.key === "Escape") {
                event.preventDefault();
                closeCapture();
            }
        });
    }
})();
