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
  let totpVerifyError = "";
  let isTotpVerifying = false;

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

  // ── Modal Visibility ───────────────────────────────────────────────────────
  let showRegisterModal = false;
  let showCreateChatModal = false;
  let showSecuritySetupModal = false;
  let showPinModal = false;

  // ── Group/Chat Creation ───────────────────────────────────────────────────
  let showMemberModal = false;
  let newMemberUsername = "";
  let newChatName = "";
  let newChatMembers = [];
  let memberToAdd = "";

  // ── Registration State ─────────────────────────────────────────────────────
  let newUsername = "";
  let newPassword = "";

  // ── Security / PIN State ───────────────────────────────────────────────────
  let securityModeEnabled = false;
  let securitySetupPin = "";
  let securitySetupConfirmPin = "";
  let securitySetupError = "";
  let securitySetupSuccess = false;
  let totpQR = "";

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

  async function login(e) {
    if (e) e.preventDefault();
    errorMessage = "";
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
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
        errorMessage = data.detail || "Authentication failed";
      }
    } catch (err) {
      errorMessage = "Network error";
    }
  }

  async function register(e) {
    if (e) e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: newUsername, password: newPassword })
      });
      if (res.ok) {
        showRegisterModal = false;
        username = newUsername;
        password = newPassword;
        newUsername = "";
        newPassword = "";
        successMessage = "Registration successful! Please login.";
      } else {
        const data = await res.json();
        alert(data.detail || "Registration failed");
      }
    } catch (e) {
      alert("Network error during registration");
    }
  }

  async function generateTOTP() {
    try {
      const res = await fetch(`${API_BASE}/auth/totp/generate?username=${currentUser}`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        qrCodeBase64 = data.qr_code;
        totpSecretText = data.secret;
        setupTotpCode = "";
        totpVerifyError = "";
        isSettingUpTOTP = true;
      } else {
        const err = await res.json();
        totpVerifyError = err.detail || "Failed to generate TOTP";
      }
    } catch (e) {
      totpVerifyError = "Network error: " + e.message;
    }
  }

  async function verifyTOTPCode() {
    if (!setupTotpCode || setupTotpCode.length !== 6) {
      totpVerifyError = "Enter a valid 6-digit code";
      return;
    }
    isTotpVerifying = true;
    totpVerifyError = "";
    try {
      const res = await fetch(`${API_BASE}/auth/totp/verify?username=${currentUser}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ totp_code: setupTotpCode })
      });
      if (res.ok) {
        const data = await res.json();
        token = data.access_token;
        isTotpEnabled = true;
        localStorage.setItem("token", token);
        localStorage.setItem("isTotpEnabled", "true");
        isSettingUpTOTP = false;
        qrCodeBase64 = "";
        totpSecretText = "";
        setupTotpCode = "";
        successMessage = "2FA successfully enabled!";
        setTimeout(() => { showSecuritySetupModal = false; }, 1500);
      } else {
        const err = await res.json();
        totpVerifyError = err.detail || "Invalid 2FA code";
      }
    } catch (e) {
      totpVerifyError = "Network error: " + e.message;
    } finally {
      isTotpVerifying = false;
    }
  }

  async function createChat() {
    try {
      const res = await fetch(`${API_BASE}/chats/`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          name: newChatName,
          is_group: newChatMembers.length > 0,
          member_usernames: newChatMembers
        })
      });
      if (res.ok) {
        showCreateChatModal = false;
        newChatName = "";
        newChatMembers = [];
        // Refresh chat list (Sidebar store handles it typically, or we triggers a refresh)
      }
    } catch (e) {}
  }

  function addMember() {
    if (memberToAdd.trim() && !newChatMembers.includes(memberToAdd.trim())) {
      newChatMembers = [...newChatMembers, memberToAdd.trim()];
      memberToAdd = "";
    }
  }

  async function enableSecurity() {
    // ... logic for PIN setup ...
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
        localStorage.setItem("securityModeEnabled", "true");
        securitySetupPin = "";
      }
    } catch (e) {}
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
    <div class="flex items-center justify-center min-h-screen p-4">
      <div class="card w-full max-w-md bg-base-100 shadow-2xl border border-base-300 overflow-hidden">
        <div class="bg-primary p-12 text-center text-primary-content">
          <h1 class="text-5xl font-black tracking-tighter mb-2">Stylometry</h1>
          <p class="text-sm font-bold uppercase tracking-widest opacity-80">Secure Chat Room</p>
        </div>
        
        <div class="card-body p-10">
          {#if errorMessage}
            <div class="alert alert-error mb-6 shadow-sm font-medium">
              <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              <span>{errorMessage}</span>
            </div>
          {/if}

          <form on:submit|preventDefault={login} class="space-y-6">
            <div class="form-control">
              <label class="label pb-2" for="username">
                <span class="label-text font-bold text-xs uppercase opacity-70">Username</span>
              </label>
              <input
                id="username"
                type="text"
                placeholder="Your ID"
                class="input input-bordered focus:input-primary w-full bg-base-200/50"
                bind:value={username}
                required
              />
            </div>

            <div class="form-control">
              <label class="label pb-2" for="password">
                <span class="label-text font-bold text-xs uppercase opacity-70">Password</span>
              </label>
              <input
                id="password"
                type="password"
                placeholder="••••••••"
                class="input input-bordered focus:input-primary w-full bg-base-200/50"
                bind:value={password}
                required
              />
            </div>

            <div class="form-control">
              <label class="label pb-2" for="totp">
                <div class="flex items-center gap-2">
                  <span class="label-text font-bold text-xs uppercase opacity-70">2FA Code</span>
                  <span class="badge badge-ghost badge-xs font-bold text-[9px] uppercase">If enabled</span>
                </div>
              </label>
              <input
                id="totp"
                type="text"
                placeholder="6-digit PIN"
                class="input input-bordered focus:input-secondary w-full bg-base-200/50 tracking-[0.5em] font-mono text-center text-lg"
                bind:value={totpCode}
                maxlength="6"
              />
            </div>

            <button type="submit" class="btn btn-primary w-full text-lg shadow-xl hover:shadow-primary/20 mt-4 h-14">
              Sign In
            </button>
          </form>

          <div class="divider text-[10px] uppercase font-bold opacity-30 my-8">Access Control</div>

          <button
            class="btn btn-outline btn-block border-2 hover:bg-base-200 h-14"
            on:click={() => (showRegisterModal = true)}
          >
            Register New Account
          </button>
        </div>
      </div>
    </div>
  {:else}
    <!-- Authenticated UI -->
    <div class="h-screen flex flex-col overflow-hidden">
    <!-- ── Navbar ─────────────────────────────────────────────────────────── -->
    <nav class="navbar bg-base-100 shadow-md px-6 z-20">
      <div class="flex-1">
        <span class="text-xl font-black tracking-tight text-primary uppercase italic">Stylometry Chat</span>
      </div>
      
      <div class="flex-none flex items-center gap-6">
        <!-- Security Group -->
        <div class="flex items-center gap-3">
          <div class="flex flex-col items-end mr-1">
            <span class="text-[10px] font-bold uppercase opacity-50 leading-none mb-1">Protection</span>
            <input type="checkbox" class="toggle toggle-error toggle-xs" bind:checked={securityEnforcement} />
          </div>
          
          {#if securityModeEnabled}
            <div class="badge badge-success gap-1.5 py-3.5 px-4 font-bold text-[11px] uppercase shadow-sm border-none">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd" />
              </svg>
              PIN Active
            </div>
          {:else}
            <button class="btn btn-warning btn-sm btn-outline gap-2" on:click={() => showSecuritySetupModal = true}>
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M2.166 4.999A11.954 11.954 0 0010 1.944 11.954 11.954 0 0017.834 5c.11.65.166 1.32.166 2.001 0 5.225-3.34 9.67-8 11.317C5.34 16.67 2 12.225 2 7c0-.682.057-1.35.166-2.001zm11.541 3.708a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
              </svg>
              Enable PIN
            </button>
          {/if}
        </div>

        <div class="h-8 w-[1px] bg-base-300"></div>

        <!-- Debug/User Group -->
        <div class="flex items-center gap-4">
          <div class="flex items-center gap-2 tooltip tooltip-bottom" data-tip="Toggle Visual Trust Score">
            <span class="text-[10px] font-bold uppercase opacity-50">Debug</span>
            <input type="checkbox" class="toggle toggle-secondary toggle-xs" bind:checked={showDebug} />
          </div>

          {#if showDebug}
            <div class="badge badge-ghost font-mono text-xs gap-2 py-3 border-base-300">
              Score: <span class={trustScore < 40 ? 'text-error font-bold' : 'text-success font-bold'}>{trustScore.toFixed(1)}</span>
            </div>
          {/if}

          <div class="flex items-center gap-3 pl-2">
            <div class="flex flex-col items-end">
              <span class="text-sm font-bold leading-none">{currentUser}</span>
              <span class="text-[10px] opacity-50 font-medium">Standard User</span>
            </div>
            <button class="btn btn-ghost btn-sm btn-circle hover:bg-error/10 hover:text-error transition-colors" on:click={logout} title="Logout">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          </div>
        </div>
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

  <!-- Register Modal -->
  {#if showRegisterModal}
    <div class="modal modal-open">
      <div class="modal-box max-w-md p-8">
        <h3 class="font-black text-2xl mb-6">Create Account</h3>
        <form on:submit|preventDefault={register} class="space-y-6">
          <div class="form-control">
            <label class="label pb-1" for="reg-username">
              <span class="label-text font-bold text-xs uppercase opacity-70">Username</span>
            </label>
            <input
              id="reg-username"
              type="text"
              placeholder="Pick a username"
              class="input input-bordered focus:input-primary w-full transition-all"
              bind:value={newUsername}
              required
            />
          </div>
          <div class="form-control">
            <label class="label pb-1" for="reg-password">
              <span class="label-text font-bold text-xs uppercase opacity-70">Password</span>
            </label>
            <input
              id="reg-password"
              type="password"
              placeholder="••••••••"
              class="input input-bordered focus:input-primary w-full"
              bind:value={newPassword}
              required
            />
          </div>
          <div class="modal-action mt-8">
            <button type="button" class="btn btn-ghost" on:click={() => (showRegisterModal = false)}>Cancel</button>
            <button type="submit" class="btn btn-primary px-8 shadow-lg">Register</button>
          </div>
        </form>
      </div>
    </div>
  {/if}

  <!-- Security Settings Modal -->
  {#if showSecuritySetupModal}
    <div class="modal modal-open">
      <div class="modal-box max-w-xl p-0 overflow-hidden bg-base-100 shadow-2xl">
        <div class="bg-primary p-8 text-primary-content">
          <h3 class="font-black text-3xl tracking-tight mb-2">Shield Protection</h3>
          <p class="opacity-80 font-medium">Configure advanced security features for your account.</p>
        </div>
        
        <div class="p-8 space-y-8">
          <!-- Multi-Factor Auth Section -->
          <section>
            <div class="flex items-center gap-3 mb-4">
              <div class="w-8 h-8 rounded-lg bg-secondary/20 flex items-center justify-center text-secondary">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clip-rule="evenodd" />
                </svg>
              </div>
              <h4 class="font-bold text-lg uppercase tracking-wider opacity-90">Authentication</h4>
            </div>

            {#if !isSettingUpTOTP}
              <div class="bg-base-200 rounded-2xl p-6 flex items-center justify-between border border-base-300">
                <div>
                  <p class="font-bold text-base mb-1">Two-Factor Authentication (2FA)</p>
                  <p class="text-xs opacity-60">Adds an extra layer of security using a time-based code.</p>
                </div>
                <button class="btn btn-secondary btn-sm px-6" on:click={generateTOTP} disabled={isTotpEnabled}>
                  {isTotpEnabled ? 'Enabled' : 'Setup 2FA'}
                </button>
              </div>
            {:else}
              <div class="bg-base-200 rounded-2xl p-6 border border-secondary/50 space-y-6">
                <div>
                  <p class="font-bold text-base mb-2">Scan QR Code</p>
                  <p class="text-xs opacity-60 mb-4">Use an authenticator app like Google Authenticator, Authy, or Microsoft Authenticator.</p>
                  <div class="bg-base-100 p-4 rounded-lg border border-base-300 flex items-center justify-center">
                    {#if qrCodeBase64}
                      <img src="data:image/png;base64,{qrCodeBase64}" alt="TOTP QR Code" class="w-48 h-48" />
                    {:else}
                      <div class="loading loading-spinner loading-lg"></div>
                    {/if}
                  </div>
                </div>

                <div class="bg-base-100 p-4 rounded-lg border border-base-300">
                  <p class="text-[10px] font-bold uppercase opacity-50 mb-2">Backup Key (Manual Entry)</p>
                  <div class="font-mono text-sm font-bold tracking-wider text-center p-3 bg-base-200 rounded border border-base-300 select-all">
                    {totpSecretText}
                  </div>
                  <p class="text-xs opacity-60 mt-2">Save this code in a safe place. You can use it to recover access if you lose your authenticator.</p>
                </div>

                <div>
                  <label class="label pb-2" for="totp-verify">
                    <span class="label-text font-bold text-xs uppercase opacity-70">Enter 6-Digit Code</span>
                  </label>
                  <input
                    id="totp-verify"
                    type="text"
                    placeholder="000000"
                    maxlength="6"
                    class="input input-bordered focus:input-secondary w-full tracking-[1em] font-mono text-center text-lg font-bold"
                    bind:value={setupTotpCode}
                    on:keydown={e => e.key === 'Enter' && !isTotpVerifying && verifyTOTPCode()}
                    disabled={isTotpVerifying}
                  />
                  {#if totpVerifyError}
                    <p class="text-error text-sm font-bold mt-2">{totpVerifyError}</p>
                  {/if}
                </div>

                <div class="flex gap-3">
                  <button
                    class="btn btn-ghost flex-1"
                    on:click={() => { isSettingUpTOTP = false; qrCodeBase64 = ""; totpSecretText = ""; setupTotpCode = ""; totpVerifyError = ""; }}
                    disabled={isTotpVerifying}
                  >
                    Back
                  </button>
                  <button
                    class="btn btn-secondary flex-1"
                    on:click={verifyTOTPCode}
                    disabled={setupTotpCode.length !== 6 || isTotpVerifying}
                  >
                    {isTotpVerifying ? 'Verifying...' : 'Verify & Enable'}
                  </button>
                </div>
              </div>
            {/if}
          </section>

          <!-- Step-Up PIN Section -->
          <section>
            <div class="flex items-center gap-3 mb-4">
              <div class="w-8 h-8 rounded-lg bg-warning/20 flex items-center justify-center text-warning">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M18 8a6 6 0 01-7.743 5.743L10 14l-1 1-1 1H6v2H2v-4l4.257-4.257A6 6 0 1118 8zm-6-4a1 1 0 100 2 2 2 0 012 2 1 1 0 102 0 4 4 0 00-4-4z" clip-rule="evenodd" />
                </svg>
              </div>
              <h4 class="font-bold text-lg uppercase tracking-wider opacity-90">Step-Up Auth</h4>
            </div>

            <div class="bg-base-200 rounded-2xl p-6 border border-base-300">
              {#if securityModeEnabled}
                <div class="flex items-center justify-between">
                  <div>
                    <p class="font-bold text-base mb-1">Protection PIN Active</p>
                    <p class="text-xs opacity-60">Session unfreezing is protected by your 6-digit code.</p>
                  </div>
                  <div class="badge badge-success py-4 px-4 font-bold">ACTIVE</div>
                </div>
              {:else}
                <div class="form-control mb-4">
                  <label class="label pb-1" for="security-pin">
                    <span class="label-text font-bold text-xs uppercase opacity-70">Register 6-Digit PIN</span>
                  </label>
                  <input
                    id="security-pin"
                    type="password"
                    placeholder="Enter 6-digit PIN"
                    maxlength="6"
                    class="input input-bordered focus:input-warning w-full tracking-[1em] font-mono text-center"
                    bind:value={securitySetupPin}
                  />
                </div>
                <button class="btn btn-warning btn-block shadow-lg" on:click={enableSecurity}>
                  Complete Security Registration
                </button>
              {/if}
            </div>
          </section>
        </div>

        <div class="p-6 bg-base-200 border-t border-base-300 flex justify-end">
          <button class="btn btn-ghost px-8" on:click={() => {
            showSecuritySetupModal = false;
            isSettingUpTOTP = false;
            qrCodeBase64 = "";
            totpSecretText = "";
            setupTotpCode = "";
            totpVerifyError = "";
          }}>Done</button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Create Chat Modal -->
  {#if showCreateChatModal}
    <div class="modal modal-open z-50">
      <div class="modal-box max-w-md p-8">
        <h3 class="font-black text-2xl mb-6 text-primary">New Conversation</h3>
        <div class="space-y-6">
          <div class="form-control">
            <label class="label pb-1" for="room-name">
              <span class="label-text font-bold text-xs uppercase opacity-70">Room Name</span>
            </label>
            <input
              id="room-name"
              type="text"
              placeholder="e.g. Project X"
              class="input input-bordered focus:input-primary w-full"
              bind:value={newChatName}
            />
          </div>
          
          <div class="form-control">
            <label class="label pb-1" for="add-member">
              <span class="label-text font-bold text-xs uppercase opacity-70">Add Members</span>
            </label>
            <div class="join w-full">
              <input
                id="add-member"
                type="text"
                placeholder="Username"
                class="input input-bordered join-item w-full focus:input-primary"
                bind:value={memberToAdd}
              />
              <button class="btn btn-primary join-item" on:click={addMember}>Add</button>
            </div>
          </div>

          {#if newChatMembers.length > 0}
            <div class="bg-base-200 rounded-xl p-4">
              <span class="text-[10px] font-bold uppercase opacity-50 block mb-3">Participants</span>
              <div class="flex flex-wrap gap-2">
                {#each newChatMembers as m}
                  <div class="badge badge-lg py-4 badge-ghost gap-2 border-base-300">
                    <span class="font-bold">{m}</span>
                    <button class="hover:text-error transition-colors" on:click={() => (newChatMembers = newChatMembers.filter(x => x !== m))}>
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                      </svg>
                    </button>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
          
          <div class="modal-action mt-8">
            <button class="btn btn-ghost" on:click={() => (showCreateChatModal = false)}>Cancel</button>
            <button class="btn btn-primary px-8 shadow-lg" on:click={createChat}>Create Room</button>
          </div>
        </div>
      </div>
    </div>
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
