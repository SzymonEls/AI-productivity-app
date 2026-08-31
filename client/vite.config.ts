import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Flask keeps serving the sign-in pages and the synchronisation API. In
// development Vite is the origin and proxies those through, so the session
// cookie stays same-origin: no CORS, and no loosening SameSite to get a login
// to stick. In production Flask serves the built files and there is no proxy.
const FLASK = "http://127.0.0.1:5001";

export default defineConfig(({ command }) => ({
  plugins: [svelte()],

  // Built assets are served by Flask out of /static/client/. In development
  // Vite is the root, so the app lives at / and the base has to stay bare.
  base: command === "build" ? "/static/client/" : "/",

  build: {
    outDir: "../app/static/client",
    emptyOutDir: true,
    manifest: true,
  },

  server: {
    port: 5173,
    proxy: {
      "/api": FLASK,
      "/auth": FLASK,
      // Icons and the manifest are still Flask's.
      "/static": FLASK,
      "/manifest.webmanifest": FLASK,
      "/service-worker.js": FLASK,
    },
  },
}));
