<script lang="ts">
  /**
   * One project: its details, its thoughts, and its plan.
   *
   * The veil is the original's: the card carries `private-veiled` and the
   * stylesheet hides its contents while safe mode is on, so nothing shows for a
   * frame before it is covered. Revealing drops the class for five minutes.
   */
  import { deleteRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { renderPlan } from "../domain/markdown";
  import { NoSuchSection, appendSection, removeSection, sectionRanges } from "../domain/plan-sections";
  import { lastSessionLabel } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link, router } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project } from "../sync/types";
  import Icon from "../ui/Icon.svelte";
  import PlanEditor from "../ui/PlanEditor.svelte";
  import Planner from "../ui/Planner.svelte";
  import ProjectTimer from "../ui/ProjectTimer.svelte";

  let { database, uid }: { database: LocalDatabase; uid: string } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const project = $derived(projects.value.find((candidate) => candidate.uid === uid));

  const REVEAL_MINUTES = 5;

  let safeMode = $state(document.documentElement.getAttribute("data-safe-mode") === "on");
  let revealed = $state<Record<string, boolean>>({});
  let editingPlan = $state(false);
  let editingDetails = $state(false);
  let details = $state<Partial<Project>>({});
  let notice = $state("");
  let planning = $state(false);
  let timing = $state(false);
  let menuOpen = $state(false);

  const html = $derived(project ? renderPlan(project.long_goal) : "");
  const interactive = $derived(html.replace(/ disabled(?=[ >])/g, ""));
  const archivedHtml = $derived(project ? renderPlan(project.archived_long_goal) : "");
  const sections = $derived(project ? sectionRanges(project.long_goal) : []);
  const archivedSections = $derived(project ? sectionRanges(project.archived_long_goal) : []);

  $effect(() => {
    const onChange = () => {
      safeMode = document.documentElement.getAttribute("data-safe-mode") === "on";
      // Reaching for the shield again drops every reveal.
      if (safeMode) revealed = {};
    };
    window.addEventListener("safe-mode-change", onChange);
    return () => window.removeEventListener("safe-mode-change", onChange);
  });

  $effect(() => {
    const now = Date.now();
    const next: Record<string, boolean> = {};
    for (const section of ["plan", "thoughts"]) {
      try {
        next[section] = Number(localStorage.getItem(`app-private-reveal:${uid}:${section}`)) > now;
      } catch {
        // Private browsing, or storage off: ask every time.
        next[section] = false;
      }
    }
    revealed = next;
  });

  function veiled(section: string): boolean {
    return Boolean(project?.is_private) && safeMode && !revealed[section];
  }

  function reveal(section: string) {
    const until = Date.now() + REVEAL_MINUTES * 60_000;
    revealed = { ...revealed, [section]: true };
    try {
      localStorage.setItem(`app-private-reveal:${uid}:${section}`, String(until));
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

  function startDetails() {
    if (!project) return;
    details = {
      title: project.title,
      short_goal: project.short_goal,
      frequency: project.frequency,
      daily_target_minutes: project.daily_target_minutes,
      is_starred: project.is_starred,
      is_private: project.is_private,
    };
    editingDetails = true;
  }

  async function saveDetails() {
    if (!details.title?.trim()) return announce("A project needs a title.");
    await save({ ...details, title: details.title.trim() }, "Saved.");
    editingDetails = false;
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
    if (!window.confirm(`Delete "${project.title}"? Its tracked time is kept.`)) return;
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
        <h1 class="project-detail-title mb-0">{project.title}</h1>
        {#if project.is_starred}<span class="project-badge project-badge-star">★ Starred</span>{/if}
        {#if project.is_private}<span class="project-badge">🔒 Private</span>{/if}
        {#if project.is_archived}<span class="project-badge project-badge-archived">Archived</span>{/if}
        <div class="inline-section-controls">
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick={startDetails}>
            <Icon name="pencil" />Edit
          </button>
        </div>
      </div>
      <p class="text-muted mb-0 mt-1">
        {lastSessionLabel(project.updated_at).replace("Last session:", "Last modified")}
      </p>
    </div>

    <div class="project-detail-actions">
      <button type="button" class="btn btn-primary project-timer-toggle" onclick={() => (timing = true)}>
        <Icon name="clock" /><span>Track time</span>
      </button>
      <button type="button" class="btn btn-outline-secondary" onclick={() => (planning = true)}>
        <Icon name="calendar" /><span>Plan next session</span>
      </button>

      <div class="dropdown">
        <button
          type="button"
          class="btn btn-outline-secondary"
          aria-label="More"
          aria-expanded={menuOpen}
          onclick={() => (menuOpen = !menuOpen)}
        >⋯</button>
        {#if menuOpen}
          <ul class="dropdown-menu dropdown-menu-end show">
            <li>
              <button type="button" class="dropdown-item" onclick={() => { menuOpen = false; startDetails(); }}>
                Settings
              </button>
            </li>
            <li>
              <button type="button" class="dropdown-item" onclick={() => { menuOpen = false; downloadMarkdown(); }}>
                Download markdown
              </button>
            </li>
            <li><a class="dropdown-item" href={`${BASE}/`} use:link>Back to home</a></li>
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
              >{project.is_archived ? "Unarchive project" : "Archive project"}</button>
            </li>
            <li>
              <button type="button" class="dropdown-item text-danger" onclick={() => { menuOpen = false; removeProject(); }}>
                Delete project
              </button>
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

  {#if editingDetails}
    <section class="card shadow-sm inline-edit-card mb-3">
      <div class="card-body">
        <h2 class="h5 mb-3">Edit project</h2>
        <div class="row g-3">
          <div class="col-12">
            <label class="form-label small text-muted" for="p-title">Title</label>
            <input id="p-title" type="text" class="form-control" bind:value={details.title} />
          </div>
          <div class="col-12">
            <label class="form-label small text-muted" for="p-thoughts">Thoughts</label>
            <textarea id="p-thoughts" class="form-control" rows="3" bind:value={details.short_goal}></textarea>
          </div>
          <div class="col-sm-6">
            <label class="form-label small text-muted" for="p-freq">Cadence</label>
            <input id="p-freq" type="text" class="form-control" bind:value={details.frequency} />
          </div>
          <div class="col-sm-6">
            <label class="form-label small text-muted" for="p-target">Daily target (minutes)</label>
            <input id="p-target" type="number" min="0" class="form-control" bind:value={details.daily_target_minutes} />
          </div>
          <div class="col-12 d-flex gap-3">
            <div class="form-check">
              <input class="form-check-input" type="checkbox" id="p-star" bind:checked={details.is_starred} />
              <label class="form-check-label" for="p-star">Starred</label>
            </div>
            <div class="form-check">
              <input class="form-check-input" type="checkbox" id="p-private" bind:checked={details.is_private} />
              <label class="form-check-label" for="p-private">Private</label>
            </div>
          </div>
          <div class="col-12">
            <button type="button" class="btn btn-primary btn-sm" onclick={saveDetails}>Save</button>
            <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => (editingDetails = false)}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </section>
  {/if}

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
            <div class="inline-section-controls">
              <button
                type="button"
                class="btn btn-outline-secondary btn-sm"
                onclick={() => (editingPlan = !editingPlan)}
              >{editingPlan ? "Done" : "Edit"}</button>
            </div>
          </div>

          {#if veiled("plan")}
            <div class="private-veil">
              <!-- The padlock lives here rather than beside the project's name:
                   it says why this card is empty, which is the one place the
                   flag is worth pointing out. -->
              <span class="private-veil-lock" aria-hidden="true">🔒</span>
              <p class="private-veil-note mb-0">
                This project is private — the plan stays hidden until you ask for it.
              </p>
              <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => reveal("plan")}>
                Show plan
              </button>
            </div>
          {/if}

          <div class="private-hideable">
            {#if editingPlan}
              {#key uid}
                <div class="plan-block-editor">
                  <PlanEditor
                    markdown={project.long_goal}
                    onsave={async (next) => {
                      await save({ long_goal: next });
                      return true;
                    }}
                  />
                </div>
              {/key}
            {:else if project.long_goal.trim()}
              <div
                class="markdown-content long-goal-preview"
                role="presentation"
                onclick={onPlanClick}
              >{@html interactive}</div>

              {#if sections.length}
                <div class="d-flex flex-wrap gap-2 align-items-center mt-3">
                  <span class="text-muted small">Archive a finished section:</span>
                  {#each sections as heading, index (heading.start)}
                    <button
                      type="button"
                      class="btn btn-outline-secondary btn-sm"
                      onclick={() => archiveSection(index)}
                    >{heading.title} ×</button>
                  {/each}
                </div>
              {/if}
            {:else}
              <p class="text-muted mb-0">This plan is empty.</p>
            {/if}
          </div>
        </div>
      </section>

      {#if project.archived_long_goal.trim()}
        <section class="card shadow-sm inline-edit-card mt-3">
          <div class="card-body">
            <h2 class="h5 mb-2">Archived sections</h2>
            <div class="d-flex flex-wrap gap-2 mb-3">
              {#each archivedSections as heading, index (heading.start)}
                <button
                  type="button"
                  class="btn btn-outline-secondary btn-sm"
                  onclick={() => restoreSection(index)}
                >↺ {heading.title}</button>
              {/each}
            </div>
            <div class="markdown-content opacity-75">{@html archivedHtml}</div>
          </div>
        </section>
      {/if}
    </div>

    <div class="project-meta-col">
      <section class="card shadow-sm inline-edit-card" class:private-veiled={veiled("thoughts")}>
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start gap-3 mb-3">
            <h2 class="h5 mb-0">Thoughts</h2>
          </div>

          {#if veiled("thoughts")}
            <div class="private-veil">
              <span class="private-veil-lock" aria-hidden="true">🔒</span>
              <p class="private-veil-note mb-0">
                This project is private — the thoughts stay hidden until you ask.
              </p>
              <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => reveal("thoughts")}>
                Show thoughts
              </button>
            </div>
          {/if}

          <div class="private-hideable">
            {#if project.short_goal.trim()}
              <p class="preserve-lines mb-0">{project.short_goal}</p>
            {:else}
              <p class="text-muted small mb-0">Nothing written here yet.</p>
            {/if}
          </div>
        </div>
      </section>

      <section class="card shadow-sm inline-edit-card mt-3">
        <div class="card-body">
          <h2 class="h5 mb-3">Details</h2>
          <dl class="mb-0">
            <dt class="small text-muted">Cadence</dt>
            <dd>{project.frequency || "—"}</dd>
            <dt class="small text-muted">Daily target</dt>
            <dd class="mb-0">
              {project.daily_target_minutes ? `${project.daily_target_minutes} min` : "—"}
            </dd>
          </dl>
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
