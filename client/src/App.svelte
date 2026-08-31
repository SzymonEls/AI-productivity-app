<script lang="ts">
  import { onMount } from "svelte";

  import { CURSOR_KEY, readMeta, storeFor } from "./db/schema";
  import { start } from "./boot";
  import { ENTITIES, type EntityName } from "./sync/types";

  let status = $state<"starting" | "ready" | "failed">("starting");
  let message = $state("");
  let username = $state("");
  let cursor = $state(0);
  let offline = $state(false);
  let persisted = $state(false);
  let counts = $state<Record<string, number>>({});
  let firstProjects = $state<string[]>([]);

  onMount(async () => {
    try {
      const { session, pulled } = await start();
      username = session.me.user.username;
      offline = session.offline;
      cursor = pulled?.cursor ?? (await readMeta(session.database, CURSOR_KEY, 0));
      persisted = (await navigator.storage?.persisted?.()) ?? false;

      const tally: Record<string, number> = {};
      for (const entity of ENTITIES as readonly EntityName[]) {
        tally[entity] = await storeFor(session.database, entity).count();
      }
      counts = tally;

      firstProjects = (await session.database.projects.toArray())
        .filter((project) => !project.is_archived)
        .map((project) => project.title)
        .slice(0, 8);

      status = "ready";
    } catch (error) {
      status = "failed";
      message = error instanceof Error ? error.message : String(error);
    }
  });
</script>

<main>
  {#if status === "starting"}
    <p class="muted">Fetching your data…</p>
  {:else if status === "failed"}
    <h1>Could not start</h1>
    <p class="error">{message}</p>
  {:else}
    <h1>Signed in as {username}</h1>
    <p class="muted">
      Cursor {cursor} · storage {persisted ? "persistent" : "best-effort"}
      {#if offline}
        · <strong>offline — read from this device, nothing fetched</strong>
      {/if}
    </p>

    <h2>In the local copy</h2>
    <ul>
      {#each Object.entries(counts) as [entity, total] (entity)}
        <li><code>{entity}</code> — {total}</li>
      {/each}
    </ul>

    <h2>Projects, read from IndexedDB</h2>
    <ul>
      {#each firstProjects as title (title)}
        <li>{title}</li>
      {/each}
    </ul>
    <p class="muted">
      Nothing above touched the network. Pull the cable, reload, and it still reads.
    </p>
  {/if}
</main>

<style>
  main {
    font-family: system-ui, sans-serif;
    max-width: 42rem;
    margin: 3rem auto;
    padding: 0 1.5rem;
    line-height: 1.5;
  }
  h2 {
    margin-top: 2rem;
    font-size: 1rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    opacity: 0.6;
  }
  .muted {
    opacity: 0.65;
  }
  .error {
    color: #b3261e;
  }
  code {
    background: rgba(127, 127, 127, 0.15);
    padding: 0.1em 0.35em;
    border-radius: 0.25rem;
  }
</style>
