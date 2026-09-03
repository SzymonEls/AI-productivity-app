<script lang="ts">
  /**
   * The settings dialog from base.html: interface style, theme, project layout
   * and which plan editor to use. Every one of them is a browser preference -
   * nothing here reaches the server, and nothing here is synchronised.
   */
  import { type Appearance, chosen, setSetting } from "../lib/appearance";
  import { dismissable } from "../lib/dismiss";
  import Icon from "./Icon.svelte";

  let { onclose }: { onclose: () => void } = $props();

  const GROUPS: {
    key: keyof Appearance;
    icon: string;
    label: string;
    hint: string;
    options: { value: string; label: string }[];
  }[] = [
    {
      key: "ui",
      icon: "sparkles",
      label: "Interface style",
      hint: "“Classic” restores the original look. It is light-only.",
      options: [
        { value: "modern", label: "Modern" },
        { value: "classic", label: "Classic" },
      ],
    },
    {
      key: "theme",
      icon: "contrast",
      label: "Theme",
      hint: "How the app looks. “System” follows your device.",
      options: [
        { value: "light", label: "Light" },
        { value: "dark", label: "Dark" },
        { value: "system", label: "System" },
      ],
    },
    {
      key: "projectLayout",
      icon: "columns",
      label: "Project page layout",
      hint: "Where “Thoughts” and “Details” sit on a project page.",
      options: [
        { value: "sidebar", label: "Beside the plan" },
        { value: "stacked", label: "Above the plan" },
      ],
    },
    {
      key: "planEditor",
      icon: "sparkles",
      label: "Plan editor",
      hint: "“Blocks” is the editor with drag-to-reorder and autosave. “Markdown” is the classic one.",
      options: [
        { value: "blocks", label: "Blocks" },
        { value: "markdown", label: "Markdown" },
      ],
    },
  ];

  let picked = $state<Record<string, string>>(
    Object.fromEntries(GROUPS.map((group) => [group.key, chosen(group.key)]))
  );

  function choose(key: keyof Appearance, value: string) {
    setSetting(key, value);
    picked = { ...picked, [key]: value };
  }
</script>

<div class="modal-backdrop-shim" use:dismissable={onclose}>
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h2 class="modal-title h5">App settings</h2>
        <button type="button" class="btn-close" aria-label="Close" onclick={onclose}></button>
      </div>
      <div class="modal-body">
        {#each GROUPS as group (group.key)}
          <div class="settings-group">
            <div class="settings-label"><Icon name={group.icon} />{group.label}</div>
            <p class="settings-hint">{group.hint}</p>
            <div class="settings-segments" role="group" aria-label={group.label}>
              {#each group.options as option (option.value)}
                <button
                  type="button"
                  class="settings-segment"
                  class:is-active={picked[group.key] === option.value}
                  onclick={() => choose(group.key, option.value)}
                >{option.label}</button>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    </div>
  </div>
</div>

<style>
  /* Bootstrap's modal needs its JavaScript to be positioned; this stands in for
     the backdrop it would have created. */
  .modal-backdrop-shim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: grid;
    place-items: center;
    padding: 1rem;
    z-index: 1055;
  }
  .modal-dialog { margin: 0; width: min(32rem, 100%); }
</style>
