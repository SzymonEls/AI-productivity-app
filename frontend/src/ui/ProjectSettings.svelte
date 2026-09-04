<script lang="ts">
  /**
   * The project's two flags.
   *
   * They live here rather than on the page because neither is something you
   * change while working - and the star's label says what it is for.
   */
  import { untrack } from "svelte";

  import type { Project } from "../sync/types";
  import Modal from "./Modal.svelte";

  let {
    project,
    onsave,
    onclose,
  }: {
    project: Project;
    onsave: (changes: Partial<Project>) => Promise<void>;
    onclose: () => void;
  } = $props();

  // A snapshot on purpose: the dialog is a draft you can cancel, so it must not
  // follow the project while it is open.
  let starred = $state(untrack(() => project.is_starred));
  let isPrivate = $state(untrack(() => project.is_private));
</script>

<Modal label="Project settings" {onclose}>
  <div class="modal-content">
    <div class="modal-header">
      <h2 class="modal-title h5">Project settings</h2>
      <button type="button" class="btn-close" aria-label="Close" onclick={onclose}></button>
    </div>
    <div class="modal-body">
      <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" id="projectStarred" bind:checked={starred} />
        <label class="form-check-label" for="projectStarred">
          Starred (context for AI Daily Planning)
        </label>
      </div>
      <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" id="projectPrivate" bind:checked={isPrivate} />
        <label class="form-check-label" for="projectPrivate">Private project</label>
      </div>
    </div>
    <div class="modal-footer">
      <button type="button" class="btn btn-outline-secondary" onclick={onclose}>Cancel</button>
      <button
        type="button"
        class="btn btn-primary"
        onclick={async () => {
          await onsave({ is_starred: starred, is_private: isPrivate });
          onclose();
        }}
      >Save settings</button>
    </div>
  </div>
</Modal>
