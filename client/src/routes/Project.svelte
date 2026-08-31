<script lang="ts">
  /**
   * One project: its plan, its thoughts, its cadence.
   *
   * The plan is not behind an edit button. In blocks mode - the default - the
   * editor *is* the view: always editable, saving itself, which is what the
   * "All changes saved" line beside the heading reports. The classic Markdown
   * mode keeps the Edit/Save pair it always had.
   *
   * The veil is the original's: the card carries `private-veiled` and the
   * stylesheet hides its contents while safe mode is on, so nothing shows for a
   * frame before it is covered.
   */
  import { deleteRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { renderPlan } from "../domain/markdown";
  import { NoSuchSection, appendSection, removeSection } from "../domain/plan-sections";
  import { slotsForDate } from "../domain/slots";
  import { lastSessionLabel, today } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link, router } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project } from "../sync/types";
  import PlanEditor from "../ui/PlanEditor.svelte";
  import Planner from "../ui/Planner.svelte";
  import ArchivedSections from "../ui/ArchivedSections.svelte";
  import ProjectSettings from "../ui/ProjectSettings.svelte";
  import ProjectTimer from "../ui/ProjectTimer.svelte";

  let { database, uid }: { database: LocalDatabase; uid: string } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const slots = live(() => database.daySlots.toArray(), []);
  const project = $derived(projects.value.find((candidate) => candidate.uid === uid));

  // Only today's booking, because "done" lives on the slot and so clears itself
  // tomorrow - there is nothing to finish on a day this project is not booked.
  const todaySlot = $derived(
    Object.values(slotsForDate(slots.value, today())).find(
      (booking) => booking?.project_uid === uid
    ) ?? null
  );

  const REVEAL_MINUTES = 5;

  let safeMode = $state(document.documentElement.getAttribute("data-safe-mode") === "on");
  let blocksMode = $state(
    (document.documentElement.getAttribute("data-plan-editor") ?? "blocks") === "blocks"
  );
  let revealed = $state<Record<string, boolean>>({});
  let editing = $state<string | null>(null);
  let draft = $state("");
  let planDraft = $state("");
  let planStatus = $state("");
  let notice = $state("");
  let planning = $state(false);
  let timing = $state(false);
  let menuOpen = $state(false);
  let settingsOpen = $state(false);
  let archiveOpen = $state(false);

  $effect(() => {
    if (!menuOpen) return;
    const close = (event: Event) => {
      const target = event.target as HTMLElement;
      if (!target.closest(".project-detail-actions .dropdown")) menuOpen = false;
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && (menuOpen = false);
    document.addEventListener("pointerdown", close, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", close, true);
      document.removeEventListener("keydown", onKey);
    };
  });

  const html = $derived(project ? renderPlan(project.long_goal) : "");
  const interactive = $derived(html.replace(/ disabled(?=[ >])/g, ""));

  $effect(() => {
    const onSafeMode = () => {
      safeMode = document.documentElement.getAttribute("data-safe-mode") === "on";
      if (safeMode) revealed = {};
    };
    const onEditor = () =>
      (blocksMode = document.documentElement.getAttribute("data-plan-editor") === "blocks");
    window.addEventListener("safe-mode-change", onSafeMode);
    window.addEventListener("plan-editor-change", onEditor);
    return () => {
      window.removeEventListener("safe-mode-change", onSafeMode);
      window.removeEventListener("plan-editor-change", onEditor);
    };
  });

  $effect(() => {
    const now = Date.now();
    const next: Record<string, boolean> = {};
    for (const section of ["plan", "thoughts"]) {
      try {
        next[section] = Number(localStorage.getItem(`app-private-reveal:${uid}:${section}`)) > now;
      } catch {
        next[section] = false;
      }
    }
    revealed = next;
  });

  function veiled(section: string): boolean {
    return Boolean(project?.is_private) && safeMode && !revealed[section];
  }

  function reveal(section: string) {
    revealed = { ...revealed, [section]: true };
    try {
      localStorage.setItem(
        `app-private-reveal:${uid}:${section}`,
        String(Date.now() + REVEAL_MINUTES * 60_000)
      );
    } catch {
      // The reveal still works for this page view.
    }
  }

  function announce(message: string) {
    notice = message;
    setTimeout(() => (notice = notice === message ? "" : notice), 4000);
  }

  async function save(changes: Partial<Project>, message = "") {
    await updateRow<Project>(database, "project", uid, changes);
    if (message) announce(message);
    await sync.refresh();
    void sync.run();
  }

  function startEdit(field: string, value: string) {
    editing = field;
    draft = value;
  }

  async function commit(field: keyof Project) {
    if (field === "title" && !draft.trim()) return announce("A project needs a title.");
    const value =
      field === "daily_target_minutes"
        ? draft.trim()
          ? Number(draft)
          : null
        : field === "title"
          ? draft.trim()
          : draft;
    await save({ [field]: value } as Partial<Project>);
    editing = null;
  }

  /** A finished section leaves the plan and joins the archive - both are text. */
  async function archiveSection(index: number) {
    if (!project) return;
    try {
      const { plan, section } = removeSection(project.long_goal, index);
      await save(
        { long_goal: plan, archived_long_goal: appendSection(project.archived_long_goal, section) },
        "Section archived."
      );
    } catch (error) {
      announce(error instanceof NoSuchSection ? error.message : String(error));
    }
  }

  async function restoreSection(index: number) {
    if (!project) return;
    try {
      const { plan, section } = removeSection(project.archived_long_goal, index);
      await save(
        { archived_long_goal: plan, long_goal: appendSection(project.long_goal, section) },
        "Section restored."
      );
    } catch (error) {
      announce(error instanceof NoSuchSection ? error.message : String(error));
    }
  }

  /** The plan, as a file. It is Markdown in the database, so nothing converts. */
  function downloadMarkdown() {
    if (!project) return;
    const blob = new Blob([project.long_goal], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${project.title.replace(/[^\w\- ]+/g, "").trim() || "plan"}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function removeProject() {
    if (!project) return;
    if (!window.confirm("Delete this project?")) return;
    await deleteRow(database, "project", uid);
    await sync.refresh();
    void sync.run();
    router.go(`${BASE}/`);
  }

  /** Tick a box by rewriting the plan: a ticked box is "[x]" in the Markdown. */
  async function toggleTask(index: number) {
    if (!project) return;
    let seen = -1;
    const lines = project.long_goal.split("\n").map((line) => {
      const match = /^(\s*[-*+]\s+)\[([xX ])\](.*)$/.exec(line);
      if (!match) return line;
      seen += 1;
      if (seen !== index) return line;
      return `${match[1]}[${match[2].toLowerCase() === "x" ? " " : "x"}]${match[3]}`;
    });
    await save({ long_goal: lines.join("\n") });
  }

  function onPlanClick(event: MouseEvent) {
    const target = event.target as HTMLElement;
    if (!target.matches("input.task-list-checkbox")) return;
    const boxes = [...(event.currentTarget as HTMLElement).querySelectorAll("input.task-list-checkbox")];
    void toggleTask(boxes.indexOf(target as HTMLInputElement));
  }
</script>

{#if !project}
  <p class="text-muted">No such project in the local copy.</p>
{:else}
  <header class="project-detail-header mb-4">
    <div class="project-detail-heading min-w-0">
      <div class="d-flex align-items-center gap-2 flex-wrap">
        {#if editing === "title"}
          <div class="project-title-edit">
            <input type="text" class="form-control form-control-lg" bind:value={draft} />
          </div>
          <div class="inline-section-controls">
            <button type="button" class="btn btn-primary btn-sm" onclick={() => commit("title")}>Save</button>
            <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => (editing = null)}>
              Cancel
            </button>
          </div>
        {:else}
          <h1 class="project-detail-title mb-0">{project.title}</h1>
          {#if project.is_starred}<span class="project-badge project-badge-star">★ Starred</span>{/if}
          {#if project.is_private}<span class="project-badge">🔒 Private</span>{/if}
          {#if project.is_archived}<span class="project-badge project-badge-archived">Archived</span>{/if}
          <div class="inline-section-controls">
            <button
              type="button"
              class="btn btn-outline-secondary btn-sm"
              onclick={() => startEdit("title", project.title)}
            ><i class="fa-solid fa-pen me-1" aria-hidden="true"></i>Rename</button>
          </div>
        {/if}
      </div>
      <p class="text-muted mb-0 mt-1">
        {lastSessionLabel(project.updated_at).replace("Last session:", "Last modified")}
      </p>
    </div>

    <div class="project-detail-actions">
      <button type="button" class="btn btn-primary project-timer-toggle" onclick={() => (timing = true)}>
        <i class="fa-regular fa-clock" aria-hidden="true"></i><span>Track time</span>
      </button>
      <button type="button" class="btn btn-outline-secondary" onclick={() => (planning = true)}>
        <i class="fa-regular fa-calendar" aria-hidden="true"></i><span>Plan next session</span>
      </button>

      {#if todaySlot}
        <!-- Only when the project actually has a session today; there is nothing
             to finish otherwise. -->
        <button
          type="button"
          class="btn"
          class:btn-success={todaySlot.is_done}
          class:btn-outline-secondary={!todaySlot.is_done}
          title={`Today's session is in slot ${todaySlot.slot}`}
          onclick={() =>
            updateRow(database, "day_slot", todaySlot.uid, { is_done: !todaySlot.is_done })
              .then(() => sync.refresh())
              .then(() => void sync.run())}
        >
          <i class="fa-regular fa-circle-check" aria-hidden="true"></i><span>{todaySlot.is_done ? "Done" : "Mark done"}</span>
        </button>
      {/if}

      <div class="dropdown">
        <button
          type="button"
          class="btn btn-outline-secondary"
          aria-label="More"
          aria-expanded={menuOpen}
          onclick={() => (menuOpen = !menuOpen)}
        ><i class="fa-solid fa-ellipsis" aria-hidden="true"></i></button>
        {#if menuOpen}
          <ul class="dropdown-menu dropdown-menu-end show">
            <li>
              <button type="button" class="dropdown-item" onclick={() => { menuOpen = false; settingsOpen = true; }}><i class="fa-solid fa-gear" aria-hidden="true"></i>Settings</button>
            </li>
            <li>
              <button type="button" class="dropdown-item" onclick={() => { menuOpen = false; downloadMarkdown(); }}><i class="fa-solid fa-download" aria-hidden="true"></i>Download markdown</button>
            </li>
            <li>
              <button type="button" class="dropdown-item" onclick={() => { menuOpen = false; archiveOpen = true; }}><i class="fa-solid fa-box-archive" aria-hidden="true"></i>Archived sections</button>
            </li>
            <li><a class="dropdown-item" href={`${BASE}/`} use:link onclick={() => (menuOpen = false)}><i class="fa-solid fa-arrow-left" aria-hidden="true"></i>Back to home</a></li>
            <li><hr class="dropdown-divider" /></li>
            <li>
              <button
                type="button"
                class="dropdown-item"
                onclick={() => {
                  menuOpen = false;
                  save({ is_archived: !project.is_archived },
                    project.is_archived ? "Restored." : "Archived.");
                }}
              ><i class="fa-solid fa-box-archive" aria-hidden="true"></i>{project.is_archived ? "Unarchive project" : "Archive project"}</button>
            </li>
            <li>
              <button type="button" class="dropdown-item text-danger" onclick={() => { menuOpen = false; removeProject(); }}><i class="fa-solid fa-trash" aria-hidden="true"></i>Delete project</button>
            </li>
          </ul>
        {/if}
      </div>
    </div>
  </header>

  {#if project.is_archived}
    <div class="alert alert-secondary d-flex justify-content-between align-items-center flex-wrap gap-2">
      <span>This project is archived. It's hidden from your dashboard.</span>
      <button
        type="button"
        class="btn btn-outline-secondary btn-sm"
        onclick={() => save({ is_archived: false }, "Restored.")}
      >Unarchive Project</button>
    </div>
  {/if}

  {#if notice}<div class="alert alert-info py-2">{notice}</div>{/if}

  <div class="project-detail-body">
    <div class="project-plan-col">
      <section
        class="card shadow-sm inline-edit-card project-plan-card"
        class:private-veiled={veiled("plan")}
      >
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-3">
            <div>
              <h2 class="h4 mb-0">Plan</h2>
              <p class="text-muted small mb-0">
                Your working roadmap. Each heading becomes a step on the timeline.
              </p>
            </div>
            {#if blocksMode}
              <span class="plan-save-status" aria-live="polite">{planStatus}</span>
            {:else if editing === "long_goal"}
              <div class="inline-section-controls">
                <button
                  type="button"
                  class="btn btn-primary btn-sm"
                  onclick={async () => {
                    await save({ long_goal: planDraft });
                    editing = null;
                  }}
                >Save</button>
                <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => (editing = null)}>
                  Cancel
                </button>
              </div>
            {:else}
              <div class="inline-section-controls">
                <button
                  type="button"
                  class="btn btn-outline-secondary btn-sm"
                  onclick={() => {
                    planDraft = project.long_goal;
                    editing = "long_goal";
                  }}
                >Edit</button>
              </div>
            {/if}
          </div>

          {#if veiled("plan")}
            <div class="private-veil">
              <!-- The padlock lives here rather than beside the project's name:
                   it says why this card is empty, which is the one place the
                   flag is worth pointing out. -->
              <i class="fa-solid fa-lock private-veil-lock" aria-hidden="true"></i>
              <p class="private-veil-note mb-0">
                This project is private — the plan stays hidden until you ask for it.
              </p>
              <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => reveal("plan")}>
                Show plan
              </button>
            </div>
          {/if}

          <div class="private-hideable">
            {#if blocksMode}
              {#key uid}
                <PlanEditor
                  markdown={project.long_goal}
                  onsave={async (next) => {
                    await save({ long_goal: next });
                    planStatus = "All changes saved";
                    return true;
                  }}
                  onarchivesection={archiveSection}
                />
              {/key}
            {:else if editing === "long_goal"}
              <textarea
                class="form-control inline-edit-textarea long-goal-markdown-field"
                rows="14"
                bind:value={planDraft}
              ></textarea>
            {:else if project.long_goal.trim()}
              <div
                class="markdown-content long-goal-preview"
                role="presentation"
                onclick={onPlanClick}
              >{@html interactive}</div>
            {:else}
              <p class="text-muted mb-0">This plan is empty.</p>
            {/if}
          </div>
        </div>
      </section>

    </div>

    <div class="project-meta-col">
      <section class="card shadow-sm inline-edit-card" class:private-veiled={veiled("thoughts")}>
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start gap-3 mb-3">
            <h2 class="h5 mb-0">Thoughts</h2>
            <div class="inline-section-controls">
              {#if editing === "short_goal"}
                <button type="button" class="btn btn-primary btn-sm" onclick={() => commit("short_goal")}>Save</button>
                <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => (editing = null)}>Cancel</button>
              {:else}
                <button
                  type="button"
                  class="btn btn-outline-secondary btn-sm"
                  onclick={() => startEdit("short_goal", project.short_goal)}
                >Edit</button>
              {/if}
            </div>
          </div>

          {#if veiled("thoughts")}
            <div class="private-veil">
              <i class="fa-solid fa-lock private-veil-lock" aria-hidden="true"></i>
              <p class="private-veil-note mb-0">
                This project is private — the thoughts stay hidden until you ask.
              </p>
              <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => reveal("thoughts")}>
                Show thoughts
              </button>
            </div>
          {/if}

          <div class="private-hideable">
            {#if editing === "short_goal"}
              <textarea class="form-control inline-edit-textarea" rows="4" bind:value={draft}></textarea>
            {:else if project.short_goal.trim()}
              <p class="preserve-lines mb-0">{project.short_goal}</p>
            {:else}
              <p class="text-muted small mb-0">Nothing written here yet.</p>
            {/if}
          </div>
        </div>
      </section>

      <section class="card shadow-sm inline-edit-card mt-3">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start gap-3 mb-3">
            <h2 class="h5 mb-0">Frequency</h2>
            <div class="inline-section-controls">
              {#if editing === "frequency"}
                <button type="button" class="btn btn-primary btn-sm" onclick={() => commit("frequency")}>Save</button>
                <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => (editing = null)}>Cancel</button>
              {:else}
                <button
                  type="button"
                  class="btn btn-outline-secondary btn-sm"
                  onclick={() => startEdit("frequency", project.frequency)}
                >Edit</button>
              {/if}
            </div>
          </div>
          {#if editing === "frequency"}
            <input type="text" class="form-control" bind:value={draft} />
          {:else}
            <p class="preserve-lines mb-0">{project.frequency || "Not set"}</p>
          {/if}
        </div>
      </section>

      <section class="card shadow-sm inline-edit-card mt-3">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start gap-3 mb-3">
            <h2 class="h5 mb-0">Daily target</h2>
            <div class="inline-section-controls">
              {#if editing === "daily_target_minutes"}
                <button type="button" class="btn btn-primary btn-sm" onclick={() => commit("daily_target_minutes")}>Save</button>
                <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => (editing = null)}>Cancel</button>
              {:else}
                <button
                  type="button"
                  class="btn btn-outline-secondary btn-sm"
                  onclick={() =>
                    startEdit("daily_target_minutes", String(project.daily_target_minutes ?? ""))}
                >Edit</button>
              {/if}
            </div>
          </div>
          {#if editing === "daily_target_minutes"}
            <input type="number" min="0" class="form-control" bind:value={draft} placeholder="Minutes" />
          {:else}
            <p class="mb-0">
              {project.daily_target_minutes ? `${project.daily_target_minutes} min` : "No target"}
            </p>
          {/if}
        </div>
      </section>
    </div>
  </div>
{/if}

{#if planning && project}
  <Planner
    {database}
    forProject={{ uid: project.uid, title: project.title }}
    onclose={() => (planning = false)}
  />
{/if}

{#if timing && project}
  <ProjectTimer
    {database}
    projectUid={project.uid}
    projectTitle={project.title}
    onclose={() => (timing = false)}
  />
{/if}

{#if settingsOpen && project}
  <ProjectSettings
    {project}
    onsave={(changes) => save(changes, "Saved.")}
    onclose={() => (settingsOpen = false)}
  />
{/if}

{#if archiveOpen && project}
  <ArchivedSections
    markdown={project.archived_long_goal}
    onrestore={restoreSection}
    onclose={() => (archiveOpen = false)}
  />
{/if}
