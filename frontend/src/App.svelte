<script>
  import { onMount } from 'svelte';

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

  // Step-Up Auth State
  let isSecurityModeEnabled = false;   // tracks whether security_enabled is set in DB
  let isEnablingSecurityMode = false;  // shows the PIN-setup inline form
  let enableSecurityPin = "";          // input for the setup flow
  let enableSecurityError = "";        // inline error for setup
  let showPinModal = false;            // FREEZE challenge — strictly blocking
  let pinModalInput = "";             // 6-digit input for the challenge
  let pinModalError = "";             // wrong-PIN feedback inside modal

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

  $: if (isAuthenticated && !ws) {
    connectWebSocket();
  }

  function connectWebSocket() {
    const wsUrl = `ws://localhost:8000/ws/chat?token=${token}`;
    ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "chat") {
        // Broadcast format: {type:"chat", sender:username, message:text, is_broadcast:true}
        const text = data.is_broadcast ? data.message : (data.text || data.message || "");
        messages = [...messages, { sender: data.sender, text }];
        scrollToBottom();
      } else if (data.type === "trust_update") {
        trustScore = data.trust_score;
      } else if (data.type === "auth_challenge") {
        // FREEZE — show the strictly-blocking PIN modal
        showPinModal = true;
        pinModalInput = "";
        pinModalError = "";
      } else if (data.type === "auth_success") {
        // Only auth_success from the server can close the modal
        showPinModal = false;
        pinModalError = "";
      } else if (data.type === "auth_failed") {
        pinModalError = "Incorrect PIN. Please try again.";
      } else if (data.type === "system_alert") {
        messages = [...messages, { type: "system_alert", text: data.message }];
        scrollToBottom();
      } else if (data.sender && (data.text || data.message)) { // fallback
        const text = data.message || data.text;
        messages = [...messages, { sender: data.sender, text }];
        scrollToBottom();
      }
    };

    ws.onclose = (event) => {
      console.log("WebSocket Disconnected", event.code);
      ws = null;
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

  function sendPinVerify() {
    if (ws && pinModalInput.trim().length === 6) {
      ws.send(JSON.stringify({ type: "verify_pin", pin: pinModalInput.trim() }));
    }
  }

  function handlePinKeydown(event) {
    if (event.key === "Enter") sendPinVerify();
  }

  function handleChatKeydown(event) {
    if (event.key === 'Enter') {
      sendChatMessage();
    }
  }

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
        errorMessage = data.detail || "Authentication failed";
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
        errorMessage = data.detail || "Failed to generate 2FA";
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
        errorMessage = data.detail || "Invalid 2FA Code";
      }
    } catch (error) {
      errorMessage = "Network Error verifying 2FA";
    }
  }
  async function enableSecurityMode() {
    if (enableSecurityPin.length !== 6 || !/^\d{6}$/.test(enableSecurityPin)) {
      enableSecurityError = "PIN must be exactly 6 digits.";
      return;
    }
    enableSecurityError = "";
    try {
      const response = await fetch(`${API_BASE}/auth/security/enable`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ pin: enableSecurityPin })
      });
      const data = await response.json();
      if (response.ok) {
        isSecurityModeEnabled = true;
        isEnablingSecurityMode = false;
        enableSecurityPin = "";
        successMessage = "✅ Security Mode enabled! Your session is now protected by PIN Step-Up Auth.";
      } else {
        enableSecurityError = data.detail || "Failed to enable Security Mode.";
      }
    } catch (e) {
      enableSecurityError = "Network error. Please try again.";
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

        <!-- Enable Security Mode -->
        {#if isSecurityModeEnabled}
          <span class="badge badge-success badge-outline mr-2 text-xs">🛡 Security Mode: ON</span>
        {:else if !isEnablingSecurityMode}
          <button class="btn btn-outline btn-warning btn-xs mr-2" on:click={() => { isEnablingSecurityMode = true; enableSecurityPin = ""; enableSecurityError = ""; }}>
            🔐 Enable Security Mode
          </button>
        {:else}
          <!-- Inline PIN Setup Form -->
          <div class="flex items-center gap-1 mr-2">
            <input
              type="password"
              id="enable-security-pin"
              placeholder="6-digit PIN"
              maxlength="6"
              inputmode="numeric"
              class="input input-xs input-bordered w-24 text-center tracking-widest"
              bind:value={enableSecurityPin}
              on:keydown={(e) => { if (e.key === 'Enter') enableSecurityMode(); }}
            />
            <button class="btn btn-success btn-xs" on:click={enableSecurityMode} disabled={enableSecurityPin.length !== 6}>Save</button>
            <button class="btn btn-ghost btn-xs" on:click={() => { isEnablingSecurityMode = false; enableSecurityPin = ""; enableSecurityError = ""; }}>✕</button>
          </div>
          {#if enableSecurityError}
            <span class="text-error text-xs mr-2">{enableSecurityError}</span>
          {/if}
        {/if}

        <button class="btn btn-outline btn-error btn-sm" on:click={logout}>
          Logout
        </button>
      </div>
    </div>
    
    <div class="flex-1 flex flex-col lg:flex-row gap-6 p-6 overflow-hidden">
      <!-- Main Dashboard Chat Interface -->
      <div class="flex-1 flex flex-col bg-base-100 shadow-xl rounded-box overflow-hidden h-full">
        <div class="bg-base-200 p-4 font-bold border-b border-base-300">
          Tester Bot Chamber
        </div>
        
        <div class="flex-1 p-4 overflow-y-auto" bind:this={chatContainer}>
          {#if messages.length === 0}
            <div class="text-center text-base-content/50 mt-10">
              <p>Welcome to Thai Stylometry Chat!</p>
              <p class="text-sm">Say hello to the Tester Bot...</p>
            </div>
          {/if}
          
          {#each messages as msg}
            {#if msg.type === "system_alert"}
              <!-- Centered system alert — not a user bubble -->
              <div class="flex justify-center my-3">
                <div class="alert alert-warning text-xs max-w-lg text-center py-2 px-4 shadow rounded-full font-semibold opacity-90">
                  {msg.text}
                </div>
              </div>
            {:else}
              <div class="chat {msg.sender === currentUser ? 'chat-end' : 'chat-start'}">
                <div class="chat-header text-xs opacity-50 mb-1">
                  {msg.sender}
                </div>
                <div class="chat-bubble {msg.sender === currentUser ? 'chat-bubble-primary' : 'chat-bubble-secondary'}">
                  {msg.text}
                </div>
              </div>
            {/if}
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

  <!-- ───────────────────────────────────────────────────────────────── -->
  <!-- STRICTLY BLOCKING PIN CHALLENGE MODAL                            -->
  <!-- The ONLY exit is receiving auth_success from the WebSocket.      -->
  <!-- There is no ESC handler, no backdrop click, no close button.     -->
  <!-- ───────────────────────────────────────────────────────────────── -->
  {#if showPinModal}
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Identity Verification Required"
    >
      <div class="card w-full max-w-sm bg-base-100 shadow-2xl border-2 border-warning">
        <div class="card-body items-center text-center gap-4">
          <div class="text-4xl">🔐</div>
          <h2 class="card-title text-xl text-warning">Identity Verification Required</h2>
          <p class="text-sm text-base-content/70">
            Unusual typing behavior detected. Enter your 6-digit Security PIN to resume.
          </p>

          {#if pinModalError}
            <div class="alert alert-error text-sm py-2 w-full">
              <span>{pinModalError}</span>
            </div>
          {/if}

          <input
            type="password"
            id="pin-modal-input"
            placeholder="● ● ● ● ● ●"
            maxlength="6"
            inputmode="numeric"
            class="input input-bordered input-lg w-full text-center tracking-[0.5em] text-xl"
            bind:value={pinModalInput}
            on:keydown={handlePinKeydown}
            autofocus
          />

          <button
            class="btn btn-warning w-full btn-lg"
            on:click={sendPinVerify}
            disabled={pinModalInput.trim().length !== 6}
          >
            Verify Identity
          </button>

          <p class="text-xs text-base-content/40 mt-1">
            Your session is paused until verification is complete.
          </p>
        </div>
      </div>
    </div>
  {/if}
</main>
