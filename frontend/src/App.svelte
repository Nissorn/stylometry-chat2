<script>
  let isLogin = true;
  let username = "";
  let password = "";

  function toggleMode() {
    isLogin = !isLogin;
    username = "";
    password = "";
  }

  function handleSubmit(event) {
    event.preventDefault();
    console.log(isLogin ? "Logging in..." : "Registering...", { username, password });
  }
</script>

<main class="min-h-screen flex items-center justify-center bg-base-200">
  <div class="card w-full max-w-sm shadow-2xl bg-base-100">
    <div class="card-body">
      <h2 class="card-title text-2xl justify-center font-bold mb-4">
        {isLogin ? 'Login to Stylometry' : 'Create Account'}
      </h2>
      
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
</main>
