/**
 * Private projects in safe mode: the plan and the thoughts open behind a button.
 *
 * A private project used to be marked with a padlock and shown like any other,
 * which is the wrong way round - the padlock told a room full of people which
 * project was the private one, and then showed them its contents. Alone at a
 * desk, though, hiding your own plan from yourself is just a click in the way,
 * so the hiding belongs to safe mode (the shield next to the theme switch) and
 * this only has work to do while that is on.
 *
 * A reveal is remembered for REVEAL_MINUTES, so moving between the project page
 * and the timer or the schedule does not mean asking again, and coming back to
 * the project half an hour later does. The memory is per project and per card,
 * in localStorage: it is a curtain, not a lock, and the text is in the page all
 * along for anyone who opens the developer tools.
 */
(function () {
    "use strict";

    const REVEAL_MINUTES = 5;
    const storageKey = (projectId, section) => `app-private-reveal:${projectId}:${section}`;

    const cards = Array.from(document.querySelectorAll("[data-private-section]"));
    if (!cards.length) {
        return;
    }

    const keyFor = (card) => storageKey(card.dataset.projectId, card.dataset.privateSection);
    const safeModeOn = () => document.documentElement.getAttribute("data-safe-mode") === "on";

    function readExpiry(key) {
        try {
            return Number(window.localStorage.getItem(key)) || 0;
        } catch (error) {
            return 0; // Private browsing, or storage switched off: ask every time.
        }
    }

    function writeExpiry(key, expiry) {
        try {
            window.localStorage.setItem(key, String(expiry));
        } catch (error) {
            /* The reveal still works for this page view. */
        }
    }

    function forgetExpiry(key) {
        try {
            window.localStorage.removeItem(key);
        } catch (error) {
            /* Nothing was remembered, then. */
        }
    }

    // Only meaningful while safe mode is on - the veil is drawn by that alone -
    // but the remembered reveals are applied here so a card the user has already
    // opened does not close again on every page load.
    cards.forEach((card) => {
        if (readExpiry(keyFor(card)) > Date.now()) {
            card.classList.remove("private-veiled");
        }

        card.querySelector("[data-private-reveal]")?.addEventListener("click", () => {
            card.classList.remove("private-veiled");
            writeExpiry(keyFor(card), Date.now() + REVEAL_MINUTES * 60 * 1000);
        });
    });

    // Switching safe mode on means "hide this now", so it also drops what was
    // revealed earlier: the point of reaching for the shield is that the room has
    // changed, and a reveal from four minutes ago knows nothing about that.
    document.addEventListener("safe-mode-change", () => {
        if (!safeModeOn()) {
            return;
        }
        cards.forEach((card) => {
            forgetExpiry(keyFor(card));
            card.classList.add("private-veiled");
        });
    });
})();
