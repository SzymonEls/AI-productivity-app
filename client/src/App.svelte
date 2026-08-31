<script lang="ts">
  import { onDestroy, onMount } from "svelte";

  import { SignedOut, signOut, start } from "./boot";
  import type { LocalDatabase } from "./db/schema";
  import { useTimezone } from "./domain/time";
  import { readAppearance, toggleSafeMode, toggleTheme } from "./lib/appearance";
  import { BASE, link, router } from "./lib/router.svelte";
  import Home from "./routes/Home.svelte";
  import NewProject from "./routes/NewProject.svelte";
  import Project from "./routes/Project.svelte";
  import Archive from "./routes/Archive.svelte";
  import Archived from "./routes/Archived.svelte";
  import Schedule from "./routes/Schedule.svelte";
  import SignIn from "./routes/SignIn.svelte";
  import TimeTracking from "./routes/TimeTracking.svelte";
  import Tags from "./routes/Tags.svelte";
  import Timeline from "./routes/Timeline.svelte";
  import { sync } from "./sync/store.svelte";
  import ConflictDialog from "./ui/ConflictDialog.svelte";
  import Switcher from "./ui/Switcher.svelte";
  import SyncButton from "./ui/SyncButton.svelte";

  let status = $state<"starting" | "ready" | "failed" | "signedout">("starting");
  let message = $state("");
  let username = $state("");
  let database = $state<LocalDatabase | null>(null);
  let titles = $state(new Map<string, string>());
  let resolving = $state(false);
  let theme = $state(readAppearance().theme);
  let safeMode = $state<"on" | "off">(readAppearance().safeMode);

  async function begin() {
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
      if (error instanceof SignedOut) {
        status = "signedout";
        return;
      }
      status = "failed";
      message = error instanceof Error ? error.message : String(error);
    }
  }

  onMount(begin);

  onDestroy(() => sync.detach());

  const titleOf = (uid: string) => titles.get(uid) ?? "";
  const route = $derived(router.current);

  const nav = [
    { href: `${BASE}/`, label: "Today", match: "home" },
    { href: `${BASE}/schedule`, label: "Schedule", match: "schedule" },
    { href: `${BASE}/timeline`, label: "Projects", match: "timeline" },
    { href: `${BASE}/time`, label: "Time", match: "time" },
    { href: `${BASE}/tags`, label: "Tags", match: "tags" },
    { href: `${BASE}/archive`, label: "Archive", match: "archive" },
    { href: `${BASE}/archived`, label: "Archived", match: "archived" },
    { href: `${BASE}/new`, label: "+ New", match: "new" },
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
      <SyncButton {titleOf} onresolve={() => (resolving = true)} />

      <button
        type="button"
        class="icon"
        title="Toggle theme"
        aria-label="Toggle colour theme"
        onclick={() => (theme = toggleTheme())}
      >{theme === "dark" ? "☀" : "☾"}</button>

      <!-- A curtain, not a lock: it covers a private project's plan and
           thoughts on this screen, in this room. -->
      <button
        type="button"
        class="icon"
        title="Safe mode — hide a private project's plan and thoughts"
        aria-pressed={safeMode === "on"}
        onclick={() => (safeMode = toggleSafeMode())}
      >{safeMode === "on" ? "🛡" : "⛨"}</button>
      <span class="who">{username}</span>
      <button
        type="button"
        class="link"
        title="Signs out and clears this device's copy"
        onclick={() => database && signOut(database)}
      >Sign out</button>
    </div>
  {/if}
</header>

<main>
  {#if status === "signedout"}
    <SignIn onsignedin={() => { status = "starting"; void begin(); }} />
  {:else if status === "starting"}
    <p class="centered muted">Fetching your data…</p>
  {:else if status === "failed"}
    <div class="centered">
      <h1>Could not start</h1>
      <p class="muted">{message}</p>
    </div>
  {:else if database}
    {#if route.name === "home"}
      <Home {database} />
    {:else if route.name === "schedule"}
      <Schedule {database} />
    {:else if route.name === "archive"}
      <Archive {database} />
    {:else if route.name === "time"}
      <TimeTracking {database} />
    {:else if route.name === "timeline"}
      <Timeline {database} />
    {:else if route.name === "new"}
      <NewProject {database} />
    {:else if route.name === "archived"}
      <Archived {database} />
    {:else if route.name === "tags"}
      <Tags {database} />
    {:else if route.name === "project"}
      <Project {database} uid={route.uid} />
    {:else}
      <div class="centered">
        <h1>Not here</h1>
        <p class="muted">Nothing lives at that address.</p>
        <a href={`${BASE}/`} use:link>Back to today</a>
      </div>
    {/if}
  {/if}
</main>

{#if database}
  <Switcher {database} />
{/if}

{#if resolving && database}
  <ConflictDialog {database} onclose={() => (resolving = false)} />
{/if}

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
  .icon { background: none; border: 1px solid rgba(127, 127, 127, 0.3); border-radius: 999px; width: 1.9rem; height: 1.9rem; color: inherit; cursor: pointer; line-height: 1; }
  .icon[aria-pressed="true"] { background: var(--bs-primary, #4f46e5); color: #fff; border-color: transparent; }
  .link { background: none; border: 0; color: inherit; opacity: 0.7; cursor: pointer; font-size: 0.85rem; }
  .centered { max-width: 40rem; margin: 4rem auto; padding: 0 1rem; text-align: center; }
  .muted { opacity: 0.65; }
</style>
