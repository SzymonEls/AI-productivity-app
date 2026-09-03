<script lang="ts">
  /** A new project, created on this device whether there is a network or not. */
  import { createRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { autoresize } from "../lib/autoresize";
  import { BASE, router } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { Project } from "../sync/types";

  let { database }: { database: LocalDatabase } = $props();

  let title = $state("");
  let shortGoal = $state("");
  let frequency = $state("");
  let longGoal = $state("");
  let dailyTarget = $state<number | null>(null);
  let isPrivate = $state(false);
  let isStarred = $state(false);
  let error = $state("");
  let created = $state(false);

  const untouched = $derived(
    !title.trim() && !shortGoal.trim() && !frequency.trim() && !longGoal.trim()
  );

  // The form holds the only copy of what has been typed until it is created -
  // the warning the original carried on the same page.
  $effect(() => {
    if (untouched || created) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  });

  async function submit(event: Event) {
    event.preventDefault();
    if (!title.trim()) {
      error = "A project needs a title.";
      return;
    }

    const uid = await createRow<Project>(database, "project", {
      title: title.trim(),
      short_goal: shortGoal,
      frequency,
      long_goal: longGoal,
      archived_long_goal: "",
      daily_target_minutes: dailyTarget,
      is_starred: isStarred,
      is_private: isPrivate,
      is_archived: false,
    });

    created = true;
    await sync.refresh();
    void sync.run();
    router.go(`${BASE}/projects/${uid}`);
  }
</script>

<div class="row justify-content-center">
  <div class="col-lg-8">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h1 class="h3 mb-4">Create Project</h1>

        {#if error}<div class="alert alert-danger py-2">{error}</div>{/if}

        <form onsubmit={submit}>
          <div class="mb-3">
            <label for="title" class="form-label">Project Title</label>
            <input type="text" class="form-control" id="title" bind:value={title} required />
          </div>

          <div class="mb-3">
            <label for="short_goal" class="form-label">Thoughts</label>
            <textarea
              class="form-control"
              id="short_goal"
              rows="4"
              use:autoresize
              bind:value={shortGoal}
            ></textarea>
            <div class="form-text">Notes, reflections, or the next thing on your mind.</div>
          </div>

          <div class="mb-3">
            <label for="frequency" class="form-label">Frequency</label>
            <input
              type="text"
              class="form-control"
              id="frequency"
              bind:value={frequency}
              placeholder="For example: 3 times a week, every weekday, every Saturday morning"
            />
            <div class="form-text">
              A short note about how often you want to come back to this project.
            </div>
          </div>

          <div class="mb-3">
            <label for="long_goal" class="form-label">Plan</label>
            <textarea
              class="form-control"
              id="long_goal"
              rows="6"
              use:autoresize
              bind:value={longGoal}
            ></textarea>
            <div class="form-text">The working project plan. Markdown is supported here.</div>
          </div>

          <div class="mb-3">
            <label for="daily_target" class="form-label">Daily target (minutes)</label>
            <input type="number" min="0" class="form-control" id="daily_target" bind:value={dailyTarget} />
            <div class="form-text">
              Shown on the home page against the time tracked, for slots A and B.
            </div>
          </div>

          <div class="form-check mb-2">
            <input class="form-check-input" type="checkbox" id="is_starred" bind:checked={isStarred} />
            <label class="form-check-label" for="is_starred">Starred</label>
          </div>
          <div class="form-check mb-4">
            <input class="form-check-input" type="checkbox" id="is_private" bind:checked={isPrivate} />
            <label class="form-check-label" for="is_private">
              Private — hidden behind a button while safe mode is on
            </label>
          </div>

          <div class="d-flex gap-2">
            <button type="submit" class="btn btn-primary">Create Project</button>
            <button type="button" class="btn btn-outline-secondary" onclick={() => router.go(`${BASE}/`)}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>
