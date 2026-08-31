import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    // A real IndexedDB implementation rather than a stub: the transaction
    // boundaries in db/mutate.ts are the point of that file, and a stub that
    // ignores them would pass while the thing being tested was broken.
    setupFiles: ["./src/test-setup.ts"],
  },
});
