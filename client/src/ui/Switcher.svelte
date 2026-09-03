<script lang="ts">
  /**
   * Jump to a project by typing part of its name.
   *
   * The palette from base.html, minus the round trip: the projects are already
   * on the device, so the list is grouped and filtered here. The markup is the
   * original's, down to the slot letter, the badges and the keyboard hints in
   * the footer, because the stylesheet is written for it.
   */
  import type { LocalDatabase } from "../db/schema";
  import { SLOTS, slotsForDate } from "../domain/slots";
  import { today } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link, router } from "../lib/router.svelte";
  import type { Project } from "../sync/types";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const slots = live(() => database.daySlots.toArray(), []);

  let visible = $state(false);
  let query = $state("");
  let highlighted = $state(0);
  let field = $state<HTMLInputElement | null>(null);
  let results = $state<HTMLDivElement | null>(null);

  const currentUid = $derived(router.current.name === "project" ? router.current.uid : "");

  const active = $derived(
    [...projects.value]
      .filter((project) => !project.is_archived)
      .sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()))
  );

  /** Today's three blocks first, in slot order, then everything else. */
  const groups = $derived.by(() => {
    const byUid = new Map(active.map((project) => [project.uid, project]));
    const booked = slotsForDate(slots.value, today());

    const todays: { project: Project; slot: string }[] = [];
    const seen = new Set<string>();
    for (const letter of SLOTS) {
      const project = byUid.get(booked[letter]?.project_uid ?? "");
      if (!project || seen.has(project.uid)) continue;
      todays.push({ project, slot: letter });
      seen.add(project.uid);
    }

    const rest = active
      .filter((project) => !seen.has(project.uid))
      .map((project) => ({ project, slot: "" }));

    const out: { name: string; entries: { project: Project; slot: string }[] }[] = [];
    if (todays.length) out.push({ name: "Today", entries: todays });
    if (rest.length) out.push({ name: todays.length ? "All projects" : "", entries: rest });
    return out;
  });

  const matches = $derived(
    groups.map((group) => ({
      ...group,
      entries: group.entries.filter((entry) =>
        entry.project.title.toLowerCase().includes(query.trim().toLowerCase())
      ),
    }))
  );
  /** The flat order the arrow keys walk, across the groups on screen. */
  const flat = $derived(matches.flatMap((group) => group.entries));

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
        // The same keystroke shuts it again, as it did on the original.
        if (visible) visible = false;
        else open();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Keep the highlighted row in view when the arrows walk past the fold.
  $effect(() => {
    if (!visible) return;
    void highlighted;
    results
      ?.querySelectorAll(".switcher-item")
      [highlighted]?.scrollIntoView({ block: "nearest" });
  });

  function go(uid: string) {
    visible = false;
    router.go(`${BASE}/projects/${uid}`);
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      visible = false;
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      if (flat.length) highlighted = (highlighted + 1) % flat.length;
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (flat.length) highlighted = (highlighted - 1 + flat.length) % flat.length;
    } else if (event.key === "Enter") {
      const target = flat[highlighted] ?? flat[0];
      if (!target) return;
      event.preventDefault();
      go(target.project.uid);
    }
  }
</script>

<!-- The overlay carries the keys because the arrows have to work from the
     search box as well as from a row: one listener, as the original had. -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  class="switcher-overlay"
  class:is-open={visible}
  role="dialog"
  tabindex="-1"
  aria-modal="true"
  aria-label="Project switcher"
  hidden={!visible}
  onclick={(event) => {
    if (event.target === event.currentTarget) visible = false;
  }}
  onkeydown={onKeydown}
>
  <div class="switcher-panel">
    <div class="switcher-search">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
      </svg>
      <input
        bind:this={field}
        bind:value={query}
        oninput={() => (highlighted = 0)}
        type="text"
        placeholder="Search projects…"
        aria-label="Search projects"
        autocomplete="off"
      />
    </div>

    <div class="switcher-results" bind:this={results}>
      {#each matches as group (group.name)}
        {#if group.entries.length}
          <div class="switcher-group" class:switcher-group-untitled={!group.name}>
            {#if group.name}<div class="switcher-group-label">{group.name}</div>{/if}
            {#each group.entries as entry (entry.project.uid)}
              {@const index = flat.indexOf(entry)}
              <a
                class="switcher-item"
                class:is-current={entry.project.uid === currentUid}
                class:is-active={index === highlighted}
                href={`${BASE}/projects/${entry.project.uid}`}
                use:link
                onclick={() => (visible = false)}
              >
                {#if entry.slot}
                  <span class="switcher-slot" title={`Today's slot ${entry.slot}`}>{entry.slot}</span>
                {:else}
                  <span class="switcher-dot" aria-hidden="true"></span>
                {/if}
                <span class="switcher-title">{entry.project.title}</span>
                {#if entry.project.is_starred}
                  <span class="switcher-badge" title="Starred" aria-hidden="true">★</span>
                {/if}
                {#if entry.project.is_private}
                  <span class="switcher-badge" title="Private" aria-hidden="true">🔒</span>
                {/if}
                {#if entry.project.uid === currentUid}
                  <span class="switcher-current-tag">current</span>
                {/if}
              </a>
            {/each}
          </div>
        {/if}
      {/each}
      {#if flat.length === 0}
        <div class="switcher-empty">No projects match your search.</div>
      {/if}
    </div>

    <div class="switcher-footer">
      <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
      <span><kbd>↵</kbd> open</span>
      <span><kbd>esc</kbd> close</span>
      <a class="ms-auto" href={`${BASE}/timeline`} use:link onclick={() => (visible = false)}>
        All projects →
      </a>
    </div>
  </div>
</div>
