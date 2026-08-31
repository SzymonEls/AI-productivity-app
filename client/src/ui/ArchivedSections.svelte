<script lang="ts">
  /**
   * The sections cut out of a plan, and the way back.
   *
   * There is no table behind this: the archive is text held in
   * archived_long_goal, rendered by the same rules the plan is.
   */
  import { renderPlan } from "../domain/markdown";
  import { sectionRanges } from "../domain/plan-sections";

  let {
    markdown,
    onrestore,
    onclose,
  }: { markdown: string; onrestore: (index: number) => void; onclose: () => void } = $props();

  const html = $derived(renderPlan(markdown));
  const sections = $derived(sectionRanges(markdown));

  /**
   * The restore buttons are put into the rendered sections after the fact, the
   * way the previous frontend did: the renderer produces the server's markup,
   * and the controls are decoration on top of it.
   */
  function decorate(node: HTMLElement) {
    function place() {
      node.querySelectorAll(".project-markdown-section").forEach((section, index) => {
        if (section.querySelector("[data-restore-section]")) return;

        const button = document.createElement("button");
        button.type = "button";
        button.className = "project-section-archive-button";
        button.dataset.restoreSection = String(index);
        button.title = "Restore section from archive";
        button.setAttribute("aria-label", "Restore section from archive");
        button.innerHTML = '<i class="fa-solid fa-rotate-left" aria-hidden="true"></i>';
        button.addEventListener("click", () => onrestore(index));
        section.querySelector(".project-markdown-section-card")?.appendChild(button);
      });
    }

    place();
    const observer = new MutationObserver(place);
    observer.observe(node, { childList: true, subtree: true });
    return { destroy: () => observer.disconnect() };
  }
</script>

<div class="modal-backdrop-shim">
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
          <div class="markdown-content" use:decorate>{@html html}</div>
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
