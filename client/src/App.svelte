<script lang="ts">
  import { onDestroy, onMount } from "svelte";

  import { start } from "./boot";
  import type { LocalDatabase } from "./db/schema";
  import { useTimezone } from "./domain/time";
  import Home from "./routes/Home.svelte";
  import { sync } from "./sync/store.svelte";
  import SyncButton from "./ui/SyncButton.svelte";

  let status = $state<"starting" | "ready" | "failed">("starting");
  let message = $state("");
  let username = $state("");
  let database = $state<LocalDatabase | null>(null);
  let titles = $state(new Map<string, string>());

  onMount(async () => {
    try {
      const { session } = await start();
      useTimezone(session.me.timezone);
      username = session.me.user.username;
      database = session.database;

      await sync.attach(session.database);
      titles = new Map((await session.database.projects.toArray()).map((p) => [p.uid, p.title]));

      status = "ready";
    } catch (error) {
      status = "failed";
      message = error instanceof Error ? error.message : String(error);
    }
  });

  onDestroy(() => sync.detach());

  function titleOf(uid: string): string {
    return titles.get(uid) ?? "";
  }
</script>

<header class="bar">
  <span class="brand">Productivity</span>
  {#if status === "ready"}
    <div class="bar-right">
      <SyncButton {titleOf} />
      <span class="who">{username}</span>
      <form method="post" action="/auth/logout">
        <button type="submit" class="link">Sign out</button>
      </form>
    </div>
  {/if}
</header>

<main>
  {#if status === "starting"}
    <p class="centered muted">Fetching your data…</p>
  {:else if status === "failed"}
    <div class="centered">
      <h1>Could not start</h1>
      <p class="muted">{message}</p>
    </div>
  {:else if database}
    <Home {database} />
  {/if}
</main>

<style>
  .bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.6rem 1rem;
    border-bottom: 1px solid rgba(127, 127, 127, 0.2);
  }
  .brand { font-weight: 700; }
  .bar-right { display: flex; align-items: center; gap: 0.85rem; }
  .who { opacity: 0.7; font-size: 0.85rem; }
  .link { background: none; border: 0; color: inherit; opacity: 0.7; cursor: pointer; font-size: 0.85rem; }
  .centered { max-width: 40rem; margin: 4rem auto; padding: 0 1rem; text-align: center; }
  .muted { opacity: 0.65; }
</style>
