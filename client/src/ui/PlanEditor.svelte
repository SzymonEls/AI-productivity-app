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
    onarchivesection,
  }: {
    markdown: string;
    onsave: (markdown: string) => Promise<boolean>;
    onarchivesection?: (index: number) => void;
  } = $props();

  let container = $state<HTMLDivElement | null>(null);
  let editor: BlockEditor | null = null;
  let status = $state("");

  onMount(() => {
    if (!container) return;
    editor = mountEditor(container, {
      initialMarkdown: markdown,
      onSave: onsave,
      onStatus: (next: string) => (status = next),
      onArchiveSection: onarchivesection,
    });
  });

  onDestroy(() => editor?.destroy?.());

  export function hasUnsavedChanges(): boolean {
    return editor?.hasUnsavedChanges() ?? false;
  }

  export function saveStatus(): string {
    return status;
  }
</script>

<div bind:this={container} class="plan-block-editor"></div>

<!-- Exposed rather than drawn here: the card header is where "All changes
     saved" belonged, beside the heading. -->
