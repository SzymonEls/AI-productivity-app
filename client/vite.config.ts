// defineConfig comes from vitest rather than vite so the `test` block below
// type-checks. It is the same function for `vite build`; only the typings differ.
import { defineConfig } from "vitest/config";
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

  test: {
    environment: "node",
    // A real IndexedDB implementation rather than a stub: the transaction
    // boundaries in db/mutate.ts are the point of that file, and a stub that
    // ignores them would pass while the thing being tested was broken.
    setupFiles: ["./src/test-setup.ts"],
  },
}));
