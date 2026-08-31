import { mount } from "svelte";

// Order matters, and matches what base.html loaded: Bootstrap first, then the
// design tokens, then the feature styles that have to win over both.
import "bootstrap/dist/css/bootstrap.min.css";
import "./styles/theme.css";
import "./styles/styles.css";

import App from "./App.svelte";
import { applyAppearance } from "./lib/appearance";

// Before the first paint, for the same reason base.html did it inline.
applyAppearance();

mount(App, { target: document.getElementById("app")! });
