<script lang="ts">
  /**
   * Jump to a project by typing part of its name.
   *
   * The navbar palette from base.html, minus the round trip: the project list
   * is already on the device, so filtering is instant and works with no network.
   */
  import type { LocalDatabase } from "../db/schema";
  import { live } from "../lib/live.svelte";
  import { BASE, router } from "../lib/router.svelte";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);

  let visible = $state(false);
  let query = $state("");
  let highlighted = $state(0);
  let field = $state<HTMLInputElement | null>(null);

  const matches = $derived(
    [...projects.value]
      .filter((project) => !project.is_archived)
      .filter((project) => project.title.toLowerCase().includes(query.trim().toLowerCase()))
      .sort(
        (a, b) =>
          Number(b.is_starred) - Number(a.is_starred) ||
          a.title.toLowerCase().localeCompare(b.title.toLowerCase())
      )
      .slice(0, 12)
  );

  /** Opened by the navbar button as well as by the keyboard. */
  export function open(): void {
    visible = true;
    query = "";
    highlighted = 0;
    queueMicrotask(() => field?.focus());
  }

  $effect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        open();
        return;
      }
      if (event.key === "Escape" && visible) visible = false;
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function go(uid: string) {
    visible = false;
    router.go(`${BASE}/projects/${uid}`);
  }

  function onFieldKey(event: KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      highlighted = Math.min(highlighted + 1, matches.length - 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      highlighted = Math.max(highlighted - 1, 0);
    } else if (event.key === "Enter" && matches[highlighted]) {
      event.preventDefault();
      go(matches[highlighted].uid);
    }
  }
</script>

{#if visible}
  <div class="overlay">
    <!-- A real button rather than a clickable div, so closing by clicking away
         is reachable from the keyboard too. -->
    <button
      type="button"
      class="backdrop"
      aria-label="Close the project switcher"
      onclick={() => (visible = false)}
    ></button>

    <div class="palette" role="dialog" aria-label="Jump to a project">
      <input
        bind:this={field}
        bind:value={query}
        onkeydown={onFieldKey}
        type="text"
        placeholder="Jump to a project…"
        aria-label="Project name"
      />
      <ul>
        {#each matches as project, index (project.uid)}
          <li>
            <button type="button" class:on={index === highlighted} onclick={() => go(project.uid)}>
              {project.is_starred ? "★ " : ""}{project.title}
            </button>
          </li>
        {/each}
        {#if matches.length === 0}
          <li class="none">Nothing matches.</li>
        {/if}
      </ul>
    </div>
  </div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; display: grid; place-items: start center; padding: 10vh 1rem 1rem; z-index: 200; }
  .backdrop { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.35); border: 0; padding: 0; cursor: default; }
  .palette { position: relative; background: var(--app-surface, Canvas); color: inherit; border-radius: 0.8rem; width: min(32rem, 100%); padding: 0.6rem; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3); }
  input { width: 100%; font: inherit; background: transparent; color: inherit; border: 1px solid rgba(127, 127, 127, 0.3); border-radius: 0.5rem; padding: 0.5rem 0.65rem; }
  ul { list-style: none; margin: 0.5rem 0 0; padding: 0; max-height: 50vh; overflow: auto; }
  li button { width: 100%; text-align: left; background: none; border: 0; color: inherit; padding: 0.45rem 0.65rem; border-radius: 0.45rem; cursor: pointer; font: inherit; }
  li button.on, li button:hover { background: rgba(127, 127, 127, 0.15); }
  .none { padding: 0.5rem 0.65rem; opacity: 0.6; }
</style>
