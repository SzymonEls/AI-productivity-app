<script lang="ts">
  /**
   * Changing the password.
   *
   * The server rotates the account's session token, which signs every other
   * device out - this browser is signed straight back in, so the person who
   * made the change stays where they are.
   */
  let current = $state("");
  let next = $state("");
  let confirm = $state("");
  let error = $state("");
  let done = $state("");

  function csrf(): string {
    return document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/)?.[1] ?? "";
  }

  async function submit(event: Event) {
    event.preventDefault();
    error = "";
    done = "";

    const response = await fetch("/api/auth/change-password", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-Token": decodeURIComponent(csrf()),
      },
      credentials: "same-origin",
      body: JSON.stringify({
        current_password: current,
        new_password: next,
        confirm_password: confirm,
      }),
    });
    const body = await response.json().catch(() => ({}));

    if (!response.ok) {
      error = body?.message ?? `The server answered ${response.status}.`;
      return;
    }
    done = body.message ?? "Your password has been updated.";
    current = next = confirm = "";
  }
</script>

<div class="row justify-content-center">
  <div class="col-md-6 col-lg-5">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h1 class="h3 mb-4">Change password</h1>

        {#if error}<div class="alert alert-danger py-2">{error}</div>{/if}
        {#if done}<div class="alert alert-success py-2">{done}</div>{/if}

        <form onsubmit={submit}>
          <div class="mb-3">
            <label for="current_password" class="form-label">Current password</label>
            <input
              type="password"
              class="form-control"
              id="current_password"
              autocomplete="current-password"
              bind:value={current}
              required
            />
          </div>
          <div class="mb-3">
            <label for="new_password" class="form-label">New password</label>
            <input
              type="password"
              class="form-control"
              id="new_password"
              autocomplete="new-password"
              bind:value={next}
              required
            />
          </div>
          <div class="mb-3">
            <label for="confirm_password" class="form-label">Confirm new password</label>
            <input
              type="password"
              class="form-control"
              id="confirm_password"
              autocomplete="new-password"
              bind:value={confirm}
              required
            />
          </div>
          <button type="submit" class="btn btn-primary w-100">Update password</button>
        </form>
      </div>
    </div>
  </div>
</div>
