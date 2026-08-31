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
  import Icon from "./ui/Icon.svelte";
  import Switcher from "./ui/Switcher.svelte";
  import SyncButton from "./ui/SyncButton.svelte";

  let status = $state<"starting" | "ready" | "failed" | "signedout">("starting");
  let message = $state("");
  let username = $state("");
  let database = $state<LocalDatabase | null>(null);
  let titles = $state(new Map<string, string>());
  let resolving = $state(false);
  let switcher = $state<{ open: () => void } | null>(null);
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
    { href: `${BASE}/`, label: "Home", match: "home", icon: "home" },
    { href: `${BASE}/schedule`, label: "Schedule", match: "schedule", icon: "calendar" },
    { href: `${BASE}/timeline`, label: "Projects", match: "timeline", icon: "folder" },
    { href: `${BASE}/time`, label: "Time tracking", match: "time", icon: "clock" },
    { href: `${BASE}/tags`, label: "Tags", match: "tags", icon: "sparkles" },
    { href: `${BASE}/archive`, label: "Archive", match: "archive", icon: "archive" },
    { href: `${BASE}/new`, label: "New", match: "new", icon: "plus" },
  ];
</script>

<nav class="navbar navbar-expand-lg app-navbar">
  <div class="container">
    <div class="d-flex align-items-center gap-2">
      <a class="app-logo" href={`${BASE}/`} use:link aria-label="Home" title="Home">
        <span class="app-brand-mark" aria-hidden="true">◆</span>
      </a>
      {#if status === "ready"}
        <button
          type="button"
          class="project-switcher-button"
          aria-haspopup="dialog"
          title="Switch project (Ctrl/⌘ K)"
          onclick={() => switcher?.open()}
        >
          <span class="switcher-label">Switch project</span>
          <svg class="switcher-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2.2" stroke-linecap="round"
               stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
          <span class="switcher-kbd" aria-hidden="true">⌘K</span>
        </button>
      {/if}
    </div>

    <div class="collapse navbar-collapse show">
      {#if status === "ready"}
        <div class="navbar-nav me-auto">
          {#each nav as item (item.href)}
            <a
              class="nav-link"
              class:active={route.name === item.match}
              href={item.href}
              use:link
            >
              <Icon name={item.icon} />{item.label}
            </a>
          {/each}
        </div>

        <div class="app-nav-actions ms-auto">
          <SyncButton {titleOf} onresolve={() => (resolving = true)} />

          <button
            type="button"
            class="icon-button theme-toggle"
            title="Toggle theme"
            aria-label="Toggle colour theme"
            onclick={() => toggleTheme()}
          >
            <svg class="theme-toggle-moon" width="17" height="17" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                 aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
            <svg class="theme-toggle-sun" width="17" height="17" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                 aria-hidden="true"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
          </button>

          <button
            type="button"
            class="icon-button safe-mode-toggle"
            aria-pressed={safeMode === "on"}
            title="Safe mode — hide a private project's plan and thoughts"
            onclick={() => (safeMode = toggleSafeMode())}
          >
            <svg class="safe-mode-off" width="17" height="17" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                 aria-hidden="true"><path d="M12 3 5 6v5.5c0 4.2 2.9 7.5 7 9.5 4.1-2 7-5.3 7-9.5V6z"/></svg>
            <svg class="safe-mode-on" width="17" height="17" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                 aria-hidden="true"><path d="M12 3 5 6v5.5c0 4.2 2.9 7.5 7 9.5 4.1-2 7-5.3 7-9.5V6z"/><path d="m8.8 11.8 2.2 2.2 4.2-4.2"/></svg>
          </button>

          <div class="nav-item dropdown">
            <button class="user-menu-button" type="button" title={username}>
              <span class="user-avatar" aria-hidden="true">{username.slice(0, 1)}</span>
              <span class="d-none d-md-inline">{username}</span>
            </button>
          </div>

          <button
            type="button"
            class="btn btn-outline-secondary btn-sm"
            title="Signs out and clears this device's copy"
            onclick={() => database && signOut(database)}
          >Sign out</button>
        </div>
      {/if}
    </div>
  </div>
</nav>

<main class="container app-main">
  {#if status === "signedout"}
    <SignIn onsignedin={() => { status = "starting"; void begin(); }} />
  {:else if status === "starting"}
    <p class="text-muted text-center py-5">Fetching your data…</p>
  {:else if status === "failed"}
    <div class="text-center py-5">
      <h1 class="h5">Could not start</h1>
      <p class="text-muted">{message}</p>
    </div>
  {:else if database}
    {#if route.name === "home"}
      <Home {database} />
    {:else if route.name === "schedule"}
      <Schedule {database} />
    {:else if route.name === "timeline"}
      <Timeline {database} />
    {:else if route.name === "archive"}
      <Archive {database} />
    {:else if route.name === "time"}
      <TimeTracking {database} />
    {:else if route.name === "archived"}
      <Archived {database} />
    {:else if route.name === "new"}
      <NewProject {database} />
    {:else if route.name === "tags"}
      <Tags {database} />
    {:else if route.name === "project"}
      <Project {database} uid={route.uid} />
    {:else}
      <div class="text-center py-5">
        <h1 class="h5">Not here</h1>
        <p class="text-muted">Nothing lives at that address.</p>
        <a href={`${BASE}/`} use:link>Back to today</a>
      </div>
    {/if}
  {/if}
</main>

{#if database}
  <Switcher {database} bind:this={switcher} />
{/if}

{#if resolving && database}
  <ConflictDialog {database} onclose={() => (resolving = false)} />
{/if}

<style>
  /* The application's own stylesheet does the work; this only spaces the page
     below the navbar, which base.html used to do with a body rule. */
  .app-main { padding-top: 1.25rem; padding-bottom: 4rem; }
</style>
