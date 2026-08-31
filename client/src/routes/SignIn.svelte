<script lang="ts">
  /**
   * Signing in, inside the application.
   *
   * The account lockout is not enforced here - it lives on the server, counting
   * failures per email address, and this only reports what it says.
   */
  let { onsignedin }: { onsignedin: () => void } = $props();

  type Mode = "signin" | "register";

  let mode = $state<Mode>("signin");
  let email = $state("");
  let username = $state("");
  let password = $state("");
  let confirmPassword = $state("");
  let remember = $state(true);
  let error = $state("");
  let busy = $state(false);

  async function submit(event: Event) {
    event.preventDefault();
    if (busy) return;

    busy = true;
    error = "";

    const url = mode === "signin" ? "/api/auth/login" : "/api/auth/register";
    const body =
      mode === "signin"
        ? { email, password, remember }
        : { username, email, password, confirm_password: confirmPassword };

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const answer = await response.json().catch(() => ({}));

      if (!response.ok) {
        error = answer?.message ?? `The server answered ${response.status}.`;
        return;
      }
      onsignedin();
    } catch {
      error = "Could not reach the server. Check your connection.";
    } finally {
      busy = false;
    }
  }
</script>

<div class="wrap">
  <form class="card" onsubmit={submit}>
    <h1>{mode === "signin" ? "Sign in" : "Create an account"}</h1>
    {#if error}<p class="error">{error}</p>{/if}

    {#if mode === "register"}
      <label>
        Username
        <input type="text" bind:value={username} autocomplete="username" required />
      </label>
    {/if}

    <label>
      Email
      <input type="email" bind:value={email} autocomplete="email" required />
    </label>

    <label>
      Password
      <input
        type="password"
        bind:value={password}
        autocomplete={mode === "signin" ? "current-password" : "new-password"}
        required
      />
    </label>

    {#if mode === "register"}
      <label>
        Confirm password
        <input type="password" bind:value={confirmPassword} autocomplete="new-password" required />
      </label>
    {:else}
      <label class="check">
        <input type="checkbox" bind:checked={remember} /> Remember me
      </label>
    {/if}

    <button type="submit" class="btn" disabled={busy}>
      {busy ? "Working…" : mode === "signin" ? "Sign in" : "Create account"}
    </button>

    <button
      type="button"
      class="linkish"
      onclick={() => {
        mode = mode === "signin" ? "register" : "signin";
        error = "";
      }}
    >
      {mode === "signin" ? "Need an account? Register" : "Already have an account? Sign in"}
    </button>
  </form>
</div>

<style>
  .wrap { min-height: 100vh; display: grid; place-items: center; padding: 1.5rem; }
  .card { width: min(24rem, 100%); display: grid; gap: 0.85rem; border: 1px solid rgba(127, 127, 127, 0.22); border-radius: 0.9rem; padding: 1.5rem; }
  h1 { font-size: 1.4rem; margin: 0 0 0.25rem; }
  label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.82rem; opacity: 0.8; }
  label.check { flex-direction: row; align-items: center; gap: 0.45rem; }
  input[type="text"], input[type="email"], input[type="password"] {
    font: inherit; background: transparent; color: inherit;
    border: 1px solid rgba(127, 127, 127, 0.35); border-radius: 0.5rem; padding: 0.5rem 0.6rem;
  }
  .btn { border: 0; background: var(--bs-primary, #4f46e5); color: #fff; border-radius: 0.5rem; padding: 0.55rem; cursor: pointer; font: inherit; }
  .btn:disabled { opacity: 0.6; cursor: default; }
  .linkish { background: none; border: 0; color: inherit; opacity: 0.7; text-decoration: underline; cursor: pointer; font: inherit; font-size: 0.85rem; }
  .error { color: #b3261e; margin: 0; font-size: 0.88rem; }
</style>
