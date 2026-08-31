<script lang="ts">
  /** A new project, created on this device whether there is a network or not. */
  import { createRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { BASE, router } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project } from "../sync/types";

  let { database }: { database: LocalDatabase } = $props();

  let title = $state("");
  let shortGoal = $state("");
  let frequency = $state("");
  let dailyTarget = $state<number | null>(null);
  let isPrivate = $state(false);
  let isStarred = $state(false);
  let error = $state("");

  async function create() {
    if (!title.trim()) {
      error = "A project needs a title.";
      return;
    }

    const uid = await createRow<Project>(database, "project", {
      title: title.trim(),
      short_goal: shortGoal,
      frequency: frequency,
      long_goal: "",
      archived_long_goal: "",
      daily_target_minutes: dailyTarget,
      is_starred: isStarred,
      is_private: isPrivate,
      is_archived: false,
    });

    await sync.refresh();
    void sync.run();
    router.go(`${BASE}/projects/${uid}`);
  }
</script>

<section class="page">
  <h1>New project</h1>
  {#if error}<p class="error">{error}</p>{/if}

  <div class="form">
    <label class="wide">Title<input type="text" bind:value={title} placeholder="What is it called?" /></label>
    <label class="wide">
      Thoughts
      <textarea rows="3" bind:value={shortGoal} placeholder="What is this for?"></textarea>
    </label>
    <label>Cadence<input type="text" bind:value={frequency} placeholder="Daily, three times a week…" /></label>
    <label>Daily target (minutes)<input type="number" min="0" bind:value={dailyTarget} /></label>
    <label class="check"><input type="checkbox" bind:checked={isStarred} /> Starred</label>
    <label class="check"><input type="checkbox" bind:checked={isPrivate} /> Private</label>
    <div class="wide">
      <button type="button" class="btn" onclick={create}>Create</button>
      <button type="button" class="btn ghost" onclick={() => router.go(BASE)}>Cancel</button>
    </div>
  </div>
</section>

<style>
  .page { max-width: 40rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  h1 { font-size: 1.6rem; margin: 0 0 1rem; }
  .error { color: #b3261e; }
  .form { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }
  .form label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem; opacity: 0.75; }
  .form .wide { grid-column: 1 / -1; }
  .form .check { flex-direction: row; align-items: center; gap: 0.4rem; }
  .form input[type="text"], .form input[type="number"], .form textarea {
    font: inherit; background: transparent; color: inherit;
    border: 1px solid rgba(127, 127, 127, 0.35); border-radius: 0.45rem; padding: 0.4rem 0.5rem;
  }
  .btn { border: 1px solid rgba(127, 127, 127, 0.35); background: var(--bs-primary, #4f46e5); color: #fff; border-radius: 0.5rem; padding: 0.4rem 1rem; cursor: pointer; }
  .btn.ghost { background: transparent; color: inherit; }
</style>
