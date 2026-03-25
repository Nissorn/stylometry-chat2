<script>
  import { onMount } from 'svelte';
  import Sidebar from './Sidebar.svelte';
  import { selectedChatId } from './store.js';
  import { chats } from './store.js';

  $: activeChat = $chats.find(c => c.id === $selectedChatId);
  let showMemberModal = false;
  let newMemberUsername = "";

  
  async function leaveChat() {
    if(!confirm('Are you sure you want to leave this group?')) return;
    try {
      const res = await fetch(`${API_BASE}/chats/${$selectedChatId}/members/${currentUser}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        selectedChatId.set(null);
        const chatsRes = await fetch(`${API_BASE}/chats/me`, { headers: { "Authorization": `Bearer ${token}` } });
        if(chatsRes.ok) chats.set(await chatsRes.json());
      }
    } catch(e) {}
  }

  async function deleteChat() {
    if(!confirm('Delete this entire chat room for everyone?')) return;
    try {
      const res = await fetch(`${API_BASE}/chats/${$selectedChatId}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        selectedChatId.set(null);
        const chatsRes = await fetch(`${API_BASE}/chats/me`, { headers: { "Authorization": `Bearer ${token}` } });
        if(chatsRes.ok) chats.set(await chatsRes.json());
      }
    } catch(e) {}
  }

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
        const chatsRes = await fetch(`${API_BASE}/chats/me`, { headers: { "Authorization": `Bearer ${token}` } });
        if(chatsRes.ok) chats.set(await chatsRes.json());
      } else {
        const data = await res.json();
        alert(data.detail || "Error adding member");
      }
    } catch(e) {}
  }

  async function removeGroupMember(username) {
    if(!confirm(`Remove ${username} from group?`)) return;
    try {
      const res = await fetch(`${API_BASE}/chats/${$selectedChatId}/members/${username}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const chatsRes = await fetch(`${API_BASE}/chats/me`, { headers: { "Authorization": `Bearer ${token}` } });
        if(chatsRes.ok) {
            let data = await chatsRes.json();
            chats.set(data);
            // Check if kicked
            let stillIn = data.find(c => c.id === $selectedChatId);
            if (!stillIn) {
                selectedChatId.set(null);
                showMemberModal = false;
            }
        }
      } else {
        const data = await res.json();
        alert(data.detail || "Error removing member");
      }
    } catch(e) {}
  }


  let isLogin = true;
  let username = "";
  let password = "";
  let totpCode = ""; // Optional 2FA for login
  let errorMessage = "";
  let successMessage = "";

  // State
  let isAuthenticated = false;
  let currentUser = "";
  let token = "";
  let isTotpEnabled = false;

  // TOTP Dashboard State
  let qrCodeBase64 = "";
  let totpSecretText = "";
  let setupTotpCode = "";
  let isSettingUpTOTP = false;

  // Real-time Chat State
  let messages = [];
  let chatInput = "";
  let ws = null;
  let chatContainer;
  
  // Trust State
  let trustScore = 100.0;
  let showDebug = false;
  let securityEnforcement = true;

  const API_BASE = "http://localhost:8000";

  onMount(() => {
    const storedToken = localStorage.getItem("token");
    const storedUser = localStorage.getItem("username");
    const storedTotp = localStorage.getItem("isTotpEnabled");
    if (storedToken && storedUser) {
      token = storedToken;
      currentUser = storedUser;
      if (storedTotp === "true") isTotpEnabled = true;
      isAuthenticated = true;
    }
  });

  let currentWsId = null;
  $: if (isAuthenticated && $selectedChatId && $selectedChatId !== currentWsId) {
    if (ws) {
      ws.close();
      ws = null;
    }
    messages = [];
    trustScore = 100.0;
    fetchChatHistory($selectedChatId);
    connectWebSocket($selectedChatId);
    currentWsId = $selectedChatId;
  }

  async function fetchChatHistory(chatId) {
    if (!chatId) return;
    try {
      const res = await fetch(`${API_BASE}/chats/${chatId}/messages`, {
         headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
         const rawMessages = await res.json();
         messages = rawMessages.map(m => ({ 
             sender: m.sender_username, 
             text: m.text, 
             timestamp: m.timestamp 
         }));
         scrollToBottom();
      }
    } catch(e) {}
  }

  function connectWebSocket(chatId) {
    if (!chatId) return;
    const wsUrl = `ws://localhost:8000/ws/chat/${chatId}?token=${token}`;
    ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "chat") {
        // Broadcast format: {type:"chat", sender:username, message:text, is_broadcast:true}
        // Legacy echo format: {type:"chat", sender:"me"/"bot", text:...}
        const text = data.is_broadcast ? data.message : (data.text || data.message || "");
        messages = [...messages, { sender: data.sender, text, timestamp: new Date().toISOString() }];
        scrollToBottom();
      } else if (data.type === "trust_update") {
        trustScore = data.trust_score;
      } else if (data.sender && (data.text || data.message)) { // fallback
        const text = data.message || data.text;
        messages = [...messages, { sender: data.sender, text, timestamp: new Date().toISOString() }];
        scrollToBottom();
      }
    };

    const thisWs = ws;
    thisWs.onclose = (event) => {
      console.log("WebSocket Disconnected", event.code);
      // Only set ws to null if the active global ws is still THIS socket.
      // This prevents race conditions when switching chats rapidly.
      if (ws === thisWs) {
        ws = null;
      }
      if (event.code === 4001) {
        forceLockout();
      }
    };
  }

  function forceLockout() {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    localStorage.removeItem("isTotpEnabled");
    isAuthenticated = false;
    currentUser = "";
    token = "";
    isTotpEnabled = false;
    isSettingUpTOTP = false;
    qrCodeBase64 = "";
    totpSecretText = "";
    setupTotpCode = "";
    messages = [];
    trustScore = 100.0;
    
    if (ws) {
      ws.close();
      ws = null;
    }
    
    isLogin = true;
    errorMessage = "Session locked due to unusual typing behavior. Please re-authenticate.";
    successMessage = "";
  }
  
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
    if (event.key === 'Enter') {
      sendChatMessage();
    }
  }

    $: messages, scrollToBottom();

  function scrollToBottom() {
    setTimeout(() => {
      if (chatContainer) {
        chatContainer.scrollTop = chatContainer.scrollHeight;
      }
    }, 50);
  }

  function toggleMode() {
    isLogin = !isLogin;
    username = "";
    password = "";
    totpCode = "";
    errorMessage = "";
    successMessage = "";
  }

  function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    localStorage.removeItem("isTotpEnabled");
    isAuthenticated = false;
    currentUser = "";
    token = "";
    isTotpEnabled = false;
    isSettingUpTOTP = false;
    qrCodeBase64 = "";
    totpSecretText = "";
    setupTotpCode = "";
    errorMessage = "";
    successMessage = "";
    trustScore = 100.0;
    
    if (ws) {
      ws.close();
      ws = null;
    }
    messages = [];
  }

  async function handleSubmit(event) {
    event.preventDefault();
    errorMessage = "";
    successMessage = "";
    
    const endpoint = isLogin ? "/auth/login" : "/auth/register";
    const payload = { username, password };
    if (isLogin && totpCode) payload.totp_code = totpCode;
    
    try {
      const response = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        // FastAPI returns detail as Array of objects (422) or String (400)
        errorMessage = Array.isArray(data.detail) ? data.detail[0].msg : (data.detail || "Authentication failed");
        return;
      }
      
      // Store on success
      token = data.access_token;
      currentUser = username;
      isTotpEnabled = data.is_totp_enabled || false;
      
      localStorage.setItem("token", token);
      localStorage.setItem("username", currentUser);
      localStorage.setItem("isTotpEnabled", isTotpEnabled.toString());
      isAuthenticated = true;
      
    } catch (error) {
      errorMessage = "Network error. Please try again.";
    }
  }

  async function generateTOTP() {
    errorMessage = "";
    successMessage = "";
    isSettingUpTOTP = true;
    
    try {
      const response = await fetch(`${API_BASE}/auth/totp/generate?username=${encodeURIComponent(currentUser)}`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`
        }
      });
      const data = await response.json();
      
      if (response.ok) {
        qrCodeBase64 = data.qr_code;
        totpSecretText = data.secret;
      } else {
        errorMessage = Array.isArray(data.detail) ? data.detail[0].msg : (data.detail || "Failed to generate 2FA");
      }
    } catch (error) {
      errorMessage = "Network Error during 2FA generation";
    }
  }

  async function verifyTOTP() {
    errorMessage = "";
    successMessage = "";
    
    try {
      const response = await fetch(`${API_BASE}/auth/totp/verify?username=${encodeURIComponent(currentUser)}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ totp_code: setupTotpCode })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        successMessage = "2FA Enabled Successfully!";
        isTotpEnabled = true;
        localStorage.setItem("isTotpEnabled", "true");
        
        isSettingUpTOTP = false;
        qrCodeBase64 = "";
        totpSecretText = "";
        setupTotpCode = "";
        
        // Optionally update token if a new one was issued
        if (data.access_token) {
          token = data.access_token;
          localStorage.setItem("token", token);
        }
      } else {
        errorMessage = Array.isArray(data.detail) ? data.detail[0].msg : (data.detail || "Invalid 2FA Code");
      }
    } catch (error) {
      errorMessage = "Network Error verifying 2FA";
    }
  }
</script>

<main class="min-h-screen flex items-center justify-center bg-base-200">
  {#if !isAuthenticated}
  <div class="card w-full max-w-sm shadow-2xl bg-base-100">
    <div class="card-body">
      <h2 class="card-title text-2xl justify-center font-bold mb-4">
        {isLogin ? 'Login to Stylometry' : 'Create Account'}
      </h2>
      
      {#if errorMessage}
        <div class="alert alert-error text-sm mb-4">
          <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
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

        <!-- Optional 2FA code field only shown in Login Mode -->
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
  <div class="w-full h-screen flex flex-col bg-base-200">
    <div class="navbar bg-base-100 shadow-sm px-4 shrink-0">
      <div class="flex-1">
        <a href="/" class="btn btn-ghost text-xl">Stylometry Chat</a>
      </div>
      <div class="flex-none gap-2 flex items-center">
        <!-- Security Enforcement Toggle -->
        <label class="swap swap-flip mr-4 text-xs font-semibold cursor-pointer">
          <input type="checkbox" bind:checked={securityEnforcement} />
          <div class="swap-on text-error">Security: ON</div>
          <div class="swap-off opacity-40">Security: OFF</div>
        </label>

        <!-- Status Feedback -->
        <div class="hidden md:block mr-4 text-[10px] uppercase tracking-tighter font-bold">
          {#if securityEnforcement}
            <span class="text-error animate-pulse">● Status: Active Protection</span>
          {:else}
            <span class="text-base-content opacity-40">○ Status: Monitoring Disabled (Data Collection Mode)</span>
          {/if}
        </div>

        <!-- Debug Toggle -->
        <label class="swap swap-flip mr-4 text-xs font-semibold cursor-pointer">
          <input type="checkbox" bind:checked={showDebug} />
          <div class="swap-on text-primary">Debug: ON</div>
          <div class="swap-off opacity-40">Debug: OFF</div>
        </label>
        
        {#if showDebug}
          <div class="radial-progress text-sm mr-4 {trustScore > 80 ? 'text-success' : trustScore > 40 ? 'text-warning' : 'text-error'}" style="--value:{trustScore}; --size:3rem; --thickness: 4px;" role="progressbar">{Math.round(trustScore)}</div>
        {/if}

        <span class="text-sm font-semibold mr-2">Welcome, {currentUser}</span>
        <button class="btn btn-outline btn-error btn-sm" on:click={logout}>
          Logout
        </button>
      </div>
    </div>
    
    <div class="flex-1 flex flex-col lg:flex-row gap-6 p-6 overflow-hidden">
      <Sidebar {token} />
      
      <!-- Main Dashboard Chat Interface -->
      <div class="flex-1 flex flex-col bg-base-100 shadow-xl rounded-box overflow-hidden h-full">
        <div class="bg-base-200 p-4 border-b border-base-300 flex justify-between items-center z-10 shadow-sm">
          <div class="font-bold text-lg flex items-center gap-2">
            {#if activeChat}
              {activeChat.name || `Room #${activeChat.id}`}
              {#if activeChat.is_group}
                <span class="badge badge-accent badge-sm font-semibold">{activeChat.members?.length || 0} Members</span>
              {/if}
            {:else}
              Select a Chat
            {/if}
          </div>
          <div class="flex items-center gap-1">
            {#if activeChat && activeChat.is_group}
              <button class="btn btn-sm btn-circle btn-ghost text-base-content/70 hover:text-primary transition-colors tooltip tooltip-bottom" data-tip="Manage Members" on:click={() => showMemberModal = true}>
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 8.614 8.614 0 00-5.46-1.503M15 19.128a3.001 3.001 0 01-5.714 0m5.714 0a3.002 3.002 0 01-5.714 0M15 19.128a9.38 9.38 0 01-2.625.372 8.614 8.614 0 015.46-1.503M8.25 15.6a9.381 9.381 0 015.714 0m-5.714 0A8.616 8.616 0 0110.875 14m-2.625 1.6a9.381 9.381 0 01-2.625-.372" />
                </svg>
              </button>
            {/if}
          
          {#if activeChat}
            <!-- 3 dots is already implemented -->
            <div class="dropdown dropdown-end">
              <label tabindex="0" class="btn btn-sm btn-circle btn-ghost">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" class="inline-block w-5 h-5 stroke-current"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z"></path></svg>
              </label>
              <ul tabindex="0" class="dropdown-content z-[1] menu p-2 shadow bg-base-100 rounded-box w-40 border border-base-200">
                {#if activeChat.is_group}
                  <li><button class="text-error font-semibold" on:click={leaveChat}>Leave Group</button></li>
                {:else}
                  <li><button class="text-error font-semibold" on:click={deleteChat}>Delete Chat</button></li>
                {/if}
              </ul>
            </div>
          {/if}
          </div>
        </div>
        
        {#if !$selectedChatId}
          <div class="flex-1 flex items-center justify-center text-base-content/50">
            Please select a chat room or create a new one from the sidebar.
          </div>
        {:else}
        <div class="flex-1 p-4 overflow-y-auto" bind:this={chatContainer}>
          {#if messages.length === 0}
            <div class="text-center text-base-content/50 mt-10">
              <p>Welcome to Thai Stylometry Chat!</p>
              <p class="text-sm">Say hello to the Tester Bot...</p>
            </div>
          {/if}
          
          {#each messages as msg}
            <div class="chat {msg.sender === currentUser ? 'chat-end' : 'chat-start'} mb-2">
              <div class="chat-header text-xs opacity-60 mb-1 font-semibold flex gap-2 items-center">
                {msg.sender === currentUser ? 'You' : msg.sender}
              </div>
              <div class="chat-bubble shadow-sm {msg.sender === currentUser ? 'bg-primary text-primary-content' : 'bg-base-200 text-base-content'}">
                {msg.text}
              </div>
              <div class="chat-footer opacity-40 text-[10px] mt-1">
                {msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : ''}
              </div>
            </div>
          {/each}
        </div>
        
        <div class="p-4 bg-base-200 border-t border-base-300 flex gap-2">
          <input 
            type="text" 
            class="input input-bordered flex-1" 
            placeholder="Type a message..." 
            bind:value={chatInput}
            on:keydown={handleChatKeydown}
          />
          <button class="btn btn-primary" on:click={sendChatMessage}>Send</button>
        </div>
        {/if}
      </div>
      
      <!-- Security Settings Panel -->
      <div class="card w-full lg:w-96 bg-base-100 shadow-xl h-fit shrink-0">
        <div class="card-body">
          <h2 class="card-title text-xl border-b pb-2 mb-4">Security Settings</h2>
          
          {#if successMessage}
            <div class="alert alert-success text-sm mb-4">
              <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              <span>{successMessage}</span>
            </div>
          {/if}

          {#if errorMessage}
            <div class="alert alert-error text-sm mb-4">
              <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              <span>{errorMessage}</span>
            </div>
          {/if}

          {#if isTotpEnabled}
             <div class="alert alert-success text-sm mb-4">
              <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              <span>✅ 2FA is securely enabled for your account.</span>
            </div>
          {:else if !isSettingUpTOTP}
            <p class="text-sm text-base-content/80 mb-4">Protect your account with Two-Factor Authentication (2FA).</p>
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
                <button class="btn btn-success btn-sm w-full" on:click={verifyTOTP} disabled={setupTotpCode.length !== 6}>
                  Verify & Save
                </button>
                <button class="btn btn-ghost btn-sm w-full mt-2" on:click={() => {isSettingUpTOTP = false; qrCodeBase64 = "";}}>
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

  <!-- Manage Members Modal -->
  {#if showMemberModal && activeChat}
  <dialog class="modal modal-open">
    <div class="modal-box rounded-2xl p-0 overflow-hidden border border-base-300 shadow-2xl">
      <div class="bg-base-200/50 p-6 border-b border-base-300 flex justify-between items-center">
        <h3 class="font-bold text-xl flex items-center gap-2">
          Manage Group Members
        </h3>
        <button class="btn btn-sm btn-circle btn-ghost" on:click={() => showMemberModal = false}>✕</button>
      </div>
      <div class="p-6 bg-base-100">
        <div class="flex gap-2 mb-6">
          <input type="text" placeholder="Add Username..." class="input input-bordered w-full focus:input-accent" bind:value={newMemberUsername} on:keydown={(e) => e.key === 'Enter' && addGroupMember()}/>
          <button class="btn btn-accent px-6" on:click={addGroupMember} disabled={!newMemberUsername.trim()}>Add</button>
        </div>
        
        <div class="text-sm font-semibold mb-2 text-base-content/80">Current Members ({activeChat.members.length})</div>
        <div class="space-y-2 max-h-60 overflow-y-auto">
          {#each activeChat.members as member}
            <div class="flex justify-between items-center bg-base-200/50 p-3 rounded-xl border border-base-200">
              <span class="font-medium text-[15px] {member.username === currentUser ? 'text-primary' : ''}">{member.username} {member.username === currentUser ? '(You)' : ''}</span>
              {#if member.username !== currentUser}
                <button class="btn btn-xs btn-error btn-outline" on:click={() => removeGroupMember(member.username)}>Remove</button>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    </div>
    <form method="dialog" class="modal-backdrop bg-neutral/60 backdrop-blur-sm" on:click={() => showMemberModal = false}>
      <button>close</button>
    </form>
  </dialog>
  {/if}
</main>

