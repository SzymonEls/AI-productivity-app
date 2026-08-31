<script lang="ts">
  import { onDestroy, onMount } from "svelte";

  import { start } from "./boot";
  import type { LocalDatabase } from "./db/schema";
  import { useTimezone } from "./domain/time";
  import { BASE, link, router } from "./lib/router.svelte";
  import Home from "./routes/Home.svelte";
  import Project from "./routes/Project.svelte";
  import Tags from "./routes/Tags.svelte";
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

      router.start();
      await sync.attach(session.database);
      titles = new Map((await session.database.projects.toArray()).map((p) => [p.uid, p.title]));

      status = "ready";
    } catch (error) {
      status = "failed";
      message = error instanceof Error ? error.message : String(error);
    }
  });

  onDestroy(() => sync.detach());

  const titleOf = (uid: string) => titles.get(uid) ?? "";
  const route = $derived(router.current);

  const nav = [
    { href: BASE, label: "Today", match: "home" },
    { href: `${BASE}/tags`, label: "Tags", match: "tags" },
  ];
</script>

<header class="bar">
  <nav class="nav">
    <span class="brand">Productivity</span>
    {#if status === "ready"}
      {#each nav as item (item.href)}
        <a href={item.href} use:link class:active={route.name === item.match}>{item.label}</a>
      {/each}
    {/if}
  </nav>

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
    {#if route.name === "home"}
      <Home {database} />
    {:else if route.name === "tags"}
      <Tags {database} />
    {:else if route.name === "project"}
      <Project {database} uid={route.uid} />
    {:else}
      <div class="centered">
        <h1>Not here</h1>
        <p class="muted">Nothing lives at that address.</p>
        <a href={BASE} use:link>Back to today</a>
      </div>
    {/if}
  {/if}
</main>

<style>
  .bar {
    display: flex; align-items: center; justify-content: space-between; gap: 1rem;
    padding: 0.6rem 1rem; border-bottom: 1px solid rgba(127, 127, 127, 0.2);
    position: sticky; top: 0; background: var(--app-surface, Canvas); z-index: 20;
  }
  .nav { display: flex; align-items: center; gap: 1rem; }
  .brand { font-weight: 700; }
  .nav a { color: inherit; text-decoration: none; opacity: 0.65; font-size: 0.9rem; }
  .nav a.active { opacity: 1; font-weight: 600; }
  .bar-right { display: flex; align-items: center; gap: 0.85rem; }
  .who { opacity: 0.7; font-size: 0.85rem; }
  .link { background: none; border: 0; color: inherit; opacity: 0.7; cursor: pointer; font-size: 0.85rem; }
  .centered { max-width: 40rem; margin: 4rem auto; padding: 0 1rem; text-align: center; }
  .muted { opacity: 0.65; }
</style>
