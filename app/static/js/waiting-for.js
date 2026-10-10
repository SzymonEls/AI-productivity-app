/**
 * The "Waiting for" dialog on a project page: suggests the milestone from the
 * plan of the project picked above it.
 *
 * The suggestions are that plan's headings and open items, asked for when a
 * project is picked (GET /projects/<id>/milestones) rather than rendered into
 * the page - they are another project's plan, and the dialog is rarely opened.
 * Picking one only types it into the field: the text is what gets saved, so
 * rewriting the plan later cannot break anything.
 *
 * Typing filters the list. A private project's lines are left out while safe
 * mode is on, the same way its plan is covered.
 */
(function () {
    "use strict";

    const form = document.querySelector("[data-waiting-form]");
    const select = form?.querySelector("[data-waiting-project]");
    const input = form?.querySelector("[data-waiting-note]");
    const box = form?.querySelector("[data-waiting-milestones]");
    const status = form?.querySelector("[data-waiting-milestones-status]");
    const list = form?.querySelector("[data-waiting-milestones-list]");
    if (!form || !select || !input || !box || !status || !list) {
        return;
    }

    const modal = form.closest(".modal");
    let milestones = [];
    let isPrivate = false;
    let request = 0;

    const safeModeOn = () => document.documentElement.getAttribute("data-safe-mode") === "on";

    function setStatus(message) {
        status.textContent = message || "";
        status.classList.toggle("d-none", !message);
    }

    function render(filter) {
        list.replaceChildren();
        box.classList.remove("d-none");

        if (isPrivate && safeModeOn()) {
            setStatus("A private project — its plan stays hidden while safe mode is on.");
            return;
        }
        if (!milestones.length) {
            setStatus("Nothing in that project's plan to pick from.");
            return;
        }

        const needle = (filter || "").trim().toLowerCase();
        const current = input.value.trim();
        const shown = needle
            ? milestones.filter((milestone) => milestone.text.toLowerCase().includes(needle))
            : milestones;
        setStatus(shown.length ? "" : "No line of that plan matches.");

        shown.forEach((milestone) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `waiting-milestone waiting-milestone-${milestone.kind}`;
            if (milestone.kind === "heading") {
                button.style.setProperty("--milestone-level", String(Math.max(milestone.level - 1, 0)));
            }
            button.classList.toggle("is-selected", milestone.text === current);
            button.textContent = milestone.text;
            button.addEventListener("click", () => {
                input.value = milestone.text;
                render("");
                input.focus();
            });
            const item = document.createElement("li");
            item.append(button);
            list.append(item);
        });
    }

    async function load() {
        const option = select.selectedOptions[0];
        const url = option?.dataset.milestonesUrl;
        const token = ++request;
        milestones = [];
        isPrivate = false;
        list.replaceChildren();
        if (!url) {
            box.classList.add("d-none");
            return;
        }

        box.classList.remove("d-none");
        setStatus("Reading the plan…");
        try {
            const response = await fetch(url, { headers: { Accept: "application/json" } });
            const payload = await response.json();
            if (token !== request) {
                return;
            }
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "");
            }
            milestones = payload.milestones || [];
            isPrivate = Boolean(payload.is_private);
            render("");
        } catch (error) {
            if (token === request) {
                setStatus("Could not read that project's plan — type the milestone instead.");
            }
        }
    }

    select.addEventListener("change", () => {
        // A milestone picked off the previous project's plan does not belong to
        // this one; something typed by hand is left alone.
        if (milestones.some((milestone) => milestone.text === input.value.trim())) {
            input.value = "";
        }
        load();
    });
    input.addEventListener("input", () => render(input.value));
    modal?.addEventListener("show.bs.modal", load);
    document.addEventListener("safe-mode-change", () => {
        if (milestones.length || isPrivate) {
            render("");
        }
    });
})();
