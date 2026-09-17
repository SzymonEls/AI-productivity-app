/**
 * The page behind the "Add to inbox" shortcut in the app icon's menu.
 *
 * One box and one button, because the shortcut exists to skip everything else:
 * it opens straight onto the field rather than onto the home page, so the thing
 * you had in your head goes down before you have to look at today's plan. The
 * mic is the keyboard's own, which is what makes this worth having on a phone.
 *
 * The field keeps the focus after a save rather than the page going anywhere,
 * so a second thought needs no second trip through the launcher.
 */
(function () {
    "use strict";

    const page = document.querySelector("[data-inbox-capture-page]");
    if (!page) {
        return;
    }

    const ENDPOINT = "/inbox";
    const status = page.querySelector("[data-capture-status]");
    const form = page.querySelector("[data-capture-form]");
    const field = page.querySelector("[data-capture-field]");
    const submit = form ? form.querySelector("button[type='submit']") : null;

    function setStatus(message, tone) {
        if (!status) {
            return;
        }
        status.textContent = message || "";
        status.className = `capture-status${tone ? ` capture-status-${tone}` : ""}`;
    }

    async function save() {
        const body = field.value.trim();
        if (!body) {
            field.focus();
            return;
        }

        if (submit) {
            submit.disabled = true;
        }

        try {
            const response = await fetch(ENDPOINT, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({ body }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "The thought was not saved.");
            }
            field.value = "";
            setStatus("Added. It is waiting on the home page.", "success");
        } catch (error) {
            // The text is left in the box on purpose: it is the only copy, and
            // this is the one moment where losing it would be unforgivable.
            setStatus(error.message || "The thought was not saved.", "danger");
        } finally {
            if (submit) {
                submit.disabled = false;
            }
            field.focus();
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        save();
    });

    field.addEventListener("keydown", (event) => {
        // Enter sends, Shift+Enter breaks the line - the same keys the box
        // beside "Today" answers to.
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            save();
        }
    });
})();
