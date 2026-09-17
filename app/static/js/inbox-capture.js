/**
 * The page behind the "Add to inbox" shortcut in the app icon's menu.
 *
 * Its whole job is to put a notification with a reply field in the shade and
 * then be irrelevant: the reply is handled by the service worker
 * (see service-worker.js), so a thought can be dictated without this window, or
 * any window, being looked at. Getting here at all is the cost of the shortcut
 * having to open something.
 *
 * Everything below is about the cases where that does not work. Permission is
 * asked for behind a button because Chrome refuses a request that no gesture
 * led to, and the textarea underneath is a real fallback rather than a
 * courtesy - a phone that has notifications switched off for this app would
 * otherwise have a shortcut that does nothing and says nothing.
 */
(function () {
    "use strict";

    const page = document.querySelector("[data-inbox-capture-page]");
    if (!page) {
        return;
    }

    const ENDPOINT = "/inbox";
    const status = page.querySelector("[data-capture-status]");
    const enableButton = page.querySelector("[data-capture-enable]");
    const form = page.querySelector("[data-capture-form]");
    const field = page.querySelector("[data-capture-field]");

    function setStatus(message) {
        if (status) {
            status.textContent = message;
        }
    }

    function supported() {
        return "serviceWorker" in navigator && "Notification" in window && window.isSecureContext;
    }

    /* The same notification the service worker re-shows after each reply, so the
       one in the shade looks the same however it got there. */
    function notificationOptions(body) {
        return {
            body,
            tag: "inbox-capture",
            silent: true,
            icon: "/static/icons/pwa-icon-192.png",
            badge: "/static/icons/pwa-icon-192.png",
            data: { kind: "inbox-capture" },
            actions: [
                {
                    action: "inbox",
                    type: "text",
                    title: "Add",
                    placeholder: "A thought to file later…",
                },
            ],
        };
    }

    async function showCaptureNotification() {
        const registration = await navigator.serviceWorker.ready;
        await registration.showNotification("Add to inbox", notificationOptions("Reply here to drop a thought in the inbox."));
        setStatus("Pull down your notifications and reply — the mic is on the keyboard. You can close this page.");
    }

    async function start() {
        if (!supported()) {
            setStatus("This browser has no notifications to reply to. Write it here instead.");
            return;
        }

        if (Notification.permission === "denied") {
            setStatus("Notifications are switched off for this app, so there is nothing to reply to. Write it here, or turn them back on in the system settings.");
            return;
        }

        if (Notification.permission !== "granted") {
            setStatus("Allow notifications once and this shortcut will drop a reply box into your notification shade.");
            if (enableButton) {
                enableButton.hidden = false;
            }
            return;
        }

        try {
            await showCaptureNotification();
        } catch (error) {
            setStatus("The notification could not be shown. Write it here instead.");
        }
    }

    if (enableButton) {
        enableButton.addEventListener("click", async () => {
            enableButton.disabled = true;
            try {
                // Asked from inside the click: Chrome ignores a request that no
                // gesture led to, and silently treats it as a refusal.
                const permission = await Notification.requestPermission();
                if (permission !== "granted") {
                    setStatus("Notifications were not allowed. Write it here instead.");
                    return;
                }
                enableButton.hidden = true;
                await showCaptureNotification();
            } catch (error) {
                setStatus("The notification could not be shown. Write it here instead.");
            } finally {
                enableButton.disabled = false;
            }
        });
    }

    if (form && field) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const body = field.value.trim();
            if (!body) {
                return;
            }

            const submit = form.querySelector("button[type='submit']");
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
                setStatus("Added to the inbox. It is waiting on the home page.");
            } catch (error) {
                setStatus(error.message || "The thought was not saved.");
            } finally {
                if (submit) {
                    submit.disabled = false;
                }
            }
        });
    }

    start();
})();
