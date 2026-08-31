<script lang="ts">
  /**
   * Projects arranged in groups, with a backlog for whatever is off the
   * timeline.
   *
   * The server version sent the whole board on every change and deleted
   * everything not in the payload - last-write-wins over the lot, which under
   * synchronisation would turn one moved card into a conflict about the entire
   * board. Here each card is its own change.
   */
  import { createRow, deleteRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { lastSessionLabel } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project, TimelineGroup, TimelineItem } from "../sync/types";
  import Icon from "../ui/Icon.svelte";

  let { database }: { database: LocalDatabase } = $props();

  const groups = live(() => database.timelineGroups.toArray(), []);
  const items = live(() => database.timelineItems.toArray(), []);
  const projects = live(() => database.projects.toArray(), []);
  const entries = live(() => database.timeEntries.toArray(), []);

  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const columns = $derived(
    [...groups.value].filter((g) => !g.is_backlog).sort((a, b) => a.position - b.position)
  );
  const backlog = $derived(groups.value.find((g) => g.is_backlog) ?? null);

  let holding = $state<string | null>(null);
  let showStats = $state(false);
  // The original kept every control behind an edit toggle, and the layout
  // depends on it: a card that is only a handle and a title has room to read.
  let editing = $state(false);
  let hidePrivate = $state(false);
  let status = $state("");

  const lastSessionOf = $derived.by(() => {
    const latest = new Map<string, string>();
    for (const entry of entries.value) {
      if (!entry.project_uid) continue;
      const seen = latest.get(entry.project_uid);
      if (!seen || entry.started_at > seen) latest.set(entry.project_uid, entry.started_at);
    }
    return latest;
  });

  function itemsIn(groupUid: string | null): TimelineItem[] {
    return items.value
      .filter((item) => item.group_uid === groupUid)
      .filter((item) => !(hidePrivate && isPrivate(item)))
      .filter((item) =>
        item.item_type === "project"
          ? !(byUid.get(item.project_uid ?? "")?.is_archived ?? false)
          : true
      )
      .sort((a, b) => a.position - b.position);
  }

  function isPrivate(item: TimelineItem): boolean {
    return item.item_type === "project"
      ? byUid.get(item.project_uid ?? "")?.is_private ?? false
      : item.is_private;
  }

  function announce(message: string) {
    status = message;
    setTimeout(() => (status = status === message ? "" : status), 4000);
  }

  async function after(message = "") {
    if (message) announce(message);
    await sync.refresh();
    void sync.run();
  }

  async function addGroup() {
    const name = window.prompt("Name the group");
    if (!name?.trim()) return;
    await createRow<TimelineGroup>(database, "timeline_group", {
      name: name.trim(),
      position: columns.length,
      is_backlog: false,
    });
    await after("Group added.");
  }

  async function renameGroup(group: TimelineGroup) {
    const name = window.prompt("Rename the group", group.name ?? "");
    if (name === null) return;
    await updateRow<TimelineGroup>(database, "timeline_group", group.uid, { name: name.trim() });
    await after();
  }

  async function moveGroup(group: TimelineGroup, by: number) {
    const order = [...columns];
    const from = order.findIndex((candidate) => candidate.uid === group.uid);
    const to = from + by;
    if (to < 0 || to >= order.length) return;

    const [moved] = order.splice(from, 1);
    order.splice(to, 0, moved);
    for (const [index, candidate] of order.entries()) {
      if (candidate.position !== index) {
        await updateRow<TimelineGroup>(database, "timeline_group", candidate.uid, {
          position: index,
        });
      }
    }
    await after();
  }

  async function removeGroup(group: TimelineGroup) {
    const held = itemsIn(group.uid);
    if (held.length && !window.confirm(`Remove "${group.name}" and its ${held.length} blocks?`)) return;
    for (const item of held) await deleteRow(database, "timeline_item", item.uid);
    await deleteRow(database, "timeline_group", group.uid);
    await after("Group removed.");
  }

  async function addNote(groupUid: string) {
    const title = window.prompt("What is the block?");
    if (!title?.trim()) return;
    await createRow<TimelineItem>(database, "timeline_item", {
      item_type: "note",
      title: title.trim(),
      body: null,
      is_private: false,
      position: itemsIn(groupUid).length,
      group_uid: groupUid,
      project_uid: null,
    });
    await after("Block added.");
  }

  /** A note that turned out to be real work becomes a project of its own. */
  async function noteToProject(item: TimelineItem) {
    if (item.item_type !== "note" || !item.title) return;
    const projectUid = await createRow<Project>(database, "project", {
      title: item.title,
      short_goal: item.body ?? "",
      frequency: "",
      long_goal: "",
      archived_long_goal: "",
      daily_target_minutes: null,
      is_starred: false,
      is_private: item.is_private,
      is_archived: false,
    });
    await updateRow<TimelineItem>(database, "timeline_item", item.uid, {
      item_type: "project",
      project_uid: projectUid,
      title: null,
      body: null,
    });
    await after("It is a project now.");
  }

  async function moveTo(groupUid: string) {
    if (!holding) return;
    const uid = holding;
    holding = null;
    await updateRow<TimelineItem>(database, "timeline_item", uid, {
      group_uid: groupUid,
      position: itemsIn(groupUid).length,
    });
    await after();
  }

  async function removeItem(item: TimelineItem) {
    await deleteRow(database, "timeline_item", item.uid);
    await after("Block removed.");
  }
</script>

<div class="dashboard-page">
  <section class="dashboard-section dashboard-header-section">
    <div class="d-flex justify-content-between align-items-center gap-3">
      <div class="d-flex align-items-center gap-2">
        <h1 class="h5 mb-0">Your Projects</h1>
        <a href={`${BASE}/archived`} use:link class="btn btn-outline-secondary btn-sm">
          <Icon name="archive" />Archived
        </a>
      </div>
      <a href={`${BASE}/new`} use:link class="btn btn-primary">
        <Icon name="plus" />Create Project
      </a>
    </div>

    <div class="project-view-toolbar dashboard-header-toolbar">
      <div class="timeline-edit-actions">
        <div class="form-check form-switch timeline-private-toggle">
          <input
            class="form-check-input"
            type="checkbox"
            id="hidePrivateTimelineItems"
            bind:checked={hidePrivate}
          />
          <label class="form-check-label small" for="hidePrivateTimelineItems">
            Hide private projects
          </label>
        </div>
        <div class="form-check form-switch timeline-stats-toggle">
          <input
            class="form-check-input"
            type="checkbox"
            id="showProjectStatsTimelineItems"
            bind:checked={showStats}
          />
          <label class="form-check-label small" for="showProjectStatsTimelineItems">
            Show last session &amp; frequency
          </label>
        </div>
        {#if editing}
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick={addGroup}>
            <Icon name="plus" />Add group
          </button>
        {/if}
        <button
          type="button"
          class="btn btn-sm"
          class:btn-outline-primary={!editing}
          class:btn-primary={editing}
          onclick={() => {
            editing = !editing;
            holding = null;
          }}
        >
          <Icon name={editing ? "check" : "pencil"} />{editing ? "Done" : "Edit timeline"}
        </button>
        {#if holding}
          <span class="schedule-status" role="status">
            Pick a group, or
            <button type="button" class="btn btn-link btn-sm p-0" onclick={() => (holding = null)}>
              cancel
            </button>
          </span>
        {:else if status}
          <span class="schedule-status" role="status">{status}</span>
        {/if}
      </div>
    </div>
  </section>

  <section class="project-timeline-panel">
    <div class="project-timeline-layout">
      <section class="dashboard-section project-timeline-section">
        <div class="project-timeline">
          {#each columns as group (group.uid)}
            <section class="timeline-group">
              <div class="timeline-group-marker"></div>
              <div class="timeline-group-content">
                <div class="timeline-group-header">
                  <h2 class="timeline-group-title">{group.name || "Untitled"}</h2>
                  {#if editing}
                    <div class="timeline-group-move">
                      <button
                        type="button"
                        class="btn btn-outline-secondary btn-sm"
                        aria-label="Rename section"
                        onclick={() => renameGroup(group)}
                      ><Icon name="pencil" /></button>
                      <button
                        type="button"
                        class="btn btn-outline-secondary btn-sm"
                        aria-label="Move section up"
                        onclick={() => moveGroup(group, -1)}
                      >↑</button>
                      <button
                        type="button"
                        class="btn btn-outline-secondary btn-sm"
                        aria-label="Move section down"
                        onclick={() => moveGroup(group, 1)}
                      >↓</button>
                    </div>
                    <button
                      type="button"
                      class="btn btn-outline-secondary btn-sm"
                      onclick={() => removeGroup(group)}
                    >Remove</button>
                  {/if}
                </div>

                <div class="timeline-items">
                  {#each itemsIn(group.uid) as item (item.uid)}
                    {@const project = byUid.get(item.project_uid ?? "")}
                    <article
                      class="timeline-item"
                      class:timeline-project-item={item.item_type === "project"}
                      class:timeline-note-item={item.item_type === "note"}
                      class:is-holding={holding === item.uid}
                    >
                      {#if editing}
                        <button
                          type="button"
                          class="timeline-drag-handle"
                          aria-label="Move"
                          onclick={() => (holding = item.uid)}
                        >::</button>
                      {/if}
                      <div class="timeline-item-main">
                        {#if item.item_type === "project" && project}
                          <a
                            class="timeline-item-title"
                            href={`${BASE}/projects/${project.uid}`}
                            use:link
                          >{project.title}</a>
                          {#if showStats}
                            <div class="timeline-item-meta">
                              {#if project.frequency}
                                <span class="timeline-item-text preserve-lines">
                                  {project.frequency}
                                </span>
                              {/if}
                              <span class="manual-last-session">
                                {lastSessionLabel(lastSessionOf.get(project.uid))}
                              </span>
                            </div>
                          {/if}
                        {:else}
                          <strong class="timeline-item-title">{item.title || "Note"}</strong>
                          {#if item.body}
                            <p class="timeline-item-text preserve-lines">{item.body}</p>
                          {/if}
                        {/if}
                      </div>
                      {#if editing}
                        {#if item.item_type === "note"}
                          <button
                            type="button"
                            class="btn btn-outline-primary btn-sm"
                            onclick={() => noteToProject(item)}
                          >Convert to project</button>
                        {/if}
                        <button
                          type="button"
                          class="btn btn-outline-danger btn-sm"
                          onclick={() => removeItem(item)}
                        >Remove</button>
                      {/if}
                    </article>
                  {/each}
                </div>

                <div class="timeline-group-add-actions">
                  {#if editing}
                    <button
                      type="button"
                      class="btn btn-outline-secondary btn-sm timeline-add-note"
                      onclick={() => addNote(group.uid)}
                    >Add text block</button>
                  {/if}
                  {#if holding}
                    <button
                      type="button"
                      class="btn btn-primary btn-sm"
                      onclick={() => moveTo(group.uid)}
                    >Move here</button>
                  {/if}
                </div>
              </div>
            </section>
          {/each}
        </div>
      </section>

      {#if backlog}
        <aside class="dashboard-section timeline-backlog">
          <div class="timeline-backlog-header">
            <h2 class="timeline-backlog-title">Off timeline</h2>
            <p class="timeline-backlog-hint">
              Projects parked outside the timeline. Move blocks here with the ::
              handle.
            </p>
          </div>
          <div class="timeline-items timeline-backlog-items">
            {#each itemsIn(backlog.uid) as item (item.uid)}
              {@const project = byUid.get(item.project_uid ?? "")}
              <article class="timeline-item timeline-project-item" class:is-holding={holding === item.uid}>
                {#if editing}
                  <button
                    type="button"
                    class="timeline-drag-handle"
                    aria-label="Move"
                    onclick={() => (holding = item.uid)}
                  >::</button>
                {/if}
                <div class="timeline-item-main">
                  {#if project}
                    <a class="timeline-item-title" href={`${BASE}/projects/${project.uid}`} use:link>
                      {project.title}
                    </a>
                  {:else}
                    <strong class="timeline-item-title">{item.title || "Note"}</strong>
                  {/if}
                </div>
              </article>
            {/each}
          </div>
          {#if itemsIn(backlog.uid).length === 0}
            <p class="timeline-backlog-empty">No projects off the timeline.</p>
          {/if}
          {#if holding}
            <button type="button" class="btn btn-primary btn-sm" onclick={() => moveTo(backlog.uid)}>
              Move here
            </button>
          {/if}
        </aside>
      {/if}
    </div>
  </section>
</div>
