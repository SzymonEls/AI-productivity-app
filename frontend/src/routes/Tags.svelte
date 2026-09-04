<script lang="ts">
  /**
   * Every #tag across the active plans.
   *
   * The server version opened on a spinner because it re-read every plan on
   * each request. The plans are already here, so there is nothing to wait for -
   * the spinner is gone rather than made faster.
   */
  import type { LocalDatabase } from "../db/schema";
  import { TAG_PATTERN } from "../domain/markdown";
  import { collectTags } from "../domain/tags";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import Icon from "../ui/Icon.svelte";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const tags = $derived(collectTags(projects.value));

  let safeMode = $state(document.documentElement.getAttribute("data-safe-mode") === "on");
  $effect(() => {
    const onChange = () =>
      (safeMode = document.documentElement.getAttribute("data-safe-mode") === "on");
    window.addEventListener("safe-mode-change", onChange);
    return () => window.removeEventListener("safe-mode-change", onChange);
  });

  /** The line's own text, with its tags picked out of it. */
  function parts(text: string): { text: string; tag: boolean }[] {
    const out: { text: string; tag: boolean }[] = [];
    let index = 0;

    for (const match of text.matchAll(TAG_PATTERN)) {
      const start = match.index! + match[1].length;
      if (start > index) out.push({ text: text.slice(index, start), tag: false });
      out.push({ text: `#${match[2]}`, tag: true });
      index = start + match[2].length + 1;
    }
    if (index < text.length) out.push({ text: text.slice(index), tag: false });
    return out;
  }
</script>

<div class="dashboard-page tags-page">
  <section class="dashboard-section dashboard-header-section">
    <div class="d-flex justify-content-between align-items-center gap-3 flex-wrap">
      <div class="d-flex align-items-center gap-2">
        <h1 class="h5 mb-0">Tags</h1>
        <span class="text-muted small">
          Everything you marked with a <code>#tag</code> in a plan's list.
        </span>
      </div>
      <a href={`${BASE}/`} use:link class="btn btn-outline-secondary btn-sm">
        <Icon name="home" />Today
      </a>
    </div>
    <p class="schedule-hint">
      Nothing here is stored as a tag — the plans are read as this page opens, so
      what they say now is what you see. Pick a line to go back to where it was
      written.
    </p>
  </section>

  <section class="dashboard-section">
    <div class="tag-list">
      {#if tags.length === 0}
        <p class="planner-status mb-0">
          No tags yet. Write #something in a list item of a plan.
        </p>
      {:else}
        {#each tags as tag (tag.name)}
          <section class="tag-group">
            <h2 class="tag-group-title">
              <span class="plan-tag">#{tag.name}</span>
              <span class="tag-group-count">
                {tag.count === 1 ? "1 item" : `${tag.count} items`}
              </span>
            </h2>
            {#each tag.items as item (item.projectUid + item.text)}
              {@const covered = safeMode && item.isPrivate}
              <!-- A link, not a button: it leads back to the line it came from,
                   and a middle click should open a tab like any other. -->
              <a
                class="tag-item"
                class:is-done={item.isDone && !covered}
                href={`${BASE}/projects/${item.projectUid}`}
                use:link
              >
                <span class="tag-item-text" class:tag-item-covered={covered}>
                  {#if covered}
                    <!-- The line stays behind the curtain safe mode drew over
                         the project; that it exists is not the secret. -->
                    Hidden — private project
                  {:else}
                    {#each parts(item.text) as piece, index (index)}
                      {#if piece.tag}<span class="plan-tag">{piece.text}</span>{:else}{piece.text}{/if}
                    {/each}
                  {/if}
                </span>
                <span class="tag-item-project">{item.projectTitle}</span>
              </a>
            {/each}
          </section>
        {/each}
      {/if}
    </div>
  </section>
</div>
