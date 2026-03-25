import os

file_path = "frontend/src/App.svelte"
with open(file_path, "r") as f:
    content = f.read()

# 1. Imports
content = content.replace(
    "import { onMount } from 'svelte';",
    "import { onMount } from 'svelte';\n  import Sidebar from './Sidebar.svelte';\n  import { selectedChatId } from './store.js';"
)

# 2. WebSocket connection logic
old_ws_logic = """  $: if (isAuthenticated && !ws) {
    connectWebSocket();
  }

  function connectWebSocket() {
    const wsUrl = `ws://localhost:8000/ws/chat?token=${token}`;"""

new_ws_logic = """  let currentWsId = null;
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
         messages = await res.json();
         scrollToBottom();
      }
    } catch(e) {}
  }

  function connectWebSocket(chatId) {
    if (!chatId) return;
    const wsUrl = `ws://localhost:8000/ws/chat/${chatId}?token=${token}`;"""

content = content.replace(old_ws_logic, new_ws_logic)

# 3. HTML layout injection
old_layout_start = """    <div class="flex-1 flex flex-col lg:flex-row gap-6 p-6 overflow-hidden">
      <!-- Main Dashboard Chat Interface -->
      <div class="flex-1 flex flex-col bg-base-100 shadow-xl rounded-box overflow-hidden h-full">
        <div class="bg-base-200 p-4 font-bold border-b border-base-300">
          Tester Bot Chamber
        </div>
        
        <div class="flex-1 p-4 overflow-y-auto" bind:this={chatContainer}>"""

new_layout_start = """    <div class="flex-1 flex flex-col lg:flex-row gap-6 p-6 overflow-hidden">
      <Sidebar {token} />
      
      <!-- Main Dashboard Chat Interface -->
      <div class="flex-1 flex flex-col bg-base-100 shadow-xl rounded-box overflow-hidden h-full">
        <div class="bg-base-200 p-4 font-bold border-b border-base-300">
          {$selectedChatId ? `Room #${$selectedChatId}` : 'Select a Chat'}
        </div>
        
        {#if !$selectedChatId}
          <div class="flex-1 flex items-center justify-center text-base-content/50">
            Please select a chat room or create a new one from the sidebar.
          </div>
        {:else}
        <div class="flex-1 p-4 overflow-y-auto" bind:this={chatContainer}>"""

content = content.replace(old_layout_start, new_layout_start)

# 4. Closing the if-else for chat container
old_layout_end = """        <div class="p-4 bg-base-200 border-t border-base-300 flex gap-2">
          <input 
            type="text" 
            class="input input-bordered flex-1" 
            placeholder="Type a message..." 
            bind:value={chatInput}
            on:keydown={handleChatKeydown}
          />
          <button class="btn btn-primary" on:click={sendChatMessage}>Send</button>
        </div>
      </div>"""

new_layout_end = """        <div class="p-4 bg-base-200 border-t border-base-300 flex gap-2">
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
      </div>"""

content = content.replace(old_layout_end, new_layout_end)

with open(file_path, "w") as f:
    f.write(content)
print("done frontend")
