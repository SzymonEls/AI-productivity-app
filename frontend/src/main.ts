import { mount } from "svelte";

// Order matters, and matches what base.html loaded: Bootstrap first, then the
// design tokens, then the feature styles that have to win over both.
import "bootstrap/dist/css/bootstrap.min.css";
// The block editor carried over from the previous frontend emits FontAwesome
// markup for its section controls; main loaded this from a CDN, which is also
// why those buttons were blank offline.
import "@fortawesome/fontawesome-free/css/all.min.css";
import "./styles/theme.css";
import "./styles/styles.css";

import App from "./App.svelte";
import { applyAppearance } from "./lib/appearance";

// Before the first paint, for the same reason base.html did it inline.
applyAppearance();

mount(App, { target: document.getElementById("app")! });

// Root-scoped, so the shell answers for every address the client owns. Only
// over https or on localhost - a service worker refuses anything else.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => {
    // Not being installable is not a reason for the application to fail.
  });
}
