<script>
  import { onMount, tick } from 'svelte';
  import Sidebar from './Sidebar.svelte';
  import { selectedChatId, chats } from './store.js';

  // ── API/WS Config ──────────────────────────────────────────────────────────
  const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
  const WS_BASE  = import.meta.env.VITE_WS_BASE  || "ws://localhost:8000";

  // ── Auth State ─────────────────────────────────────────────────────────────
  let isAuthenticated = false;
  let currentUser = "";
  let token = "";
  let isLogin = true;
  let username = "";
  let password = "";
  let totpCode = "";
  let isTotpEnabled = false;
  let errorMessage = "";
  let successMessage = "";

  // ── TOTP Setup State ───────────────────────────────────────────────────────
  let isSettingUpTOTP = false;
  let qrCodeBase64 = "";
  let totpSecretText = "";
  let setupTotpCode = "";

  // ── Chat State ─────────────────────────────────────────────────────────────
  $: activeChat = $chats.find(c => c.id === $selectedChatId);
  let messages = [];
  let chatInput = "";
  let ws = null;
  let chatContainer;
  let isLoadingHistory = false;
  let trustScore = 100.0;
  let securityEnforcement = true;
  let showDebug = false;
  let currentWsId = null;

  // ── Group Management ───────────────────────────────────────────────────────
  let showMemberModal = false;
  let newMemberUsername = "";

  // ── Security / PIN State ───────────────────────────────────────────────────
  let securityModeEnabled = false;
  let showSecuritySetupModal = false;
  let securitySetupPin = "";
  let securitySetupConfirmPin = "";
  let securitySetupError = "";
  let securitySetupSuccess = false;

  let showPinModal = false;
  let pinInput = "";
  let pinError = "";
  let systemAlert = null;

  // ── Lifecycle ──────────────────────────────────────────────────────────────
  onMount(() => {
    const storedToken = localStorage.getItem("token");
    const storedUser  = localStorage.getItem("username");
    if (storedToken && storedUser) {
      token               = storedToken;
      currentUser         = storedUser;
      isTotpEnabled       = localStorage.getItem("isTotpEnabled")       === "true";
      securityModeEnabled = localStorage.getItem("securityModeEnabled") === "true";
      isAuthenticated     = true;
      checkFrozenStatus();
    }
  });

  // ── WebSocket Connectivity ─────────────────────────────────────────────────
  $: if (isAuthenticated && $selectedChatId && $selectedChatId !== currentWsId) {
    if (ws) {
      ws.close();
      ws = null;
    }
    messages = [];
    fetchChatHistory($selectedChatId);
    connectWebSocket($selectedChatId);
    currentWsId = $selectedChatId;
  }

  async function checkFrozenStatus() {
    try {
      const res = await fetch(`${API_BASE}/auth/me`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        if (data.is_frozen) {
          showPinModal = true;
        }
      }
    } catch (e) {}
  }

  async function fetchChatHistory(chatId) {
    if (!chatId) return;
    isLoadingHistory = true;
    try {
      const res = await fetch(`${API_BASE}/chats/${chatId}/messages`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const raw = await res.json();
        messages = raw.map(m => ({
          sender: m.sender_username,
          text: m.text,
          timestamp: m.timestamp
        }));
        scrollToBottom();
      }
    } catch (e) {
      console.error("[History] Error:", e);
    } finally {
      isLoadingHistory = false;
    }
  }

  function connectWebSocket(chatId) {
    if (!chatId || ws) return;
    const wsUrl = `${WS_BASE}/ws/chat/${chatId}?token=${token}`;
    ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "chat") {
        const text = data.is_broadcast ? data.message : (data.text || "");
        messages = [...messages, { 
          sender: data.sender, 
          text, 
          timestamp: new Date().toISOString() 
        }];
        scrollToBottom();
      } else if (data.type === "trust_update") {
        trustScore = data.trust_score;
      } else if (data.type === "group_updated") {
        chats.update(list =>
          list.map(c => c.id === data.chat_id ? { ...c, members: data.members } : c)
        );
        if (data.kicked_user === currentUser && data.chat_id === chatId) {
          ws.close();
          selectedChatId.set(null);
        }
      } else if (data.type === "system_alert") {
        systemAlert = data.clear ? null : { message: data.message };
      }
    };

    ws.onclose = (event) => {
      console.log("[WS] Closed code:", event.code);
      ws = null;
      if (event.code === 4001) {
        if (securityModeEnabled) {
          showPinModal = true;
        } else {
          forceLockout();
        }
      }
    };
  }

  async function submitPin() {
    pinError = "Verifying...";
    try {
      const res = await fetch(`${API_BASE}/auth/verify-pin`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ pin: pinInput })
      });
      if (res.ok) {
        showPinModal = false;
        pinInput = "";
        pinError = "";
        trustScore = 100.0;
        systemAlert = null;
        if ($selectedChatId) connectWebSocket($selectedChatId);
      } else {
        const data = await res.json();
        pinError = data.detail || "Invalid PIN";
      }
    } catch (e) {
      pinError = "Connection error";
    }
  }

  function forceLockout() {
    logout();
    errorMessage = "Session locked due to unusual behavior. Please login again.";
  }

  function logout() {
    localStorage.clear();
    isAuthenticated = false;
    currentUser = "";
    token = "";
    if (ws) ws.close();
    ws = null;
    messages = [];
    selectedChatId.set(null);
  }

  // ── Chat Actions ───────────────────────────────────────────────────────────
  function sendChatMessage() {
    if (ws && chatInput.trim() !== "") {
      ws.send(JSON.stringify({
        message: chatInput.trim(),
        enforce_security: securityEnforcement
      }));
      chatInput = "";
    }
  }

  async function scrollToBottom() {
    await tick();
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  // ── Group Actions ──────────────────────────────────────────────────────────
  async function addGroupMember() {
    if (!newMemberUsername.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/chats/${$selectedChatId}/members`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ username: newMemberUsername.trim() })
      });
      if (res.ok) {
        newMemberUsername = "";
        // Group sync happens via WS "group_updated"
      } else {
        const data = await res.json();
        alert(data.detail || "Error adding member");
      }
    } catch(e) {}
  }

  async function removeGroupMember(username) {
    if(!confirm(`Remove ${username}?`)) return;
    try {
      await fetch(`${API_BASE}/chats/${$selectedChatId}/members/${username}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
    } catch(e) {}
  }

  // ── Auth Actions ───────────────────────────────────────────────────────────
  async function handleSubmit(e) {
    e.preventDefault();
    errorMessage = "";
    const endpoint = isLogin ? "/auth/login" : "/auth/register";
    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, totp_code: totpCode })
      });
      const data = await res.json();
      if (res.ok) {
        token = data.access_token;
        currentUser = username;
        isTotpEnabled = data.is_totp_enabled === true;
        securityModeEnabled = data.security_enabled === true;
        localStorage.setItem("token", token);
        localStorage.setItem("username", currentUser);
        localStorage.setItem("isTotpEnabled", isTotpEnabled);
        localStorage.setItem("securityModeEnabled", securityModeEnabled);
        isAuthenticated = true;
        checkFrozenStatus();
      } else {
        errorMessage = data.detail || "Auth failed";
      }
    } catch (err) {
      errorMessage = "Network error";
    }
  }

  async function enableSecurityMode() {
    securitySetupError = "";
    if (securitySetupPin !== securitySetupConfirmPin) {
      securitySetupError = "PINs do not match";
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
      if (res.ok) {
        securityModeEnabled = true;
        securitySetupSuccess = true;
        localStorage.setItem("securityModeEnabled", "true");
        setTimeout(() => { showSecuritySetupModal = false; }, 1500);
      } else {
        const data = await res.json();
        securitySetupError = data.detail || "Failed to enable";
      }
    } catch (e) {
      securitySetupError = "Network error";
    }
  }
</script>

<main class="min-h-screen bg-base-200">
  {#if !isAuthenticated}
    <!-- Login/Register UI -->
    <div class="flex items-center justify-center min-h-screen p-4">
      <div class="card w-full max-w-md shadow-2xl bg-base-100">
        <div class="card-body">
          <h2 class="card-title text-2xl font-bold justify-center mb-6">
            {isLogin ? 'Welcome Back' : 'Create Account'}
          </h2>
          {#if errorMessage}
            <div class="alert alert-error mb-4">{errorMessage}</div>
          {/if}
          <form on:submit={handleSubmit}>
            <div class="form-control mb-4">
              <label class="label"><span class="label-text">Username</span></label>
              <input type="text" class="input input-bordered" bind:value={username} required />
            </div>
            <div class="form-control mb-4">
              <label class="label"><span class="label-text">Password</span></label>
              <input type="password" class="input input-bordered" bind:value={password} required />
            </div>
            {#if isLogin}
              <div class="form-control mb-6">
                <label class="label"><span class="label-text">2FA Code (Optional)</span></label>
                <input type="text" class="input input-bordered" bind:value={totpCode} maxlength="6" />
              </div>
            {/if}
            <button type="submit" class="btn btn-primary w-full">{isLogin ? 'Login' : 'Register'}</button>
          </form>
          <div class="divider">OR</div>
          <button class="btn btn-link no-underline" on:click={() => isLogin = !isLogin}>
            {isLogin ? 'Need an account? Register' : 'Have an account? Login'}
          </button>
        </div>
      </div>
    </div>
  {:else}
    <!-- Authenticated UI -->
    <div class="h-screen flex flex-col overflow-hidden">
      <!-- Navbar -->
      <nav class="navbar bg-base-100 shadow-md px-6 z-20">
        <div class="flex-1">
          <span class="text-xl font-bold tracking-tight text-primary">Stylometry Ultimate</span>
        </div>
        <div class="flex-none gap-4 items-center">
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold uppercase opacity-50">Security</span>
            <input type="checkbox" class="toggle toggle-error toggle-sm" bind:checked={securityEnforcement} />
          </div>
          
          {#if securityModeEnabled}
            <div class="badge badge-success gap-1 py-3 px-4 font-bold text-xs uppercase">
              🔐 PIN Active
            </div>
          {:else}
            <button class="btn btn-warning btn-sm" on:click={() => showSecuritySetupModal = true}>
              Enable PIN Auth
            </button>
          {/if}

          <div class="flex items-center gap-2">
            <span class="text-xs font-bold uppercase opacity-50">Debug</span>
            <input type="checkbox" class="toggle toggle-secondary toggle-sm" bind:checked={showDebug} />
          </div>

          {#if showDebug}
            <div class="badge badge-outline gap-2 font-mono">
              Score: <span class={trustScore < 40 ? 'text-error' : 'text-success'}>{trustScore.toFixed(1)}</span>
            </div>
          {/if}

          <div class="divider divider-horizontal mx-0"></div>
          <span class="text-sm font-semibold">{currentUser}</span>
          <button class="btn btn-ghost btn-sm btn-circle" on:click={logout} title="Logout">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
          </button>
        </div>
      </nav>

      <div class="flex-1 flex overflow-hidden p-4 gap-4">
        <Sidebar {token} />

        <!-- Chat Container -->
        <div class="flex-1 flex flex-col bg-base-100 rounded-2xl shadow-xl overflow-hidden border border-base-300">
          {#if !$selectedChatId}
            <div class="flex-1 flex flex-col items-center justify-center opacity-30 select-none">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-24 w-24 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              <h3 class="text-xl font-bold">Select a conversation</h3>
            </div>
          {:else}
            <!-- Chat Header -->
            <div class="bg-base-200 p-4 border-b border-base-300 flex justify-between items-center">
              <div>
                <h3 class="font-bold text-lg">{activeChat?.name || 'Chat Room'}</h3>
                <p class="text-xs opacity-50">{activeChat?.members?.length || 0} Members</p>
              </div>
              <div class="flex gap-2">
                {#if activeChat?.is_group}
                  <button class="btn btn-sm btn-circle btn-ghost" on:click={() => showMemberModal = true}>
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" /></svg>
                  </button>
                {/if}
              </div>
            </div>

            <!-- Messages Area -->
            <div class="flex-1 overflow-y-auto p-6" bind:this={chatContainer}>
              {#if isLoadingHistory}
                <div class="flex justify-center p-12"><span class="loading loading-spinner loading-lg"></span></div>
              {:else}
                {#each messages as msg}
                  <div class="chat {msg.sender === currentUser ? 'chat-end' : 'chat-start'} mb-4">
                    <div class="chat-header text-xs opacity-50 mb-1">{msg.sender}</div>
                    <div class="chat-bubble {msg.sender === currentUser ? 'chat-bubble-primary' : 'bg-base-200 text-base-content'}">
                      {msg.text}
                    </div>
                  </div>
                {/each}
              {/if}
            </div>

            <!-- Input Area -->
            <div class="p-4 bg-base-200 border-t border-base-300">
              {#if systemAlert}
                <div class="alert alert-warning py-2 mb-3 text-xs font-bold uppercase animate-pulse">
                  ⚠️ {systemAlert.message}
                </div>
              {/if}
              <div class="flex gap-2">
                <input 
                  type="text" 
                  class="input input-bordered flex-1" 
                  placeholder="Type a message..." 
                  bind:value={chatInput} 
                  on:keydown={e => e.key === 'Enter' && sendChatMessage()}
                />
                <button class="btn btn-primary px-8" on:click={sendChatMessage}>Send</button>
              </div>
            </div>
          {/if}
        </div>
      </div>
    </div>
  {/if}

  <!-- PIN Modal (Full Screen Overlay) -->
  {#if showPinModal}
    <div class="fixed inset-0 z-[100] bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
      <div class="card w-full max-w-sm bg-base-100 shadow-2xl border-2 border-error">
        <div class="card-body items-center text-center py-10">
          <div class="text-6xl mb-4 animate-bounce">🔐</div>
          <h2 class="card-title text-2xl font-bold text-error">Session Frozen</h2>
          <p class="text-sm opacity-70 mb-6">Critical typing anomaly detected. Enter your 6-digit PIN to unfreeze your session.</p>
          
          <div class="form-control w-full mb-4">
            <input 
              type="password" 
              class="input input-bordered input-error text-center tracking-[1em] text-2xl font-bold" 
              maxlength="6" 
              placeholder="••••••"
              bind:value={pinInput}
              on:keydown={e => e.key === 'Enter' && submitPin()}
              autofocus
            />
          </div>

          {#if pinError}
            <p class="text-error text-sm font-bold mb-4">{pinError}</p>
          {/if}

          <button class="btn btn-error w-full text-white font-bold" on:click={submitPin} disabled={pinInput.length !== 6}>
            Verify & Unfreeze
          </button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Security Setup Modal -->
  {#if showSecuritySetupModal}
    <dialog class="modal modal-open">
      <div class="modal-box max-w-sm">
        <h3 class="font-bold text-lg mb-4">Setup Security PIN</h3>
        {#if securitySetupSuccess}
          <div class="alert alert-success">PIN Setup Successful!</div>
        {:else}
          <p class="text-sm opacity-70 mb-4">Set a 6-digit PIN to enable step-up authentication. This prevents hard-kicks if stylometry fails.</p>
          <div class="form-control mb-4">
            <label class="label"><span class="label-text">6-Digit PIN</span></label>
            <input type="password" class="input input-bordered text-center" maxlength="6" bind:value={securitySetupPin} />
          </div>
          <div class="form-control mb-6">
            <label class="label"><span class="label-text">Confirm PIN</span></label>
            <input type="password" class="input input-bordered text-center" maxlength="6" bind:value={securitySetupConfirmPin} />
          </div>
          {#if securitySetupError}
            <p class="text-error text-sm mb-4">{securitySetupError}</p>
          {/if}
          <div class="modal-action">
            <button class="btn btn-ghost" on:click={() => showSecuritySetupModal = false}>Cancel</button>
            <button class="btn btn-primary" on:click={enableSecurityMode}>Enable</button>
          </div>
        {/if}
      </div>
    </dialog>
  {/if}

  <!-- Member Management Modal -->
  {#if showMemberModal && activeChat}
    <dialog class="modal modal-open">
      <div class="modal-box">
        <h3 class="font-bold text-lg mb-4">Manage Members</h3>
        <div class="flex gap-2 mb-6">
          <input type="text" placeholder="Username" class="input input-bordered flex-1" bind:value={newMemberUsername} />
          <button class="btn btn-primary" on:click={addGroupMember}>Add</button>
        </div>
        <div class="space-y-2 max-h-60 overflow-y-auto">
          {#each activeChat.members as member}
            <div class="flex justify-between items-center p-2 bg-base-200 rounded-lg">
              <span class="font-medium">{member.username}</span>
              {#if member.username !== currentUser}
                <button class="btn btn-xs btn-error btn-outline" on:click={() => removeGroupMember(member.username)}>Remove</button>
              {/if}
            </div>
          {/each}
        </div>
        <div class="modal-action">
          <button class="btn btn-ghost" on:click={() => showMemberModal = false}>Close</button>
        </div>
      </div>
    </dialog>
  {/if}
</main>
