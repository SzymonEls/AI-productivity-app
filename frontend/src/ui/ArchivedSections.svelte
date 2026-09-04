<script lang="ts">
  /**
   * The sections cut out of a plan, and the way back.
   *
   * There is no table behind this: the archive is text held in
   * archived_long_goal, rendered by the same rules the plan is.
   */
  import { renderPlan } from "../domain/markdown";
  import { sectionRanges } from "../domain/plan-sections";
  import { sectionControls } from "../lib/section-controls";
  import Modal from "./Modal.svelte";

  let {
    markdown,
    onrestore,
    onclose,
  }: { markdown: string; onrestore: (index: number) => void; onclose: () => void } = $props();

  const html = $derived(renderPlan(markdown));
  const sections = $derived(sectionRanges(markdown));
</script>

<Modal label="Archived sections" dialogClass="modal-lg modal-dialog-scrollable" {onclose}>
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
</Modal>
