<script>
  import { onMount } from 'svelte';

  let isLogin = true;
  let username = "";
  let password = "";
  let showPassword = false;
  let totpCode = ""; // Optional 2FA for login
  let showTotpCode = false;
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
  // Navigation & Screen State
  let currentScreen = "welcome"; // welcome, login, register, chat, profile, edit_profile
  
  // Profile Data (State from Backend)
  let profileData = {
    username: "",
    full_name: "",
    email: "",
    birth_date: "",
    age: null,
    gender: "",
    blood_type: "",
    height: null,
    weight: null,
    avatar_url: null,
    is_totp_enabled: false
  };

  // Profile Draft for editing (Form state)
  let profileDraft = { ...profileData };

  const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? "http://localhost:8000"
    : "http://172.20.10.2:8000";

  function getAvatarUrl(url) {
    if (!url) return "";
    if (url.startsWith("data:") || url.startsWith("http")) return url;
    return API_BASE + url;
  }

  let fileInput;

  function triggerFileInput() {
    fileInput.click();
  }

  let selectedImageFile = null;

  function handleFileChange(event) {
    const file = event.target.files[0];
    if (file) {
      selectedImageFile = file;
      const reader = new FileReader();
      reader.onload = (e) => {
        profileDraft.avatar_url = e.target.result;
      };
      reader.readAsDataURL(file);
    }
  }

  function removePhoto() {
    selectedImageFile = null;
    profileDraft.avatar_url = null;
    if (fileInput) fileInput.value = '';
  }

  function handleBirthDateInput(event) {
    let val = event.target.value.replace(/\D/g, '');
    if (val.length > 8) val = val.slice(0, 8);
    let formatted = val;
    if (val.length > 4) {
      formatted = `${val.slice(0, 2)}/${val.slice(2, 4)}/${val.slice(4)}`;
    } else if (val.length > 2) {
      formatted = `${val.slice(0, 2)}/${val.slice(2)}`;
    }
    profileDraft.birth_date = formatted;

    if (formatted.length === 10) {
      const parts = formatted.split('/');
      if (parts.length === 3) {
        const [day, month, year] = parts;
        const dob = new Date(`${year}-${month}-${day}`);
        if (!isNaN(dob.getTime())) {
          const today = new Date();
          let age = today.getFullYear() - dob.getFullYear();
          const m = today.getMonth() - dob.getMonth();
          if (m < 0 || (m === 0 && today.getDate() < dob.getDate())) {
            age--;
          }
          profileDraft.age = age;
        }
      }
    } else {
      profileDraft.age = null;
    }
  }

  async function fetchProfile() {
    const token = localStorage.getItem("token");
    if (!token) return;

    try {
      const response = await fetch(`${API_BASE}/auth/profile`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (response.ok) {
        profileData = await response.json();
        profileDraft = { ...profileData };
      }
    } catch (error) {
      console.error("Fetch profile failed", error);
    }
  }

  async function saveProfile() {
    const token = localStorage.getItem("token");
    try {
      if (selectedImageFile) {
        const formData = new FormData();
        formData.append("file", selectedImageFile);
        const imgRes = await fetch(`${API_BASE}/auth/upload-image`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${token}` },
          body: formData
        });
        if (imgRes.ok) {
          const data = await imgRes.json();
          profileDraft.avatar_url = data.avatar_url;
        }
      }

      const response = await fetch(`${API_BASE}/auth/profile`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          full_name: profileDraft.full_name,
          email: profileDraft.email,
          birth_date: profileDraft.birth_date,
          age: profileDraft.age,
          gender: profileDraft.gender,
          blood_type: profileDraft.blood_type,
          height: profileDraft.height,
          weight: profileDraft.weight
        })
      });
      if (response.ok) {
        // Use the returned updated profile directly to avoid any browser GET caching issues
        profileData = await response.json();
        profileDraft = { ...profileData };
        selectedImageFile = null;
        successMessage = "Profile updated successfully!";
        goTo('profile');
      } else {
        errorMessage = "Failed to update profile";
      }
    } catch (error) {
      errorMessage = "Network error updating profile";
    }
  }

  onMount(() => {
    const storedToken = localStorage.getItem("token");
    const storedUser = localStorage.getItem("username");
    
    if (storedToken && storedUser) {
      currentUser = storedUser;
      isAuthenticated = true;
      currentScreen = "chat";
      connectWebSocket();
      fetchProfile();
    }
  });

  function goTo(screen) {
    if (screen === 'edit_profile') {
      profileDraft = { ...profileData };
      selectedImageFile = null;
    }
    currentScreen = screen;
    errorMessage = "";
    successMessage = "";
  }

  $: if (isAuthenticated && !ws) {
    connectWebSocket();
  }

  function connectWebSocket() {
    const wsUrl = `ws://172.20.10.2:8000/ws/chat?token=${token}`;
    ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "chat") {
        // Broadcast format: {type:"chat", sender:username, message:text, is_broadcast:true}
        // Legacy echo format: {type:"chat", sender:"me"/"bot", text:...}
        const text = data.is_broadcast ? data.message : (data.text || data.message || "");
        messages = [...messages, { sender: data.sender, text }];
        scrollToBottom();
      } else if (data.type === "trust_update") {
        trustScore = data.trust_score;
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
    currentScreen = isLogin ? "login" : "register";
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
    currentScreen = "welcome";
    
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
      currentScreen = "chat";
      
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

<main class="min-h-screen flex items-center justify-center bg-gray-100 p-4 font-sans">
  {#if currentScreen === 'welcome'}
    <!-- register1 mock-up -->
    <div class="relative w-full max-w-4xl bg-white rounded-3xl shadow-2xl p-8 pt-12 overflow-hidden flex flex-col items-center animate-in fade-in zoom-in duration-300">
      <div class="w-full mb-6"></div>

      <h1 class="text-4xl font-bold text-[#205267] tracking-tight">StyloSense</h1>
      <p class="text-gray-400 mt-2 text-sm italic">Login or signup to continue</p>

      <div class="relative my-12 w-64 h-64 flex items-center justify-center">
        <img src="/assets/welcome_cloud.png" alt="Welcome Character" class="w-full h-full object-contain" />
      </div>

      <div class="w-full space-y-4 mt-8">
        <button on:click={() => { isLogin = false; goTo('register'); }} class="w-full py-4 bg-[#539BB8] text-white font-bold rounded-2xl hover:bg-[#458caf] active:scale-[0.98] transition-all shadow-lg shadow-blue-50/50">
          Create account
        </button>
        <button on:click={() => { isLogin = true; goTo('login'); }} class="w-full py-4 bg-[#7BB2C7] text-white font-bold rounded-2xl hover:bg-[#6aa4b9] active:scale-[0.98] transition-all shadow-lg shadow-blue-50/50">
          Already have an account
        </button>
      </div>
    </div>

  {:else if currentScreen === 'login' || currentScreen === 'register'}
    <!-- Login/Register Screen -->
    <div class="relative w-full max-w-2xl bg-white rounded-3xl shadow-2xl p-8 pt-12 overflow-hidden animate-in fade-in slide-in-from-bottom-4 duration-300">


      <div class="mt-12">
        <h2 class="text-3xl font-bold text-[#205267]">
          {isLogin ? 'Login account' : 'Create account'}
        </h2>
        <p class="text-gray-400 mt-2">
          {isLogin ? 'Welcome back!' : 'Sign up to continue'}
        </p>
      </div>

      {#if errorMessage}
        <div class="mt-6 p-4 bg-red-50 text-red-600 rounded-2xl text-sm flex items-center gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>
          <span>{errorMessage}</span>
        </div>
      {/if}

      <form on:submit={handleSubmit} class="mt-8 space-y-6" novalidate>
        <div class="space-y-2">
          <label class="block text-sm font-medium text-gray-500 ml-1" for="username">Username</label>
          <div class="relative flex items-center">
            <span class="absolute left-4 text-gray-400">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </span>
            <input 
              type="text" 
              id="username"
              placeholder="Username" 
              class="w-full pl-12 pr-4 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl focus:ring-2 focus:ring-[#539BB8] focus:border-transparent outline-none transition-all"
              bind:value={username}
              required
            />
          </div>
        </div>

        <div class="space-y-2">
          <label class="block text-sm font-medium text-gray-500 ml-1" for="password">Password</label>
          <div class="relative flex items-center">
            <span class="absolute left-4 text-gray-400">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            </span>
            <input 
              type={showPassword ? "text" : "password"} 
              id="password"
              placeholder="Password"
              class="w-full pl-12 pr-12 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl focus:ring-2 focus:ring-[#539BB8] focus:border-transparent outline-none transition-all"
              value={password}
              on:input={(e) => password = e.target.value}
              required
            />
            <button type="button" class="absolute right-4 text-gray-400 hover:text-gray-600 focus:outline-none" on:click={() => showPassword = !showPassword}>
              {#if showPassword}
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
              {:else}
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/></svg>
              {/if}
            </button>
          </div>
        </div>

        {#if isLogin}
        <div class="space-y-2">
          <label class="block text-sm font-medium text-gray-500 ml-1" for="totpCode">2FA Code (Optional)</label>
          <div class="relative flex items-center">
            <span class="absolute left-4 text-gray-400">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/></svg>
            </span>
            <input 
              type={showTotpCode ? "text" : "password"} 
              id="totpCode"
              placeholder="123456" 
              class="w-full pl-12 pr-12 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl focus:ring-2 focus:ring-[#539BB8] focus:border-transparent outline-none transition-all"
              value={totpCode}
              on:input={(e) => totpCode = e.target.value}
              maxlength="6"
              inputmode="numeric"
            />
            <button type="button" class="absolute right-4 text-gray-400 hover:text-gray-600 focus:outline-none" on:click={() => showTotpCode = !showTotpCode}>
              {#if showTotpCode}
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
              {:else}
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/></svg>
              {/if}
            </button>
          </div>
        </div>
        {/if}

        <div class="pt-4">
          <button 
            type="submit" 
            class="w-full py-4 bg-[#539BB8] text-white font-bold rounded-2xl hover:bg-[#458caf] active:scale-[0.98] transition-all"
          >
            {isLogin ? 'Login' : 'Create account'}
          </button>
        </div>
      </form>

      <div class="mt-8 text-center">
        <p class="text-gray-400 text-sm">
          {isLogin ? "Don't have an account?" : "Already have an account?"}
          <button on:click={toggleMode} class="font-bold text-[#205267]">
            {isLogin ? 'Sign up' : 'Login'}
          </button>
        </p>
      </div>
    </div>

  {:else if currentScreen === 'chat'}
    <!-- Existing Chat UI with a Profile Button -->
    <div class="w-full h-screen flex flex-col bg-base-200">
      <div class="navbar bg-base-100 shadow-sm px-4 shrink-0">
        <div class="flex-1">
          <a href="/" class="btn btn-ghost text-xl text-[#205267] font-bold">Stylometry Chat</a>
        </div>
        <div class="flex-none gap-2 flex items-center">
          <label class="swap swap-flip mr-4 text-xs font-semibold cursor-pointer">
            <input type="checkbox" bind:checked={securityEnforcement} />
            <div class="swap-on text-error">Security: ON</div>
            <div class="swap-off opacity-40">Security: OFF</div>
          </label>

          <button class="btn btn-ghost btn-circle" on:click={() => goTo('profile')}>
            <div class="avatar">
              <div class="w-8 rounded-full border border-blue-50 bg-gray-100 overflow-hidden">
                {#if profileData.avatar_url}
                  <img src={getAvatarUrl(profileData.avatar_url)} alt="User Avatar" />
                {/if}
              </div>
            </div>
          </button>

          <span class="text-sm font-semibold hidden md:block">@{currentUser}</span>
        </div>
      </div>
      
      <div class="flex-1 flex flex-col lg:flex-row gap-6 p-6 overflow-hidden">
        <div class="flex-1 flex flex-col bg-base-100 shadow-xl rounded-[32px] overflow-hidden h-full border border-white">
          <div class="bg-gray-50/50 p-4 font-bold border-b border-gray-100 flex items-center justify-between">
            <span class="text-[#205267]">Tester Bot Chamber</span>
            {#if showDebug}
              <div class="flex items-center gap-2">
                <span class="text-[10px] text-gray-400 uppercase tracking-widest">Trust</span>
                <div class="radial-progress text-[10px] {trustScore > 80 ? 'text-success' : trustScore > 40 ? 'text-warning' : 'text-error'}" style="--value:{trustScore}; --size:2rem; --thickness: 3px;" role="progressbar">{Math.round(trustScore)}</div>
              </div>
            {/if}
          </div>
          
          <div class="flex-1 p-4 overflow-y-auto space-y-4" bind:this={chatContainer}>
            {#each messages as msg}
              <div class="chat {msg.sender === currentUser ? 'chat-end' : 'chat-start'}">
                <div class="chat-bubble {msg.sender === currentUser ? 'bg-[#539BB8] text-white' : 'bg-gray-100 text-gray-700'} rounded-2xl shadow-sm border-none">
                  {msg.text}
                </div>
              </div>
            {/each}
          </div>
          
          <div class="p-4 bg-gray-50/50 border-t border-gray-100 flex gap-2">
            <input 
              type="text" 
              class="input bg-white border-gray-100 rounded-2xl flex-1 focus:outline-[#539BB8]" 
              placeholder="Type a message..." 
              bind:value={chatInput}
              on:keydown={handleChatKeydown}
            />
            <button class="btn bg-[#539BB8] hover:bg-[#458caf] text-white border-none rounded-2xl px-6" on:click={sendChatMessage}>Send</button>
          </div>
        </div>
      </div>
    </div>

  {:else if currentScreen === 'profile'}
    <!-- profile mock-up (Settings) -->
    <div class="relative w-full max-w-2xl bg-white rounded-3xl shadow-2xl p-8 pt-12 overflow-hidden flex flex-col animate-in fade-in slide-in-from-right-4 duration-300">
      <div class="w-full flex items-center mb-8">
        <span class="ml-0 font-bold text-gray-700">Setting</span>
      </div>

      <p class="text-gray-400 text-sm italic mb-8">@{profileData.username || currentUser}</p>
      
      <div class="mt-auto pt-8">
        <button on:click={logout} class="w-full flex items-center p-4 bg-gray-50/80 hover:bg-white rounded-2xl transition-all group">
          <span class="text-gray-600 font-medium flex-1 text-left group-hover:text-red-500">Logout</span>
          <svg class="text-gray-300 group-hover:text-red-300 transition-colors" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>
        </button>
      </div>
    </div>

  {:else if currentScreen === 'edit_profile'}
    <!-- edit profile mock-up -->
    <div class="relative w-full max-w-4xl bg-white rounded-3xl shadow-2xl p-8 pt-12 overflow-hidden flex flex-col animate-in fade-in slide-in-from-right-4 duration-300 min-h-[40vh] items-center justify-center">
      <h2 class="text-2xl font-bold text-[#205267]">@{profileData.username || currentUser}</h2>
      <button on:click={() => goTo('profile')} class="mt-8 px-12 py-3 bg-gray-100 text-gray-600 font-bold rounded-2xl hover:bg-gray-200 transition-all">
        Back to Settings
      </button>
    </div>
  {/if}
</main>
