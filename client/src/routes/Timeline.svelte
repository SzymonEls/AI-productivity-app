<script lang="ts">
  /**
   * Projects arranged in columns you drag between, with a backlog for whatever
   * is off the timeline.
   *
   * The server version sent the whole board on every change and deleted
   * everything not in the payload - last-write-wins over the lot, which under
   * synchronisation would turn one dragged card into a conflict about the
   * entire board. Here each card is its own change.
   */
  import { createRow, deleteRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project, TimelineGroup, TimelineItem } from "../sync/types";
  import PrivateVeil from "../ui/PrivateVeil.svelte";

  let { database }: { database: LocalDatabase } = $props();

  const groups = live(() => database.timelineGroups.toArray(), []);
  const items = live(() => database.timelineItems.toArray(), []);
  const projects = live(() => database.projects.toArray(), []);

  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const columns = $derived(
    [...groups.value]
      .filter((group) => !group.is_backlog)
      .sort((a, b) => a.position - b.position)
  );
  const backlog = $derived(groups.value.find((group) => group.is_backlog) ?? null);

  /** Tap a card, then tap a column - HTML5 drag does not fire on a phone. */
  let holding = $state<string | null>(null);
  let notice = $state("");

  function itemsIn(groupUid: string | null): TimelineItem[] {
    return items.value
      .filter((item) => item.group_uid === groupUid)
      .sort((a, b) => a.position - b.position);
  }

  function announce(message: string) {
    notice = message;
    setTimeout(() => (notice = notice === message ? "" : notice), 4000);
  }

  async function after(message = "") {
    if (message) announce(message);
    await sync.refresh();
    void sync.run();
  }

  async function addColumn() {
    const name = window.prompt("Name the column");
    if (!name?.trim()) return;
    await createRow<TimelineGroup>(database, "timeline_group", {
      name: name.trim(),
      position: columns.length,
      is_backlog: false,
    });
    await after("Column added.");
  }

  async function renameColumn(group: TimelineGroup) {
    const name = window.prompt("Rename the column", group.name ?? "");
    if (name === null) return;
    await updateRow<TimelineGroup>(database, "timeline_group", group.uid, { name: name.trim() });
    await after();
  }

  async function removeColumn(group: TimelineGroup) {
    const held = itemsIn(group.uid);
    if (held.length && !window.confirm(`Delete "${group.name}" and its ${held.length} cards?`)) return;

    // Cards go with the column, the way the cascade used to take them.
    for (const item of held) await deleteRow(database, "timeline_item", item.uid);
    await deleteRow(database, "timeline_group", group.uid);
    await after("Column deleted.");
  }

  async function addNote(groupUid: string) {
    const title = window.prompt("What is the note?");
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
    await after("Note added.");
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
    await after("Note is a project now.");
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
    await after("Card removed.");
  }

  function titleOf(item: TimelineItem): string {
    if (item.item_type === "project") {
      return byUid.get(item.project_uid ?? "")?.title ?? "Unknown project";
    }
    return item.title ?? "Note";
  }

  function isPrivate(item: TimelineItem): boolean {
    if (item.item_type === "project") return byUid.get(item.project_uid ?? "")?.is_private ?? false;
    return item.is_private;
  }
</script>

<section class="page">
  <header class="head">
    <h1>Projects</h1>
    <div class="tools">
      {#if holding}
        <span class="hint">Pick a column, or
          <button type="button" class="linkish" onclick={() => (holding = null)}>cancel</button>
        </span>
      {/if}
      <button type="button" class="btn ghost" onclick={addColumn}>Add column</button>
    </div>
  </header>

  {#if notice}<p class="notice">{notice}</p>{/if}

  <div class="board">
    {#each columns as group (group.uid)}
      <section class="column" class:target={holding !== null}>
        <header>
          <button type="button" class="column-name" onclick={() => renameColumn(group)}>
            {group.name || "Untitled"}
          </button>
          <span>
            <button type="button" title="Add a note" onclick={() => addNote(group.uid)}>＋</button>
            <button type="button" title="Delete this column" onclick={() => removeColumn(group)}>×</button>
          </span>
        </header>

        <button type="button" class="dropzone" onclick={() => moveTo(group.uid)} disabled={!holding}>
          Move here
        </button>

        <ul class="cards">
          {#each itemsIn(group.uid) as item (item.uid)}
            <li class="card" class:held={holding === item.uid}>
              <PrivateVeil
                projectUid={item.project_uid ?? item.uid}
                section="plan"
                isPrivate={isPrivate(item)}
                label="card"
              >
                {#if item.item_type === "project" && item.project_uid}
                  <a href={`${BASE}/projects/${item.project_uid}`} use:link>{titleOf(item)}</a>
                {:else}
                  <span>{titleOf(item)}</span>
                {/if}
              </PrivateVeil>
              <span class="card-tools">
                <button type="button" title="Move this card" onclick={() => (holding = item.uid)}>⇄</button>
                {#if item.item_type === "note"}
                  <button type="button" title="Make it a project" onclick={() => noteToProject(item)}>↗</button>
                {/if}
                <button type="button" title="Remove this card" onclick={() => removeItem(item)}>×</button>
              </span>
            </li>
          {/each}
        </ul>
      </section>
    {/each}

    {#if backlog}
      <section class="column backlog">
        <header><span class="column-name">Off the timeline</span></header>
        <button type="button" class="dropzone" onclick={() => moveTo(backlog.uid)} disabled={!holding}>
          Move here
        </button>
        <ul class="cards">
          {#each itemsIn(backlog.uid) as item (item.uid)}
            <li class="card" class:held={holding === item.uid}>
              {#if item.item_type === "project" && item.project_uid}
                <a href={`${BASE}/projects/${item.project_uid}`} use:link>{titleOf(item)}</a>
              {:else}
                <span>{titleOf(item)}</span>
              {/if}
              <span class="card-tools">
                <button type="button" title="Move this card" onclick={() => (holding = item.uid)}>⇄</button>
                <button type="button" title="Remove this card" onclick={() => removeItem(item)}>×</button>
              </span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  </div>
</section>

<style>
  .page { max-width: 76rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  .head { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
  h1 { font-size: 1.6rem; margin: 0; }
  .tools { display: flex; align-items: center; gap: 0.75rem; }
  .hint { font-size: 0.82rem; opacity: 0.75; }
  .notice { background: rgba(217, 119, 6, 0.12); border-radius: 0.5rem; padding: 0.5rem 0.75rem; font-size: 0.88rem; }
  .btn { border: 1px solid rgba(127, 127, 127, 0.35); background: transparent; color: inherit; border-radius: 0.5rem; padding: 0.3rem 0.8rem; cursor: pointer; }
  .linkish { background: none; border: 0; color: inherit; text-decoration: underline; cursor: pointer; font: inherit; }

  .board { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); margin-top: 1rem; align-items: start; }
  .column { border: 1px solid rgba(127, 127, 127, 0.22); border-radius: 0.75rem; padding: 0.6rem; }
  .column.backlog { border-style: dashed; opacity: 0.9; }
  .column header { display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; margin-bottom: 0.5rem; }
  .column-name { background: none; border: 0; color: inherit; font-weight: 600; font-size: 0.9rem; cursor: pointer; padding: 0; text-align: left; }
  .column header button { background: none; border: 0; color: inherit; opacity: 0.55; cursor: pointer; }
  .column header button:hover { opacity: 1; }

  .dropzone { width: 100%; border: 1px dashed rgba(127, 127, 127, 0.4); background: transparent; color: inherit; border-radius: 0.5rem; padding: 0.3rem; font-size: 0.78rem; opacity: 0.75; cursor: pointer; margin-bottom: 0.5rem; }
  .dropzone:disabled { visibility: hidden; height: 0; padding: 0; margin: 0; border: 0; }

  .cards { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.4rem; }
  .card { display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; border: 1px solid rgba(127, 127, 127, 0.25); border-radius: 0.5rem; padding: 0.4rem 0.5rem; font-size: 0.86rem; }
  .card.held { outline: 2px solid var(--bs-primary, #4f46e5); }
  .card a { color: inherit; text-decoration: none; }
  .card a:hover { text-decoration: underline; }
  .card-tools { display: flex; gap: 0.1rem; }
  .card-tools button { background: none; border: 0; color: inherit; opacity: 0.5; cursor: pointer; padding: 0 0.15rem; }
  .card-tools button:hover { opacity: 1; }
</style>
