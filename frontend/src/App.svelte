<script>
  import { onMount } from 'svelte';

  // ── Auth State ─────────────────────────────────────────────────────────────
  let isLogin = true;
  let username = "";
  let password = "";
  let totpCode = "";
  let errorMessage = "";
  let successMessage = "";

  let isAuthenticated = false;
  let currentUser = "";
  let token = "";
  let isTotpEnabled = false;

  // ── TOTP Dashboard State ───────────────────────────────────────────────────
  let qrCodeBase64 = "";
  let totpSecretText = "";
  let setupTotpCode = "";
  let isSettingUpTOTP = false;

  // ── Real-time Chat State ───────────────────────────────────────────────────
  let messages = [];
  let chatInput = "";
  let ws = null;
  let chatContainer;

  // ── Trust State ────────────────────────────────────────────────────────────
  let trustScore = 100.0;
  let showDebug = false;
  let securityEnforcement = true;

  // ── System Alert (broadcast from server to all-except-sender) ─────────────
  // null  → no active alert
  // { message: string } → show warning pill
  let systemAlert = null;

  // ── Step-Up Auth: Challenge Modal (strictly blocking, two-stage) ──────────
  // pinModalStage: "pin_input" → user enters 6-digit PIN
  //                "confirmation" → user confirms ownership of the held message
  let showPinModal = false;
  let pinModalStage = "pin_input";   // "pin_input" | "confirmation"
  let pinInput = "";
  let pinError = "";
  let pendingMessageForConfirmation = ""; // populated by require_confirmation payload

  // ── Security Mode Setup (Enable Security Mode flow) ───────────────────────
  let securityModeEnabled = false;      // true once the user has registered a PIN
  let showSecuritySetupModal = false;   // drives the setup dialog visibility
  let securitySetupPin = "";            // PIN typed in the setup dialog
  let securitySetupConfirmPin = "";     // confirmation field
  let securitySetupError = "";          // inline error inside the setup dialog
  let securitySetupSuccess = false;     // one-shot success banner inside dialog

  const API_BASE = "http://localhost:8000";

  // ── Lifecycle ──────────────────────────────────────────────────────────────
  onMount(() => {
    const storedToken = localStorage.getItem("token");
    const storedUser  = localStorage.getItem("username");
    if (storedToken && storedUser) {
      token               = storedToken;
      currentUser         = storedUser;
      // Unconditional === "true" comparisons: always assign both true and false
      // so stale in-memory defaults can never silently override stored state.
      isTotpEnabled       = localStorage.getItem("isTotpEnabled")       === "true";
      securityModeEnabled = localStorage.getItem("securityModeEnabled") === "true";
      isAuthenticated     = true;
    }
  });

  // Block ESC from closing the PIN challenge modal
  function handleWindowKeydown(e) {
    if (showPinModal && e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
    }
  }

  // ── WebSocket ──────────────────────────────────────────────────────────────
  $: if (isAuthenticated && !ws) {
    connectWebSocket();
  }

  function connectWebSocket() {
    const wsUrl = `ws://localhost:8000/ws/chat?token=${token}`;
    ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "chat") {
        const text = data.is_broadcast ? data.message : (data.text || data.message || "");
        messages = [...messages, { sender: data.sender, text }];
        scrollToBottom();

      } else if (data.type === "trust_update") {
        trustScore = data.trust_score;

      } else if (data.type === "auth_challenge") {
        // Freeze UI — enter PIN input stage; user cannot dismiss the modal
        pinError      = "";
        pinInput      = "";
        pinModalStage = "pin_input";
        showPinModal  = true;

      } else if (data.type === "require_confirmation") {
        // PIN accepted — switch to the ownership confirmation stage.
        // Do NOT close the modal; keep the session visually frozen.
        pendingMessageForConfirmation = data.pending_message || "";
        pinModalStage = "confirmation";
        // showPinModal stays true

      } else if (data.type === "auth_success") {
        // Confirmation received by server — close the modal entirely
        showPinModal                  = false;
        pinModalStage                 = "pin_input";
        pinInput                      = "";
        pinError                      = "";
        pendingMessageForConfirmation = "";
        // Also clear the local system alert (our own session is clean again)
        systemAlert                   = null;

      } else if (data.type === "system_alert") {
        if (data.clear) {
          systemAlert = null;
        } else {
          systemAlert = { message: data.message };
        }

      } else if (data.sender && (data.text || data.message)) {
        // Legacy fallback
        const text = data.message || data.text;
        messages = [...messages, { sender: data.sender, text }];
        scrollToBottom();
      }
    };

    ws.onclose = (event) => {
      console.log("WebSocket Disconnected", event.code, event.reason);
      ws = null;
      if (event.code === 4001) {
        forceLockout();
      }
    };
  }

  // ── Session Freeze / Hard Kick ─────────────────────────────────────────────
  function forceLockout() {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    localStorage.removeItem("isTotpEnabled");
    localStorage.removeItem("securityModeEnabled");
    isAuthenticated     = false;
    currentUser         = "";
    token               = "";
    isTotpEnabled       = false;
    securityModeEnabled = false;
    isSettingUpTOTP     = false;
    qrCodeBase64        = "";
    totpSecretText      = "";
    setupTotpCode       = "";
    messages            = [];
    trustScore          = 100.0;
    systemAlert         = null;
    showPinModal        = false;

    if (ws) { ws.close(); ws = null; }

    isLogin      = true;
    errorMessage = "Session locked due to unusual typing behavior. Please re-authenticate.";
    successMessage = "";
  }

  // ── Step-Up Auth: submit PIN to WebSocket ──────────────────────────────────
  function submitPin() {
    if (!ws || pinInput.length !== 6) return;
    ws.send(JSON.stringify({ type: "verify_pin", pin: pinInput }));
    pinInput = "";
    pinError = "Verifying…";
  }

  function handlePinKeydown(e) {
    if (e.key === "Enter") submitPin();
  }

  // ── Step-Up Auth: ownership confirmation ───────────────────────────────────
  // Called by the two confirmation buttons in the modal's second stage.
  // isOwner = true  → server saves the held message to baseline and broadcasts it
  // isOwner = false → server silently discards it (baseline integrity preserved)
  function confirmOwnership(isOwner) {
    if (!ws) return;
    ws.send(JSON.stringify({ type: "confirm_message", is_owner: isOwner }));
  }

  // ── Chat ───────────────────────────────────────────────────────────────────
  function sendChatMessage() {
    if (ws && chatInput.trim() !== "") {
      const payload = {
        message: chatInput.trim(),
        enforce_security: securityEnforcement
      };
      console.log("DEBUG: Sending payload:", payload);
      ws.send(JSON.stringify(payload));
      chatInput = "";
    }
  }

  function handleChatKeydown(event) {
    if (event.key === "Enter") sendChatMessage();
  }

  function scrollToBottom() {
    setTimeout(() => {
      if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
    }, 50);
  }

  // ── Enable Security Mode ───────────────────────────────────────────────────
  function openSecuritySetupModal() {
    securitySetupPin        = "";
    securitySetupConfirmPin = "";
    securitySetupError      = "";
    securitySetupSuccess    = false;
    showSecuritySetupModal  = true;
  }

  function closeSecuritySetupModal() {
    showSecuritySetupModal  = false;
    securitySetupPin        = "";
    securitySetupConfirmPin = "";
    securitySetupError      = "";
  }

  async function enableSecurityMode() {
    securitySetupError   = "";
    securitySetupSuccess = false;

    if (!/^\d{6}$/.test(securitySetupPin)) {
      securitySetupError = "PIN must be exactly 6 digits.";
      return;
    }
    if (securitySetupPin !== securitySetupConfirmPin) {
      securitySetupError = "PINs do not match.";
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/auth/security/enable`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ pin: securitySetupPin })
      });

      const data = await res.json();

      if (!res.ok) {
        securitySetupError = Array.isArray(data.detail)
          ? data.detail[0].msg
          : (data.detail || "Failed to enable Security Mode.");
        return;
      }

      // Success
      securityModeEnabled  = true;
      securitySetupSuccess = true;
      localStorage.setItem("securityModeEnabled", "true");

      // Auto-close after brief success feedback
      setTimeout(() => { showSecuritySetupModal = false; }, 1800);

    } catch (err) {
      securitySetupError = "Network error. Please try again.";
    }
  }

  // ── Auth / TOTP ────────────────────────────────────────────────────────────
  function toggleMode() {
    isLogin        = !isLogin;
    username       = "";
    password       = "";
    totpCode       = "";
    errorMessage   = "";
    successMessage = "";
  }

  function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    localStorage.removeItem("isTotpEnabled");
    localStorage.removeItem("securityModeEnabled");
    isAuthenticated     = false;
    currentUser         = "";
    token               = "";
    isTotpEnabled       = false;
    securityModeEnabled = false;
    isSettingUpTOTP     = false;
    qrCodeBase64        = "";
    totpSecretText      = "";
    setupTotpCode       = "";
    errorMessage        = "";
    successMessage      = "";
    trustScore          = 100.0;
    systemAlert         = null;
    showPinModal        = false;
    if (ws) { ws.close(); ws = null; }
    messages = [];
  }

  async function handleSubmit(event) {
    event.preventDefault();
    errorMessage   = "";
    successMessage = "";

    const endpoint = isLogin ? "/auth/login" : "/auth/register";
    const payload  = { username, password };
    if (isLogin && totpCode) payload.totp_code = totpCode;

    try {
      const response = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();

      if (!response.ok) {
        errorMessage = Array.isArray(data.detail)
          ? data.detail[0].msg
          : (data.detail || "Authentication failed");
        return;
      }

      console.log("Login Response from Backend:", data);

      token               = data.access_token;
      currentUser         = username;
      // Strict === true comparison — avoids falsy-coercion bugs where a
      // missing field (undefined) and an explicit false both collapse to false
      // correctly, and a genuine true is never accidentally cast to something else.
      isTotpEnabled       = data.is_totp_enabled  === true;
      securityModeEnabled = data.security_enabled  === true;

      localStorage.setItem("token",               token);
      localStorage.setItem("username",            currentUser);
      localStorage.setItem("isTotpEnabled",       isTotpEnabled.toString());
      localStorage.setItem("securityModeEnabled", securityModeEnabled.toString());
      isAuthenticated = true;

    } catch (error) {
      errorMessage = "Network error. Please try again.";
    }
  }

  async function generateTOTP() {
    errorMessage   = "";
    successMessage = "";
    isSettingUpTOTP = true;

    try {
      const response = await fetch(
        `${API_BASE}/auth/totp/generate?username=${encodeURIComponent(currentUser)}`,
        { method: "POST", headers: { "Authorization": `Bearer ${token}` } }
      );
      const data = await response.json();
      if (response.ok) {
        qrCodeBase64  = data.qr_code;
        totpSecretText = data.secret;
      } else {
        errorMessage = Array.isArray(data.detail)
          ? data.detail[0].msg
          : (data.detail || "Failed to generate 2FA");
      }
    } catch (error) {
      errorMessage = "Network Error during 2FA generation";
    }
  }

  async function verifyTOTP() {
    errorMessage   = "";
    successMessage = "";

    try {
      const response = await fetch(
        `${API_BASE}/auth/totp/verify?username=${encodeURIComponent(currentUser)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify({ totp_code: setupTotpCode })
        }
      );
      const data = await response.json();

      if (response.ok) {
        successMessage  = "2FA Enabled Successfully!";
        isTotpEnabled   = true;
        localStorage.setItem("isTotpEnabled", "true");
        isSettingUpTOTP = false;
        qrCodeBase64    = "";
        totpSecretText  = "";
        setupTotpCode   = "";
        if (data.access_token) {
          token = data.access_token;
          localStorage.setItem("token", token);
        }
      } else {
        errorMessage = Array.isArray(data.detail)
          ? data.detail[0].msg
          : (data.detail || "Invalid 2FA Code");
      }
    } catch (error) {
      errorMessage = "Network Error verifying 2FA";
    }
  }
</script>

<!-- ── Block ESC while the PIN challenge modal is open ─────────────────────── -->
<svelte:window on:keydown={handleWindowKeydown} />

<!-- ═══════════════════════════════════════════════════════════════════════════
     STEP-UP AUTH — Blocking Two-Stage Modal
     Stage 1 "pin_input"    — user enters their 6-digit Security PIN
     Stage 2 "confirmation" — user confirms whether they typed the held message
     • No close button, no backdrop click, ESC captured by svelte:window
     ═══════════════════════════════════════════════════════════════════════════ -->
{#if showPinModal}
  <!-- Full-screen overlay; pointer-events:all blocks everything underneath -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
    style="pointer-events: all;"
    on:click|stopPropagation={() => {/* swallow backdrop clicks */}}
    role="dialog"
    aria-modal="true"
    aria-labelledby="pin-modal-title"
  >
    <div
      class="bg-base-100 rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-8 border-2 border-error"
      on:click|stopPropagation
    >

      {#if pinModalStage === "pin_input"}
        <!-- ── Stage 1: PIN entry ───────────────────────────────────────── -->
        <div class="flex flex-col items-center mb-6">
          <div class="text-5xl mb-3 animate-pulse">🔐</div>
          <h3 id="pin-modal-title" class="text-xl font-bold text-error text-center">
            Identity Verification Required
          </h3>
          <p class="text-sm text-base-content/70 text-center mt-2 leading-relaxed">
            Unusual typing pattern detected.<br />
            Enter your 6-digit Security PIN to resume your session.
          </p>
        </div>

        <div class="form-control mb-4">
          <input
            type="password"
            inputmode="numeric"
            maxlength="6"
            pattern="[0-9]{6}"
            placeholder="••••••"
            class="input input-bordered input-error w-full text-center tracking-[0.6em] text-2xl font-bold"
            bind:value={pinInput}
            on:keydown={handlePinKeydown}
            autofocus
          />
        </div>

        {#if pinError}
          <p class="text-sm text-center mb-3
            {pinError === 'Verifying…' ? 'text-info animate-pulse' : 'text-error font-semibold'}">
            {pinError}
          </p>
        {/if}

        <button
          class="btn btn-error w-full text-white font-bold"
          on:click={submitPin}
          disabled={pinInput.length !== 6}
        >
          Verify PIN
        </button>

        <p class="text-[10px] text-base-content/40 text-center mt-4 uppercase tracking-widest">
          Session frozen · All messages held until verified
        </p>

      {:else if pinModalStage === "confirmation"}
        <!-- ── Stage 2: Ownership confirmation ────────────────────────── -->
        <div class="flex flex-col items-center mb-5">
          <div class="text-5xl mb-3">🤔</div>
          <h3 id="pin-modal-title" class="text-xl font-bold text-warning text-center">
            Unusual Typing Detected
          </h3>
          <p class="text-sm text-base-content/70 text-center mt-2">
            Did <span class="font-bold text-base-content">you</span> type this message?
          </p>
        </div>

        <!-- Held message quote block -->
        <div class="bg-base-200 border-l-4 border-warning rounded-lg px-4 py-3 mb-6">
          <p class="text-xs uppercase tracking-wider text-base-content/50 mb-1 font-semibold">
            Held message
          </p>
          <p class="text-sm text-base-content leading-relaxed italic break-words">
            "{pendingMessageForConfirmation}"
          </p>
        </div>

        <!-- Confirmation buttons -->
        <div class="flex gap-3">
          <button
            class="btn btn-success flex-1"
            on:click={() => confirmOwnership(true)}
          >
            ✅ Yes, it was me
          </button>
          <button
            class="btn btn-error flex-1"
            on:click={() => confirmOwnership(false)}
          >
            🗑️ No, delete it
          </button>
        </div>

        <p class="text-[10px] text-base-content/40 text-center mt-4 uppercase tracking-widest">
          "No" protects the baseline · Message will not be broadcast
        </p>
      {/if}

    </div>
  </div>
{/if}

<!-- ═══════════════════════════════════════════════════════════════════════════
     ENABLE SECURITY MODE — Setup Modal
     ═══════════════════════════════════════════════════════════════════════════ -->
{#if showSecuritySetupModal}
  <div
    class="fixed inset-0 z-40 flex items-center justify-center bg-black/60 backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
    aria-labelledby="sec-setup-title"
  >
    <div
      class="bg-base-100 rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-8 border border-base-300"
      on:click|stopPropagation
    >
      <div class="flex flex-col items-center mb-5">
        <div class="text-4xl mb-2">🛡️</div>
        <h3 id="sec-setup-title" class="text-xl font-bold text-center">Enable Security Mode</h3>
        <p class="text-sm text-base-content/60 text-center mt-1 leading-relaxed">
          Set a 6-digit PIN. If your trust score drops critically,
          you'll be challenged instead of hard-kicked.
        </p>
      </div>

      {#if securitySetupSuccess}
        <div class="alert alert-success text-sm mb-4">
          <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-5 w-5" fill="none" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <span>Security Mode activated!</span>
        </div>
      {:else}
        <div class="form-control mb-3">
          <label class="label pb-1" for="sec-pin">
            <span class="label-text text-xs font-semibold uppercase tracking-wider">PIN</span>
          </label>
          <input
            id="sec-pin"
            type="password"
            inputmode="numeric"
            maxlength="6"
            placeholder="6-digit PIN"
            class="input input-bordered w-full text-center tracking-[0.4em] text-lg font-bold"
            bind:value={securitySetupPin}
          />
        </div>

        <div class="form-control mb-4">
          <label class="label pb-1" for="sec-pin-confirm">
            <span class="label-text text-xs font-semibold uppercase tracking-wider">Confirm PIN</span>
          </label>
          <input
            id="sec-pin-confirm"
            type="password"
            inputmode="numeric"
            maxlength="6"
            placeholder="Repeat PIN"
            class="input input-bordered w-full text-center tracking-[0.4em] text-lg font-bold"
            bind:value={securitySetupConfirmPin}
          />
        </div>

        {#if securitySetupError}
          <p class="text-error text-sm font-semibold mb-3 text-center">{securitySetupError}</p>
        {/if}

        <button
          class="btn btn-primary w-full mb-2"
          on:click={enableSecurityMode}
          disabled={securitySetupPin.length !== 6 || securitySetupConfirmPin.length !== 6}
        >
          Activate Security Mode
        </button>
      {/if}

      <button class="btn btn-ghost btn-sm w-full" on:click={closeSecuritySetupModal}>
        Cancel
      </button>
    </div>
  </div>
{/if}

<!-- ═══════════════════════════════════════════════════════════════════════════
     MAIN APP
     ═══════════════════════════════════════════════════════════════════════════ -->
<main class="min-h-screen flex items-center justify-center bg-base-200">

  {#if !isAuthenticated}
  <!-- ── Login / Register Card ──────────────────────────────────────────── -->
  <div class="card w-full max-w-sm shadow-2xl bg-base-100">
    <div class="card-body">
      <h2 class="card-title text-2xl justify-center font-bold mb-4">
        {isLogin ? 'Login to Stylometry' : 'Create Account'}
      </h2>

      {#if errorMessage}
        <div class="alert alert-error text-sm mb-4">
          <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <span>{errorMessage}</span>
        </div>
      {/if}

      <form on:submit={handleSubmit} novalidate>
        <div class="form-control mb-4">
          <label class="label" for="username">
            <span class="label-text">Username</span>
          </label>
          <input
            type="text"
            id="username"
            placeholder="johndoe"
            class="input input-bordered w-full"
            bind:value={username}
            required
            pattern="[a-zA-Z0-9_]+"
            minlength="3"
            maxlength="20"
          />
        </div>

        <div class="form-control mb-4">
          <label class="label" for="password">
            <span class="label-text">Password</span>
          </label>
          <input
            type="password"
            id="password"
            placeholder="••••••••"
            class="input input-bordered w-full"
            bind:value={password}
            required
            minlength="6"
          />
        </div>

        {#if isLogin}
          <div class="form-control mb-6">
            <label class="label" for="totpCode">
              <span class="label-text">2FA Code (if enabled)</span>
            </label>
            <input
              type="text"
              id="totpCode"
              placeholder="123456"
              class="input input-bordered w-full"
              bind:value={totpCode}
              maxlength="6"
              inputmode="numeric"
            />
          </div>
        {:else}
          <div class="mb-6"></div>
        {/if}

        <div class="form-control mt-2">
          <button type="submit" class="btn btn-primary w-full">
            {isLogin ? 'Sign In' : 'Sign Up'}
          </button>
        </div>
      </form>

      <div class="divider">OR</div>

      <div class="text-center mt-2">
        <button class="btn btn-link text-sm" on:click={toggleMode}>
          {isLogin ? "Don't have an account? Register" : 'Already have an account? Login'}
        </button>
      </div>
    </div>
  </div>

  {:else}
  <!-- ── Authenticated Shell ─────────────────────────────────────────────── -->
  <div class="w-full h-screen flex flex-col bg-base-200">

    <!-- ── Navbar ─────────────────────────────────────────────────────────── -->
    <div class="navbar bg-base-100 shadow-sm px-4 shrink-0">
      <div class="flex-1">
        <a href="/" class="btn btn-ghost text-xl">Stylometry Chat</a>
      </div>

      <div class="flex-none gap-2 flex items-center flex-wrap">

        <!-- Security Enforcement Toggle -->
        <label class="swap swap-flip mr-2 text-xs font-semibold cursor-pointer">
          <input type="checkbox" bind:checked={securityEnforcement} />
          <div class="swap-on text-error">Security: ON</div>
          <div class="swap-off opacity-40">Security: OFF</div>
        </label>

        <!-- Status Feedback -->
        <div class="hidden md:block mr-2 text-[10px] uppercase tracking-tighter font-bold">
          {#if securityEnforcement}
            <span class="text-error animate-pulse">● Active Protection</span>
          {:else}
            <span class="text-base-content opacity-40">○ Data Collection</span>
          {/if}
        </div>

        <!-- ── 🔐 Enable Security Mode Button ──────────────────────────────
             Shows a lock icon + label; turns into a success badge once enabled.
        ─────────────────────────────────────────────────────────────────── -->
        {#if securityModeEnabled}
          <div class="badge badge-success gap-1 mr-2 text-xs font-semibold py-3 px-3">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
            </svg>
            Security PIN Active
          </div>
        {:else}
          <button
            class="btn btn-outline btn-warning btn-sm mr-2 gap-1"
            on:click={openSecuritySetupModal}
            title="Enable step-up authentication via a secondary PIN"
          >
            🔐 Enable Security Mode
          </button>
        {/if}

        <!-- Debug Toggle -->
        <label class="swap swap-flip mr-2 text-xs font-semibold cursor-pointer">
          <input type="checkbox" bind:checked={showDebug} />
          <div class="swap-on text-primary">Debug: ON</div>
          <div class="swap-off opacity-40">Debug: OFF</div>
        </label>

        {#if showDebug}
          <div
            class="radial-progress text-sm mr-2
              {trustScore > 80 ? 'text-success' : trustScore > 40 ? 'text-warning' : 'text-error'}"
            style="--value:{trustScore}; --size:3rem; --thickness: 4px;"
            role="progressbar"
          >
            {Math.round(trustScore)}
          </div>
        {/if}

        <span class="text-sm font-semibold mr-2">Welcome, {currentUser}</span>
        <button class="btn btn-outline btn-error btn-sm" on:click={logout}>Logout</button>
      </div>
    </div>

    <!-- ── System Alert Pill ──────────────────────────────────────────────── -->
    <!-- Rendered outside the chat panel so it floats over all content.
         Only visible when another user's session is frozen. -->
    {#if systemAlert}
      <div class="flex justify-center px-4 pt-3 shrink-0 pointer-events-none">
        <div
          class="alert alert-warning shadow-lg max-w-xl w-full rounded-full py-2 px-6 flex items-center gap-3 animate-pulse pointer-events-auto"
          role="alert"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
          </svg>
          <span class="text-sm font-semibold flex-1 text-center">{systemAlert.message}</span>
          <!-- Manual dismiss (for observers who have already seen the alert) -->
          <button
            class="btn btn-xs btn-ghost pointer-events-auto"
            on:click={() => systemAlert = null}
            title="Dismiss"
          >✕</button>
        </div>
      </div>
    {/if}

    <!-- ── Main Content ───────────────────────────────────────────────────── -->
    <div class="flex-1 flex flex-col lg:flex-row gap-6 p-6 overflow-hidden">

      <!-- Chat Panel -->
      <div class="flex-1 flex flex-col bg-base-100 shadow-xl rounded-box overflow-hidden h-full">
        <div class="bg-base-200 p-4 font-bold border-b border-base-300">
          Tester Bot Chamber
        </div>

        <div class="flex-1 p-4 overflow-y-auto" bind:this={chatContainer}>
          {#if messages.length === 0}
            <div class="text-center text-base-content/50 mt-10">
              <p>Welcome to Thai Stylometry Chat!</p>
              <p class="text-sm">Say hello to the Tester Bot…</p>
            </div>
          {/if}

          {#each messages as msg}
            <div class="chat {msg.sender === currentUser ? 'chat-end' : 'chat-start'}">
              <div class="chat-header text-xs opacity-50 mb-1">{msg.sender}</div>
              <div class="chat-bubble {msg.sender === currentUser ? 'chat-bubble-primary' : 'chat-bubble-secondary'}">
                {msg.text}
              </div>
            </div>
          {/each}
        </div>

        <div class="p-4 bg-base-200 border-t border-base-300 flex gap-2">
          <input
            type="text"
            class="input input-bordered flex-1"
            placeholder="Type a message…"
            bind:value={chatInput}
            on:keydown={handleChatKeydown}
          />
          <button class="btn btn-primary" on:click={sendChatMessage}>Send</button>
        </div>
      </div>

      <!-- Security Settings Panel -->
      <div class="card w-full lg:w-96 bg-base-100 shadow-xl h-fit shrink-0">
        <div class="card-body">
          <h2 class="card-title text-xl border-b pb-2 mb-4">Security Settings</h2>

          {#if successMessage}
            <div class="alert alert-success text-sm mb-4">
              <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              <span>{successMessage}</span>
            </div>
          {/if}

          {#if errorMessage}
            <div class="alert alert-error text-sm mb-4">
              <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              <span>{errorMessage}</span>
            </div>
          {/if}

          <!-- Step-Up Security Status Block -->
          <div class="mb-4 p-3 rounded-box border
            {securityModeEnabled ? 'border-success bg-success/5' : 'border-warning bg-warning/5'}">
            <p class="text-xs font-bold uppercase tracking-wider mb-1
              {securityModeEnabled ? 'text-success' : 'text-warning'}">
              {securityModeEnabled ? '🔐 Step-Up Auth' : '⚠️ Step-Up Auth'}
            </p>
            {#if securityModeEnabled}
              <p class="text-xs text-base-content/70">
                Security PIN is active. If your trust score drops critically, you'll
                be challenged instead of kicked.
              </p>
            {:else}
              <p class="text-xs text-base-content/70 mb-2">
                No PIN registered. A critical trust drop will hard-kick your session.
              </p>
              <button class="btn btn-warning btn-xs w-full" on:click={openSecuritySetupModal}>
                🔐 Enable Security Mode
              </button>
            {/if}
          </div>

          <!-- TOTP Section -->
          {#if isTotpEnabled}
            <div class="alert alert-success text-sm mb-4">
              <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              <span>✅ 2FA is securely enabled for your account.</span>
            </div>
          {:else if !isSettingUpTOTP}
            <p class="text-sm text-base-content/80 mb-4">
              Protect your account with Two-Factor Authentication (2FA).
            </p>
            <button class="btn btn-outline btn-primary w-full" on:click={generateTOTP}>
              Enable 2FA
            </button>
          {:else}
            <div class="flex flex-col items-center">
              <p class="text-sm font-semibold mb-2">1. Scan QR Code</p>
              {#if qrCodeBase64}
                <div class="bg-white p-2 rounded-lg mb-2">
                  <img src="data:image/png;base64,{qrCodeBase64}" alt="TOTP QR Code" class="w-48 h-48" />
                </div>
              {:else}
                <span class="loading loading-spinner text-primary my-4"></span>
              {/if}
              <p class="text-xs text-base-content/60 mb-4">Secret: {totpSecretText}</p>

              <div class="w-full divider my-2"></div>

              <p class="text-sm font-semibold mb-2 w-full text-left">2. Verify & Save</p>
              <div class="form-control w-full">
                <input
                  type="text"
                  placeholder="Enter 6-digit code"
                  class="input input-sm input-bordered w-full mb-3 text-center tracking-widest text-lg"
                  bind:value={setupTotpCode}
                  pattern="[0-9]{6}"
                  maxlength="6"
                  inputmode="numeric"
                />
                <button
                  class="btn btn-success btn-sm w-full"
                  on:click={verifyTOTP}
                  disabled={setupTotpCode.length !== 6}
                >
                  Verify & Save
                </button>
                <button
                  class="btn btn-ghost btn-sm w-full mt-2"
                  on:click={() => { isSettingUpTOTP = false; qrCodeBase64 = ""; }}
                >
                  Cancel
                </button>
              </div>
            </div>
          {/if}
        </div>
      </div>

    </div>
  </div>
  {/if}
</main>
