<script lang="ts">
  /** Projects put aside, and the way back. */
  import { updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project } from "../sync/types";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const archived = $derived(
    [...projects.value]
      .filter((project) => project.is_archived)
      .sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()))
  );

  async function unarchive(project: Project) {
    await updateRow<Project>(database, "project", project.uid, { is_archived: false });
    await sync.refresh();
    void sync.run();
  }
</script>

<section class="page">
  <h1>Archived</h1>
  {#if archived.length === 0}
    <p class="muted">Nothing is archived.</p>
  {:else}
    <ul class="plain">
      {#each archived as project (project.uid)}
        <li>
          <a href={`${BASE}/projects/${project.uid}`} use:link>{project.title}</a>
          <button type="button" class="btn" onclick={() => unarchive(project)}>Restore</button>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .page { max-width: 44rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  h1 { font-size: 1.6rem; margin: 0 0 1rem; }
  .muted { opacity: 0.65; }
  .plain { list-style: none; margin: 0; padding: 0; }
  .plain li { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 0.5rem 0; border-bottom: 1px solid rgba(127, 127, 127, 0.15); }
  a { color: inherit; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .btn { border: 1px solid rgba(127, 127, 127, 0.35); background: transparent; color: inherit; border-radius: 0.5rem; padding: 0.25rem 0.7rem; cursor: pointer; font-size: 0.85rem; }
</style>
