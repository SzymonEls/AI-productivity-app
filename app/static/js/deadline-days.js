/**
 * The schedule's purple D: the projects whose deadline falls on a day.
 *
 * Each D carries its list in a <template> beside it, and this shows that list
 * in one shared panel fixed to the viewport - a day sheet clips whatever sticks
 * out of it, so the list cannot simply drop out of the header. The clicks are
 * caught on the document rather than on each D, so the weeks the calendar view
 * loads as it is scrolled get a working D without anyone binding it.
 *
 * One panel at a time: a click on another D moves it there, a click on the
 * same one, outside it, Escape, a scroll or a resize closes it.
 */
(function () {
    "use strict";

    const GUTTER = 16;
    const GAP = 6;

    let panel = null;
    let openFor = null;

    function ensurePanel() {
        if (panel) {
            return panel;
        }
        panel = document.createElement("div");
        panel.className = "day-deadline-panel";
        panel.setAttribute("role", "dialog");
        panel.hidden = true;
        document.body.appendChild(panel);
        return panel;
    }

    function close(returnFocus) {
        if (!openFor) {
            return;
        }
        const marker = openFor;
        openFor = null;
        marker.setAttribute("aria-expanded", "false");
        panel.hidden = true;
        panel.replaceChildren();
        if (returnFocus) {
            marker.focus();
        }
    }

    /* Under the D, or above it when the viewport has no room below; kept
       inside the side gutters either way. */
    function place(marker) {
        const rect = marker.getBoundingClientRect();
        panel.style.left = "0px";
        panel.style.top = "0px";
        const width = panel.offsetWidth;
        const height = panel.offsetHeight;

        const maxLeft = window.innerWidth - GUTTER - width;
        const left = Math.max(GUTTER, Math.min(rect.left, maxLeft));
        const below = rect.bottom + GAP;
        const top = below + height > window.innerHeight - GUTTER && rect.top - GAP - height >= GUTTER
            ? rect.top - GAP - height
            : below;

        panel.style.left = `${left}px`;
        panel.style.top = `${top}px`;
    }

    function open(marker) {
        const template = marker.parentElement?.querySelector("[data-deadline-list]");
        if (!template) {
            return;
        }
        close(false);
        ensurePanel();
        panel.replaceChildren(template.content.cloneNode(true));
        panel.setAttribute("aria-label", marker.getAttribute("aria-label") || "Deadlines");
        panel.hidden = false;
        openFor = marker;
        marker.setAttribute("aria-expanded", "true");
        place(marker);
    }

    document.addEventListener("click", (event) => {
        const marker = event.target.closest("[data-deadline-marker]");
        if (marker) {
            event.preventDefault();
            if (openFor === marker) {
                close(false);
            } else {
                open(marker);
            }
            return;
        }
        if (openFor && !panel.contains(event.target)) {
            close(false);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && openFor) {
            close(true);
        }
    });

    // The panel is fixed and the D scrolls away under it, so rather than
    // chase it the panel goes.
    window.addEventListener("scroll", () => close(false), { passive: true, capture: true });
    window.addEventListener("resize", () => close(false));
})();
