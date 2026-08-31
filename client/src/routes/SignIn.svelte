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
  let registrationEnabled = $state(true);

  // A demo publishes its own credentials; filling them in saves a visitor typing.
  $effect(() => {
    fetch("/api/me", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null)
      .then((body) => {
        if (!body?.demo?.enabled) return;
        email ||= body.demo.email ?? "";
        password ||= body.demo.password ?? "";
      });
  });

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
        if (response.status === 403) registrationEnabled = false;
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

<div class="row justify-content-center">
  <div class="col-md-6 col-lg-5">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h1 class="h3 mb-4">{mode === "signin" ? "Login" : "Register"}</h1>

        {#if error}
          <div class="alert alert-danger py-2">{error}</div>
        {/if}

        <form onsubmit={submit}>
          {#if mode === "register"}
            <div class="mb-3">
              <label for="username" class="form-label">Username</label>
              <input
                type="text"
                class="form-control"
                id="username"
                autocomplete="username"
                bind:value={username}
                required
              />
            </div>
          {/if}

          <div class="mb-3">
            <label for="email" class="form-label">Email</label>
            <input
              type="email"
              class="form-control"
              id="email"
              autocomplete="email"
              bind:value={email}
              required
            />
          </div>

          <div class="mb-3">
            <label for="password" class="form-label">Password</label>
            <input
              type="password"
              class="form-control"
              id="password"
              autocomplete={mode === "signin" ? "current-password" : "new-password"}
              bind:value={password}
              required
            />
          </div>

          {#if mode === "register"}
            <div class="mb-3">
              <label for="confirm" class="form-label">Confirm password</label>
              <input
                type="password"
                class="form-control"
                id="confirm"
                autocomplete="new-password"
                bind:value={confirmPassword}
                required
              />
            </div>
          {:else}
            <div class="form-check mb-3">
              <input class="form-check-input" type="checkbox" id="remember_me" bind:checked={remember} />
              <label class="form-check-label" for="remember_me">Remember me</label>
            </div>
          {/if}

          <button type="submit" class="btn btn-primary w-100" disabled={busy}>
            {busy ? "Working…" : mode === "signin" ? "Login" : "Register"}
          </button>
        </form>

        {#if registrationEnabled}
          <p class="mt-3 mb-0 text-muted">
            {#if mode === "signin"}
              Need an account?
              <button type="button" class="btn btn-link p-0 align-baseline" onclick={() => { mode = "register"; error = ""; }}>
                Register here
              </button>.
            {:else}
              Already have an account?
              <button type="button" class="btn btn-link p-0 align-baseline" onclick={() => { mode = "signin"; error = ""; }}>
                Log in
              </button>.
            {/if}
          </p>
        {/if}
      </div>
    </div>
  </div>
</div>
