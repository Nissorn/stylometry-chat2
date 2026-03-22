<script>
  import { onMount } from 'svelte';

  let isLogin = true;
  let username = "";
  let password = "";
  let errorMessage = "";

  // State
  let isAuthenticated = false;
  let currentUser = "";
  let token = "";

  const API_BASE = "http://localhost:8000";

  onMount(() => {
    const storedToken = localStorage.getItem("token");
    const storedUser = localStorage.getItem("username");
    if (storedToken && storedUser) {
      token = storedToken;
      currentUser = storedUser;
      isAuthenticated = true;
    }
  });

  function toggleMode() {
    isLogin = !isLogin;
    username = "";
    password = "";
    errorMessage = "";
  }

  function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    isAuthenticated = false;
    currentUser = "";
    token = "";
  }

  async function handleSubmit(event) {
    event.preventDefault();
    errorMessage = "";
    
    const endpoint = isLogin ? "/auth/login" : "/auth/register";
    const payload = { username, password };
    
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
      localStorage.setItem("token", token);
      localStorage.setItem("username", currentUser);
      isAuthenticated = true;
      
    } catch (error) {
      errorMessage = "Network error. Please try again.";
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

      <form on:submit={handleSubmit}>
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
        
        <div class="form-control mb-6">
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
    <div class="navbar bg-base-100 shadow-sm px-4">
      <div class="flex-1">
        <a href="/" class="btn btn-ghost text-xl">Stylometry Chat</a>
      </div>
      <div class="flex-none gap-2">
        <span class="text-sm font-semibold mr-2">Welcome, {currentUser}</span>
        <button class="btn btn-outline btn-error btn-sm" on:click={logout}>
          Logout
        </button>
      </div>
    </div>
    
    <div class="flex-1 flex items-center justify-center p-4">
      <div class="card w-full max-w-lg bg-base-100 shadow-xl">
        <div class="card-body items-center text-center">
          <h2 class="card-title text-3xl mb-4">Welcome to Thai Stylometry Chat!</h2>
          <p class="mb-4">You are securely logged in as <strong>{currentUser}</strong>.</p>
          <p class="text-sm text-base-content/70">The real-time chat interface will be built here shortly.</p>
        </div>
      </div>
    </div>
  </div>
  {/if}
</main>
