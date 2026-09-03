<script lang="ts">
  /**
   * Projects arranged in groups, with a backlog for whatever is off the
   * timeline.
   *
   * The board edits a draft and writes it on "Save timeline", exactly as the
   * original did - drag a card, rename a group, cancel and nothing happened.
   * What is different is underneath: the server took the whole board and
   * deleted everything not in the payload, which under synchronisation would
   * turn one moved card into a conflict about the entire board. Saving here
   * walks the draft and writes only the rows that actually changed.
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

  /** What a card shows on the board, whether it is saved yet or not. */
  interface Card {
    /** Stable while the draft is open, so a drag can follow one card. */
    key: string;
    uid: string | null;
    type: "project" | "note";
    projectUid: string | null;
    title: string;
    body: string;
    isPrivate: boolean;
    /** A note the person asked to turn into a project when the board saves. */
    convert: boolean;
  }

  interface Column {
    key: string;
    uid: string | null;
    name: string;
    isBacklog: boolean;
    cards: Card[];
  }

  const PRIVATE_LABEL = "(private)";

  const groups = live(() => database.timelineGroups.toArray(), []);
  const items = live(() => database.timelineItems.toArray(), []);
  const projects = live(() => database.projects.toArray(), []);
  const entries = live(() => database.timeEntries.toArray(), []);

  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const liveProjects = $derived(projects.value.filter((project) => !project.is_archived));

  let editing = $state(false);
  let draft = $state<Column[] | null>(null);
  let saving = $state(false);
  let showStats = $state(false);
  let hidePrivate = $state(false);
  let status = $state("");

  // The card being dragged, and the container the pointer is over: the two
  // classes the stylesheet uses to show a drag in progress.
  let draggingKey = $state<string | null>(null);
  let dragOverKey = $state<string | null>(null);

  let nextKey = 0;
  const freshKey = () => `draft-${(nextKey += 1)}`;

  const lastSessionOf = $derived.by(() => {
    const latest = new Map<string, string>();
    for (const entry of entries.value) {
      if (!entry.project_uid) continue;
      const seen = latest.get(entry.project_uid);
      if (!seen || entry.started_at > seen) latest.set(entry.project_uid, entry.started_at);
    }
    return latest;
  });

  /** The board as it stands in the database. */
  function fromStore(): Column[] {
    const cardsOf = (groupUid: string | null): Card[] =>
      items.value
        .filter((item) => item.group_uid === groupUid)
        .filter((item) =>
          item.item_type === "project"
            ? Boolean(byUid.get(item.project_uid ?? "")) &&
              !byUid.get(item.project_uid ?? "")!.is_archived
            : true
        )
        .sort((a, b) => a.position - b.position)
        .map((item) => ({
          key: item.uid,
          uid: item.uid,
          type: item.item_type,
          projectUid: item.project_uid,
          title: item.title ?? "",
          body: item.body ?? "",
          isPrivate: item.is_private,
          convert: false,
        }));

    const columns: Column[] = [...groups.value]
      .filter((group) => !group.is_backlog)
      .sort((a, b) => a.position - b.position)
      .map((group) => ({
        key: group.uid,
        uid: group.uid,
        name: group.name ?? "",
        isBacklog: false,
        cards: cardsOf(group.uid),
      }));

    const stored = groups.value.find((group) => group.is_backlog) ?? null;
    columns.push({
      key: stored?.uid ?? "backlog",
      uid: stored?.uid ?? null,
      name: "",
      isBacklog: true,
      // A card with no group at all belongs off the timeline too - it is what a
      // project created outside the board looks like until it is placed.
      cards: stored ? cardsOf(stored.uid) : cardsOf(null),
    });
    return columns;
  }

  const board = $derived(editing && draft ? draft : fromStore());
  const columns = $derived(board.filter((column) => !column.isBacklog));
  const backlog = $derived(board.find((column) => column.isBacklog) ?? null);
  const hasProjects = $derived(liveProjects.length > 0);

  function announce(message: string) {
    status = message;
    setTimeout(() => (status = status === message ? "" : status), 4000);
  }

  function titleOf(card: Card): string {
    if (card.type !== "project") return card.title || "Note";
    return byUid.get(card.projectUid ?? "")?.title ?? "Project";
  }

  function cardIsPrivate(card: Card): boolean {
    return card.type === "project"
      ? byUid.get(card.projectUid ?? "")?.is_private ?? false
      : card.isPrivate;
  }

  /**
   * Hiding a private project leaves the card where it is and takes its words
   * away, rather than removing it: a gap in the board is itself a hint about
   * what is missing from it.
   */
  function masked(card: Card): boolean {
    return hidePrivate && cardIsPrivate(card);
  }

  // ---------------------------------------------------------------- editing

  function startEditing() {
    draft = fromStore();
    editing = true;
  }

  function cancelEditing() {
    draft = null;
    editing = false;
    draggingKey = null;
  }

  function column(key: string): Column | undefined {
    return draft?.find((entry) => entry.key === key);
  }

  function addGroup() {
    draft?.push({ key: freshKey(), uid: null, name: "", isBacklog: false, cards: [] });
  }

  /**
   * Removing a group keeps its cards: they go to the group beside it, which is
   * what the original did rather than taking the work with the heading.
   */
  function removeGroup(key: string) {
    if (!draft) return;
    const at = draft.findIndex((entry) => entry.key === key);
    const ordinary = draft.filter((entry) => !entry.isBacklog);
    if (at < 0) return;
    if (ordinary.length === 1) {
      draft[at].name = "";
      return;
    }
    const neighbour =
      ordinary[ordinary.indexOf(draft[at]) - 1] ?? ordinary[ordinary.indexOf(draft[at]) + 1];
    neighbour.cards.push(...draft[at].cards);
    draft.splice(at, 1);
  }

  function moveGroup(key: string, by: number) {
    if (!draft) return;
    const ordinary = draft.filter((entry) => !entry.isBacklog);
    const from = ordinary.findIndex((entry) => entry.key === key);
    const to = from + by;
    if (from < 0 || to < 0 || to >= ordinary.length) return;

    const moved = ordinary[from];
    const target = ordinary[to];
    const a = draft.indexOf(moved);
    const b = draft.indexOf(target);
    draft.splice(a, 1);
    draft.splice(b, 0, moved);
  }

  function addNote(key: string) {
    column(key)?.cards.push({
      key: freshKey(),
      uid: null,
      type: "note",
      projectUid: null,
      title: "Note",
      body: "",
      isPrivate: false,
      convert: false,
    });
  }

  /** A project written straight onto the board: a note that converts on save. */
  function addProject(key: string) {
    column(key)?.cards.push({
      key: freshKey(),
      uid: null,
      type: "note",
      projectUid: null,
      title: "",
      body: "",
      isPrivate: false,
      convert: true,
    });
  }

  function removeCard(cardKey: string) {
    for (const entry of draft ?? []) {
      const at = entry.cards.findIndex((card) => card.key === cardKey);
      if (at >= 0) {
        entry.cards.splice(at, 1);
        return;
      }
    }
  }

  function convertCard(card: Card) {
    card.convert = true;
  }

  // ------------------------------------------------------------ drag & drop

  function pull(cardKey: string): Card | null {
    for (const entry of draft ?? []) {
      const at = entry.cards.findIndex((card) => card.key === cardKey);
      if (at >= 0) return entry.cards.splice(at, 1)[0];
    }
    return null;
  }

  function onDragStart(event: DragEvent, cardKey: string) {
    if (!editing) {
      event.preventDefault();
      return;
    }
    draggingKey = cardKey;
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
  }

  function onDragEnd() {
    draggingKey = null;
    dragOverKey = null;
  }

  /** The card whose centre is nearest the pointer - the original's rule. */
  function nearestKey(container: HTMLElement, x: number, y: number): string | null {
    let closest: string | null = null;
    let distance = Number.POSITIVE_INFINITY;

    for (const node of container.querySelectorAll<HTMLElement>("[data-card-key]")) {
      if (node.dataset.cardKey === draggingKey) continue;
      const box = node.getBoundingClientRect();
      const away = Math.hypot(box.left + box.width / 2 - x, box.top + box.height / 2 - y);
      if (away < distance) {
        distance = away;
        closest = node.dataset.cardKey ?? null;
      }
    }
    return closest;
  }

  function onDragOver(event: DragEvent, columnKey: string) {
    if (!editing || !draggingKey || !draft) return;
    const target = column(columnKey);
    const held = draft.flatMap((entry) => entry.cards).find((card) => card.key === draggingKey);
    if (!target || !held) return;
    // Only a project can be parked off the timeline; a note stays on it.
    if (target.isBacklog && held.type !== "project") return;

    event.preventDefault();
    dragOverKey = columnKey;

    const before = nearestKey(event.currentTarget as HTMLElement, event.clientX, event.clientY);
    const card = pull(draggingKey);
    if (!card) return;
    const at = before ? target.cards.findIndex((entry) => entry.key === before) : -1;
    target.cards.splice(at < 0 ? target.cards.length : at, 0, card);
  }

  function onDragLeave(event: DragEvent, columnKey: string) {
    const container = event.currentTarget as HTMLElement;
    if (!container.contains(event.relatedTarget as Node) && dragOverKey === columnKey) {
      dragOverKey = null;
    }
  }

  // ----------------------------------------------------------------- saving

  /** Only the fields that actually differ, so a save writes as little as it can. */
  function changed<T extends object>(stored: T | undefined, wanted: Partial<T>): Partial<T> | null {
    if (!stored) return wanted;
    const diff: Partial<T> = {};
    for (const [field, value] of Object.entries(wanted) as [keyof T, T[keyof T]][]) {
      if (stored[field] !== value) diff[field] = value;
    }
    return Object.keys(diff).length ? diff : null;
  }

  async function saveBoard() {
    if (!draft) return;
    saving = true;
    try {
      const storedGroups = new Map(groups.value.map((group) => [group.uid, group]));
      const storedItems = new Map(items.value.map((item) => [item.uid, item]));
      const keptGroups = new Set<string>();
      const keptItems = new Set<string>();
      let position = 0;

      for (const entry of draft) {
        let groupUid = entry.uid;

        if (entry.isBacklog) {
          if (!groupUid && entry.cards.length) {
            groupUid = await createRow<TimelineGroup>(database, "timeline_group", {
              name: "",
              // Past every ordinary group, so it never lands between them.
              position: draft.length,
              is_backlog: true,
            });
          }
        } else if (!groupUid) {
          groupUid = await createRow<TimelineGroup>(database, "timeline_group", {
            name: entry.name.trim(),
            position,
            is_backlog: false,
          });
          position += 1;
        } else {
          const changes = changed(storedGroups.get(groupUid), {
            name: entry.name.trim(),
            position,
          });
          if (changes) {
            await updateRow<TimelineGroup>(database, "timeline_group", groupUid, changes);
          }
          position += 1;
        }

        if (!groupUid) continue;
        keptGroups.add(groupUid);

        for (const [index, card] of entry.cards.entries()) {
          let projectUid = card.projectUid;
          let type = card.type;

          if (card.convert && type === "note") {
            projectUid = await createRow<Project>(database, "project", {
              title: card.title.trim() || "Untitled project",
              short_goal: card.body.trim(),
              frequency: "",
              long_goal: "",
              archived_long_goal: "",
              daily_target_minutes: null,
              is_starred: false,
              is_private: card.isPrivate,
              is_archived: false,
            });
            type = "project";
          }

          const wanted = {
            item_type: type,
            title: type === "project" ? null : card.title.trim() || null,
            body: type === "project" ? null : card.body.trim() || null,
            is_private: type === "project" ? false : card.isPrivate,
            position: index,
            group_uid: groupUid,
            project_uid: projectUid,
          } satisfies Partial<TimelineItem>;

          if (!card.uid) {
            keptItems.add(await createRow<TimelineItem>(database, "timeline_item", wanted));
            continue;
          }
          keptItems.add(card.uid);
          const changes = changed(storedItems.get(card.uid), wanted);
          if (changes) await updateRow<TimelineItem>(database, "timeline_item", card.uid, changes);
        }
      }

      for (const item of items.value) {
        if (!keptItems.has(item.uid)) await deleteRow(database, "timeline_item", item.uid);
      }
      for (const group of groups.value) {
        if (!keptGroups.has(group.uid)) await deleteRow(database, "timeline_group", group.uid);
      }

      draft = null;
      editing = false;
      announce("Timeline saved.");
      await sync.refresh();
      void sync.run();
    } finally {
      saving = false;
    }
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

    {#if hasProjects}
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
            <button
              type="button"
              class="btn btn-primary btn-sm"
              disabled={saving}
              onclick={saveBoard}
            ><Icon name="check" />Save timeline</button>
            <button
              type="button"
              class="btn btn-outline-secondary btn-sm"
              disabled={saving}
              onclick={cancelEditing}
            ><Icon name="x" />Cancel</button>
          {:else}
            <button type="button" class="btn btn-outline-primary btn-sm" onclick={startEditing}>
              <Icon name="pencil" />Edit timeline
            </button>
          {/if}
          {#if status}<span class="schedule-status" role="status">{status}</span>{/if}
        </div>
      </div>
    {/if}
  </section>

  {#if !hasProjects}
    <div class="empty-state text-center p-5 bg-light rounded-3">
      <Icon name="inbox" size={40} />
      <h2 class="h4">No projects yet</h2>
      <p class="text-muted">Create your first project to start organizing your goals.</p>
      <a href={`${BASE}/new`} use:link class="btn btn-primary">
        <Icon name="plus" />Create Your First Project
      </a>
    </div>
  {:else}
    <section class="project-timeline-panel" class:is-editing={editing}>
      <div class="project-timeline-layout">
        <section class="dashboard-section project-timeline-section">
          <div class="project-timeline" class:is-editing={editing}>
            {#each columns as group, index (group.key)}
              <section class="timeline-group">
                <div class="timeline-group-marker"></div>
                <div class="timeline-group-content">
                  <div class="timeline-group-header" class:d-none={!editing && !group.name}>
                    {#if editing}
                      <input
                        class="form-control form-control-sm timeline-group-name"
                        bind:value={group.name}
                        placeholder="Group name"
                        aria-label="Group name"
                      />
                      <div class="timeline-group-move">
                        <button
                          type="button"
                          class="btn btn-outline-secondary btn-sm"
                          aria-label="Move section up"
                          disabled={index === 0}
                          onclick={() => moveGroup(group.key, -1)}
                        >↑</button>
                        <button
                          type="button"
                          class="btn btn-outline-secondary btn-sm"
                          aria-label="Move section down"
                          disabled={index === columns.length - 1}
                          onclick={() => moveGroup(group.key, 1)}
                        >↓</button>
                      </div>
                      <button
                        type="button"
                        class="btn btn-outline-secondary btn-sm"
                        onclick={() => removeGroup(group.key)}
                      >Remove</button>
                    {:else if group.name}
                      <h2 class="timeline-group-title">{group.name}</h2>
                    {/if}
                  </div>

                  <!-- svelte-ignore a11y_no_static_element_interactions -->
                  <div
                    class="timeline-items"
                    class:is-drag-over={dragOverKey === group.key}
                    ondragover={(event) => onDragOver(event, group.key)}
                    ondragleave={(event) => onDragLeave(event, group.key)}
                    ondrop={(event) => {
                      event.preventDefault();
                      dragOverKey = null;
                    }}
                  >
                    {#each group.cards as card (card.key)}
                      {@render timelineCard(card)}
                    {/each}
                  </div>

                  {#if editing}
                    <div class="timeline-group-add-actions">
                      <button
                        type="button"
                        class="btn btn-outline-secondary btn-sm timeline-add-note"
                        onclick={() => addNote(group.key)}
                      >Add text block</button>
                      <button
                        type="button"
                        class="btn btn-outline-secondary btn-sm timeline-add-project"
                        onclick={() => addProject(group.key)}
                      >Add project</button>
                    </div>
                  {/if}
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
                Projects parked outside the timeline. Drag items here while editing.
              </p>
            </div>
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div
              class="timeline-items timeline-backlog-items"
              class:is-editing={editing}
              class:is-drag-over={dragOverKey === backlog.key}
              ondragover={(event) => onDragOver(event, backlog.key)}
              ondragleave={(event) => onDragLeave(event, backlog.key)}
              ondrop={(event) => {
                event.preventDefault();
                dragOverKey = null;
              }}
            >
              {#each backlog.cards as card (card.key)}
                {@render timelineCard(card)}
              {/each}
            </div>
            {#if backlog.cards.length === 0}
              <p class="timeline-backlog-empty">No projects off the timeline.</p>
            {/if}
          </aside>
        {/if}
      </div>
    </section>
  {/if}
</div>

{#snippet timelineCard(card: Card)}
  {@const project = byUid.get(card.projectUid ?? "")}
  <article
    class="timeline-item"
    class:timeline-project-item={card.type === "project"}
    class:timeline-note-item={card.type === "note"}
    class:timeline-project-draft-item={card.type === "note" && card.convert}
    class:is-converting-to-project={card.type === "note" && card.convert}
    class:is-private-masked={masked(card)}
    class:is-dragging={draggingKey === card.key}
    data-card-key={card.key}
    draggable={editing}
    ondragstart={(event) => onDragStart(event, card.key)}
    ondragend={onDragEnd}
  >
    {#if editing}
      <button type="button" class="timeline-drag-handle" aria-label="Move">::</button>
    {/if}

    <div class="timeline-item-main">
      {#if card.type === "project"}
        <!-- While editing, the title is a label rather than a way off the page. -->
        <a
          class="timeline-item-title"
          href={`${BASE}/projects/${card.projectUid}`}
          use:link
          onclick={(event) => editing && event.preventDefault()}
        >{masked(card) ? PRIVATE_LABEL : titleOf(card)}</a>
        {#if showStats && project}
          <div class="timeline-item-meta">
            {#if project.frequency}
              <span class="timeline-item-text preserve-lines">{project.frequency}</span>
            {/if}
            <span class="manual-last-session">
              {lastSessionLabel(lastSessionOf.get(project.uid))}
            </span>
          </div>
        {/if}
      {:else if editing}
        <div class="timeline-note-fields">
          <input
            class="form-control form-control-sm"
            bind:value={card.title}
            placeholder={card.convert ? "Project name" : ""}
            aria-label="Note title"
          />
          <textarea
            class="form-control form-control-sm"
            rows="2"
            bind:value={card.body}
            placeholder={card.convert ? "Short goal / description (optional)" : ""}
            aria-label="Note content"
          ></textarea>
          <div class="form-check timeline-note-privacy">
            <input
              class="form-check-input"
              type="checkbox"
              bind:checked={card.isPrivate}
              aria-label="Mark block as private"
            />
            <!-- svelte-ignore a11y_label_has_associated_control -->
            <label class="form-check-label small">Private</label>
          </div>
        </div>
      {:else}
        <strong class="timeline-item-title">
          {masked(card) ? PRIVATE_LABEL : card.title || "Note"}
        </strong>
        {#if card.body && !masked(card)}
          <p class="timeline-item-text preserve-lines">{card.body}</p>
        {/if}
      {/if}
    </div>

    {#if editing && card.type === "note"}
      <button
        type="button"
        class="btn btn-outline-primary btn-sm"
        disabled={card.convert}
        onclick={() => convertCard(card)}
      >{card.convert ? "Will become project" : "Convert to project"}</button>
      <button
        type="button"
        class="btn btn-outline-danger btn-sm"
        onclick={() => removeCard(card.key)}
      >Delete</button>
    {/if}
  </article>
{/snippet}
