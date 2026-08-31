<script lang="ts">
  /** One project: its details, and its plan. */
  import { updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { renderPlan } from "../domain/markdown";
  import { live } from "../lib/live.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project } from "../sync/types";

  let { database, uid }: { database: LocalDatabase; uid: string } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const project = $derived(projects.value.find((candidate) => candidate.uid === uid));

  let editing = $state(false);
  let draft = $state("");

  const html = $derived(project ? renderPlan(project.long_goal) : "");

  /**
   * The renderer emits the checkboxes disabled, matching what the server sent.
   * A disabled input dispatches no click, so ticking one off would be dead -
   * the attribute is dropped for display only, never in what is stored.
   */
  const interactive = $derived(html.replace(/ disabled(?=[ >])/g, ""));

  async function save(changes: Partial<Project>) {
    await updateRow<Project>(database, "project", uid, changes);
    await sync.refresh();
    void sync.run();
  }

  function startEditing() {
    draft = project?.long_goal ?? "";
    editing = true;
  }

  async function savePlan() {
    await save({ long_goal: draft });
    editing = false;
  }

  /**
   * Tick a checkbox by rewriting the plan, because that is where the state
   * lives - a plan is Markdown, and a ticked box is "[x]" in it.
   */
  async function toggleTask(index: number) {
    if (!project) return;
    let seen = -1;
    const lines = project.long_goal.split("\n").map((line) => {
      const match = /^(\s*[-*+]\s+)\[([xX ])\](.*)$/.exec(line);
      if (!match) return line;
      seen += 1;
      if (seen !== index) return line;
      const next = match[2].toLowerCase() === "x" ? " " : "x";
      return `${match[1]}[${next}]${match[3]}`;
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
      <div>
        <h1>{project.title}</h1>
        {#if project.short_goal}<p class="muted">{project.short_goal}</p>{/if}
      </div>
      <dl class="facts">
        <div><dt>Cadence</dt><dd>{project.frequency || "—"}</dd></div>
        <div>
          <dt>Daily target</dt>
          <dd>{project.daily_target_minutes ? `${project.daily_target_minutes} min` : "—"}</dd>
        </div>
      </dl>
    </header>

    <div class="plan-head">
      <h2 class="section">Plan</h2>
      {#if editing}
        <div>
          <button type="button" class="btn" onclick={savePlan}>Save</button>
          <button type="button" class="btn ghost" onclick={() => (editing = false)}>Cancel</button>
        </div>
      {:else}
        <button type="button" class="btn ghost" onclick={startEditing}>Edit</button>
      {/if}
    </div>

    {#if editing}
      <textarea class="editor" bind:value={draft} spellcheck="false"></textarea>
      <p class="muted small">
        Saved to this device as you press Save; it reaches the server on the next sync.
      </p>
    {:else if project.long_goal.trim()}
      <!-- Rendered by the same rules the server used, so the same styles fit. -->
      <div class="markdown" role="presentation" onclick={onPlanClick}>{@html interactive}</div>
    {:else}
      <p class="muted">This plan is empty.</p>
    {/if}
  {/if}
</section>

<style>
  .page { max-width: 54rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  .head { display: flex; justify-content: space-between; gap: 2rem; flex-wrap: wrap; }
  h1 { font-size: 1.6rem; margin: 0 0 0.25rem; }
  .muted { opacity: 0.65; }
  .small { font-size: 0.82rem; }
  .facts { display: flex; gap: 1.5rem; margin: 0; }
  .facts dt { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.55; }
  .facts dd { margin: 0.1rem 0 0; }
  .section { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.6; margin: 0; }
  .plan-head { display: flex; align-items: center; justify-content: space-between; margin: 2rem 0 0.75rem; }
  .btn { border: 1px solid rgba(127, 127, 127, 0.35); background: var(--bs-primary, #4f46e5); color: #fff; border-radius: 0.5rem; padding: 0.3rem 0.8rem; cursor: pointer; }
  .btn.ghost { background: transparent; color: inherit; }
  .editor { width: 100%; min-height: 24rem; font: inherit; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9rem; padding: 0.75rem; border-radius: 0.6rem; border: 1px solid rgba(127, 127, 127, 0.35); background: transparent; color: inherit; }
  .markdown :global(.project-markdown-section) { border: 1px solid rgba(127, 127, 127, 0.2); border-radius: 0.75rem; padding: 0.9rem 1.1rem; margin-bottom: 0.85rem; }
  .markdown :global(h1) { font-size: 1.15rem; margin: 0 0 0.5rem; }
  .markdown :global(ul) { margin: 0; padding-left: 1.2rem; }
  .markdown :global(li) { margin: 0.2rem 0; }
  .markdown :global(.plan-tag) { color: var(--tag-color, #6d28d9); font-weight: 600; }
  .markdown :global(input.task-list-checkbox) { margin-right: 0.4rem; cursor: pointer; pointer-events: auto; }
</style>
