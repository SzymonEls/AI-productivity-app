<script lang="ts">
  /** Projects put aside, and the way back. */
  import { updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { lastSessionLabel } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project } from "../sync/types";
  import Icon from "../ui/Icon.svelte";

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

<div class="d-flex justify-content-between align-items-center mb-4">
  <div>
    <h1 class="h2 mb-1">Archived Projects</h1>
    <p class="text-muted mb-0">
      Projects you've archived. Restore one to bring it back to your dashboard.
    </p>
  </div>
  <a href={`${BASE}/`} use:link class="btn btn-outline-secondary">Back to home</a>
</div>

{#if archived.length}
  <div class="list-group">
    {#each archived as project (project.uid)}
      <div class="list-group-item d-flex justify-content-between align-items-center flex-wrap gap-2">
        <div>
          <a
            href={`${BASE}/projects/${project.uid}`}
            use:link
            class="fw-semibold text-decoration-none"
          >{project.title}</a>
          <p class="text-muted mb-0 small">
            {lastSessionLabel(project.updated_at).replace("Last session:", "Last modified")}
          </p>
        </div>
        <button type="button" class="btn btn-outline-primary btn-sm" onclick={() => unarchive(project)}>
          <Icon name="restore" />Unarchive
        </button>
      </div>
    {/each}
  </div>
{:else}
  <div class="empty-state text-center p-5 bg-light rounded-3">
    <Icon name="archive" size={40} />
    <h2 class="h4">No archived projects</h2>
    <p class="text-muted mb-0">Projects you archive will show up here.</p>
  </div>
{/if}
