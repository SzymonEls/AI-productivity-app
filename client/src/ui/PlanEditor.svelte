<script lang="ts">
  /**
   * The block editor, mounted as an island.
   *
   * It manages its own DOM - 1500 lines of contenteditable, drag handles and an
   * undo stack - so Svelte is told to keep out: the container is created empty
   * and never re-rendered while the editor lives inside it. This is the reason
   * the framework choice mattered.
   */
  import { onDestroy, onMount } from "svelte";

  import { mount as mountEditor, type BlockEditor } from "../lib/plan-block-editor";

  let {
    markdown,
    onsave,
  }: { markdown: string; onsave: (markdown: string) => Promise<boolean> } = $props();

  let container = $state<HTMLDivElement | null>(null);
  let editor: BlockEditor | null = null;
  let status = $state("");

  onMount(() => {
    if (!container) return;
    editor = mountEditor(container, {
      initialMarkdown: markdown,
      onSave: onsave,
      onStatus: (next: string) => (status = next),
    });
  });

  onDestroy(() => editor?.destroy?.());

  export function hasUnsavedChanges(): boolean {
    return editor?.hasUnsavedChanges() ?? false;
  }
</script>

<div class="plan-editor">
  <div bind:this={container} class="pbe-root"></div>
  {#if status}<p class="status muted">{status}</p>{/if}
</div>

<style>
  .plan-editor { margin-top: 0.5rem; }
  .status { font-size: 0.8rem; margin: 0.5rem 0 0; }
  .muted { opacity: 0.6; }
</style>
