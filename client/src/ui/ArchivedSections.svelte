<script lang="ts">
  /**
   * The sections cut out of a plan, and the way back.
   *
   * There is no table behind this: the archive is text held in
   * archived_long_goal, rendered by the same rules the plan is.
   */
  import { renderPlan } from "../domain/markdown";
  import { sectionRanges } from "../domain/plan-sections";
  import { dismissable } from "../lib/dismiss";
  import { sectionControls } from "../lib/section-controls";

  let {
    markdown,
    onrestore,
    onclose,
  }: { markdown: string; onrestore: (index: number) => void; onclose: () => void } = $props();

  const html = $derived(renderPlan(markdown));
  const sections = $derived(sectionRanges(markdown));
</script>

<div class="modal-backdrop-shim" use:dismissable={onclose}>
  <div class="modal-dialog modal-lg modal-dialog-scrollable">
    <div class="modal-content">
      <div class="modal-header">
        <h2 class="modal-title h5">Archived sections</h2>
        <button type="button" class="btn-close" aria-label="Close" onclick={onclose}></button>
      </div>
      <div class="modal-body">
        {#if sections.length === 0}
          <p class="text-muted mb-0">No archived sections.</p>
        {:else}
          <div
            class="markdown-content"
            use:sectionControls={{
              icon: "fa-rotate-left",
              label: "Restore section from archive",
              onpick: onrestore,
            }}
          >{@html html}</div>
        {/if}
      </div>
    </div>
  </div>
</div>

<style>
  .modal-backdrop-shim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: grid;
    place-items: center;
    padding: 1rem;
    z-index: 1055;
  }
  .modal-dialog { margin: 0; width: min(48rem, 100%); max-height: 85vh; }
  .modal-content { max-height: 85vh; }
  .modal-body { overflow-y: auto; }
</style>
