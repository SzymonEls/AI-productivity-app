/**
 * Private projects: the plan and the thoughts open behind a button.
 *
 * A private project used to be marked with a padlock and shown like any other,
 * which is the wrong way round - the padlock told a room full of people which
 * project was the private one, and then showed them its contents. The page now
 * renders those two cards veiled and this lifts them one at a time.
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

    document.querySelectorAll("[data-private-section]").forEach((card) => {
        const key = storageKey(card.dataset.projectId, card.dataset.privateSection);

        if (readExpiry(key) > Date.now()) {
            card.classList.remove("private-veiled");
        }

        card.querySelector("[data-private-reveal]")?.addEventListener("click", () => {
            card.classList.remove("private-veiled");
            writeExpiry(key, Date.now() + REVEAL_MINUTES * 60 * 1000);
        });
    });
})();
