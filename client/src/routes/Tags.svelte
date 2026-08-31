<script lang="ts">
  /**
   * Every #tag across the active plans.
   *
   * The server version opened on a spinner because it re-read every plan on
   * each request. The plans are already here, so there is nothing to wait for.
   */
  import type { LocalDatabase } from "../db/schema";
  import { collectTags } from "../domain/tags";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import PrivateVeil from "../ui/PrivateVeil.svelte";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const tags = $derived(collectTags(projects.value));
</script>

<section class="page">
  <h1>Tags</h1>
  {#if tags.length === 0}
    <p class="muted">
      No tags yet. Write <code>#something</code> in a list item of a plan and it
      becomes one.
    </p>
  {:else}
    {#each tags as tag (tag.name)}
      <section class="tag">
        <h2><span class="plan-tag">#{tag.name}</span> <span class="muted">{tag.count}</span></h2>
        <ul class="plain">
          {#each tag.items as item (item.projectUid + item.text)}
            <li class:done={item.isDone}>
              <!-- A tag lives in a plan, so a private project's line is covered
                   by the same curtain the plan is. -->
              <PrivateVeil
                projectUid={item.projectUid}
                section="plan"
                isPrivate={item.isPrivate}
                label="line"
              >
                <a href={`${BASE}/projects/${item.projectUid}`} use:link>{item.text}</a>
              </PrivateVeil>
              <span class="muted">{item.projectTitle}</span>
            </li>
          {/each}
        </ul>
      </section>
    {/each}
  {/if}
</section>

<style>
  .page { max-width: 54rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  h1 { font-size: 1.6rem; margin: 0 0 1rem; }
  .tag { margin-bottom: 1.75rem; }
  .tag h2 { font-size: 1rem; margin: 0 0 0.4rem; }
  .plan-tag { color: var(--tag-color, #6d28d9); font-weight: 600; }
  .muted { opacity: 0.6; font-weight: 400; font-size: 0.85rem; }
  .plain { list-style: none; margin: 0; padding: 0; }
  .plain li {
    display: flex; justify-content: space-between; gap: 1rem;
    padding: 0.35rem 0; border-bottom: 1px solid rgba(127, 127, 127, 0.15);
  }
  .plain li.done a { text-decoration: line-through; opacity: 0.55; }
  a { color: inherit; text-decoration: none; }
  a:hover { text-decoration: underline; }
  code { background: rgba(127, 127, 127, 0.15); padding: 0.1em 0.35em; border-radius: 0.25rem; }
</style>
