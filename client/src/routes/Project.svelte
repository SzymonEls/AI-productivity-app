<script lang="ts">
  /** One project: its details, its thoughts, and its plan. */
  import { deleteRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { renderPlan } from "../domain/markdown";
  import { NoSuchSection, appendSection, removeSection, sectionRanges } from "../domain/plan-sections";
  import { live } from "../lib/live.svelte";
  import { BASE, router } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project } from "../sync/types";
  import PlanEditor from "../ui/PlanEditor.svelte";
  import PrivateVeil from "../ui/PrivateVeil.svelte";

  let { database, uid }: { database: LocalDatabase; uid: string } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const project = $derived(projects.value.find((candidate) => candidate.uid === uid));

  let editingPlan = $state(false);
  // Which editor: the block editor, or raw Markdown in a textarea. The same
  // localStorage key and the same default the previous frontend used.
  let blockEditor = $state(
    (document.documentElement.getAttribute("data-plan-editor") ?? "blocks") === "blocks"
  );
  let editingDetails = $state(false);
  let planDraft = $state("");
  let details = $state<Partial<Project>>({});
  let notice = $state("");

  const html = $derived(project ? renderPlan(project.long_goal) : "");
  // The renderer emits checkboxes disabled, matching the server. A disabled
  // input dispatches no click, so the attribute goes for display only.
  const interactive = $derived(html.replace(/ disabled(?=[ >])/g, ""));
  const archivedHtml = $derived(project ? renderPlan(project.archived_long_goal) : "");
  const sections = $derived(project ? sectionRanges(project.long_goal) : []);
  const archivedSections = $derived(project ? sectionRanges(project.archived_long_goal) : []);

  async function save(changes: Partial<Project>, message = "") {
    await updateRow<Project>(database, "project", uid, changes);
    if (message) announce(message);
    await sync.refresh();
    void sync.run();
  }

  function announce(message: string) {
    notice = message;
    setTimeout(() => (notice = notice === message ? "" : notice), 4000);
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

  async function savePlan() {
    await save({ long_goal: planDraft }, "Plan saved.");
    editingPlan = false;
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

  async function removeProject() {
    if (!project) return;
    if (!window.confirm(`Delete "${project.title}"? Its tracked time is kept.`)) return;
    await deleteRow(database, "project", uid);
    await sync.refresh();
    void sync.run();
    router.go(BASE);
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

<section class="page">
  {#if !project}
    <p class="muted">No such project in the local copy.</p>
  {:else}
    <header class="head">
      <div class="titles">
        <h1>{project.is_starred ? "★ " : ""}{project.title}</h1>
        <p class="muted">
          {project.frequency || "no cadence"}
          {#if project.daily_target_minutes} · {project.daily_target_minutes} min a day{/if}
          {#if project.is_archived} · archived{/if}
        </p>
      </div>
      <div class="tools">
        <button type="button" class="btn ghost" onclick={startDetails}>Edit details</button>
        <button
          type="button"
          class="btn ghost"
          onclick={() => save({ is_archived: !project.is_archived },
            project.is_archived ? "Restored." : "Archived.")}
        >{project.is_archived ? "Restore" : "Archive"}</button>
        <button type="button" class="btn danger" onclick={removeProject}>Delete</button>
      </div>
    </header>

    {#if notice}<p class="notice">{notice}</p>{/if}

    {#if editingDetails}
      <div class="form">
        <label>Title<input type="text" bind:value={details.title} /></label>
        <label>Cadence<input type="text" bind:value={details.frequency} /></label>
        <label>
          Daily target (minutes)
          <input type="number" min="0" bind:value={details.daily_target_minutes} />
        </label>
        <label class="wide">
          Thoughts
          <textarea rows="3" bind:value={details.short_goal}></textarea>
        </label>
        <label class="check"><input type="checkbox" bind:checked={details.is_starred} /> Starred</label>
        <label class="check"><input type="checkbox" bind:checked={details.is_private} /> Private</label>
        <div class="wide">
          <button type="button" class="btn" onclick={saveDetails}>Save</button>
          <button type="button" class="btn ghost" onclick={() => (editingDetails = false)}>Cancel</button>
        </div>
      </div>
    {:else if project.short_goal}
      <h2 class="section">Thoughts</h2>
      <PrivateVeil projectUid={uid} section="thoughts" isPrivate={project.is_private} label="thoughts">
        <p class="thoughts">{project.short_goal}</p>
      </PrivateVeil>
    {/if}

    <div class="plan-head">
      <h2 class="section">Plan</h2>
      {#if editingPlan}
        <div class="plan-actions">
          <button
            type="button"
            class="btn ghost"
            title="Switch between blocks and raw Markdown"
            onclick={() => {
              blockEditor = !blockEditor;
              planDraft = project.long_goal;
              try {
                localStorage.setItem("app-plan-editor", blockEditor ? "blocks" : "markdown");
              } catch {
                // The choice still holds for this page view.
              }
            }}
          >{blockEditor ? "Markdown" : "Blocks"}</button>
          {#if !blockEditor}
            <button type="button" class="btn" onclick={savePlan}>Save</button>
          {/if}
          <button type="button" class="btn ghost" onclick={() => (editingPlan = false)}>Done</button>
        </div>
      {:else}
        <button
          type="button"
          class="btn ghost"
          onclick={() => {
            planDraft = project.long_goal;
            editingPlan = true;
          }}
        >Edit</button>
      {/if}
    </div>

    <PrivateVeil projectUid={uid} section="plan" isPrivate={project.is_private} label="plan">
      {#if editingPlan && blockEditor}
        <!-- Saves itself as you type; the outbox carries it onward. -->
        {#key uid}
          <PlanEditor
            markdown={project.long_goal}
            onsave={async (next) => {
              await save({ long_goal: next });
              return true;
            }}
          />
        {/key}
      {:else if editingPlan}
        <textarea class="editor" bind:value={planDraft} spellcheck="false"></textarea>
      {:else if project.long_goal.trim()}
        <div class="markdown" role="presentation" onclick={onPlanClick}>{@html interactive}</div>

        {#if sections.length}
          <div class="section-tools">
            <span class="muted small">Archive a finished section:</span>
            {#each sections as heading, index (heading.start)}
              <button type="button" class="chip" onclick={() => archiveSection(index)}>
                {heading.title} ×
              </button>
            {/each}
          </div>
        {/if}
      {:else}
        <p class="muted">This plan is empty.</p>
      {/if}
    </PrivateVeil>

    {#if project.archived_long_goal.trim()}
      <h2 class="section">Archived sections</h2>
      <div class="section-tools">
        {#each archivedSections as heading, index (heading.start)}
          <button type="button" class="chip" onclick={() => restoreSection(index)}>
            ↺ {heading.title}
          </button>
        {/each}
      </div>
      <div class="markdown archived">{@html archivedHtml}</div>
    {/if}
  {/if}
</section>

<style>
  .page { max-width: 54rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  .head { display: flex; justify-content: space-between; gap: 1.5rem; flex-wrap: wrap; align-items: flex-start; }
  h1 { font-size: 1.6rem; margin: 0 0 0.2rem; }
  .muted { opacity: 0.65; }
  .small { font-size: 0.82rem; }
  .thoughts { white-space: pre-wrap; margin: 0.3rem 0 0; }
  .section { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.6; margin: 2rem 0 0.6rem; }
  .plan-head { display: flex; align-items: center; justify-content: space-between; }
  .plan-actions { display: flex; gap: 0.4rem; }
  .tools { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .notice { background: rgba(217, 119, 6, 0.12); border-radius: 0.5rem; padding: 0.5rem 0.75rem; font-size: 0.88rem; }

  .btn { border: 1px solid rgba(127, 127, 127, 0.35); background: var(--bs-primary, #4f46e5); color: #fff; border-radius: 0.5rem; padding: 0.3rem 0.8rem; cursor: pointer; font-size: 0.88rem; }
  .btn.ghost { background: transparent; color: inherit; }
  .btn.danger { background: transparent; color: #b3261e; border-color: rgba(179, 38, 30, 0.4); }

  .form { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); margin-top: 1rem; }
  .form label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem; opacity: 0.75; }
  .form .wide { grid-column: 1 / -1; }
  .form .check { flex-direction: row; align-items: center; gap: 0.4rem; }
  .form input[type="text"], .form input[type="number"], .form textarea {
    font: inherit; background: transparent; color: inherit;
    border: 1px solid rgba(127, 127, 127, 0.35); border-radius: 0.45rem; padding: 0.35rem 0.5rem;
  }

  .editor { width: 100%; min-height: 24rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9rem; padding: 0.75rem; border-radius: 0.6rem; border: 1px solid rgba(127, 127, 127, 0.35); background: transparent; color: inherit; }

  .section-tools { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; margin: 0.75rem 0; }
  .chip { border: 1px solid rgba(127, 127, 127, 0.3); background: transparent; color: inherit; border-radius: 999px; padding: 0.15rem 0.65rem; font-size: 0.8rem; cursor: pointer; }
  .archived { opacity: 0.7; }
  .markdown :global(input.task-list-checkbox) { cursor: pointer; pointer-events: auto; }
</style>
