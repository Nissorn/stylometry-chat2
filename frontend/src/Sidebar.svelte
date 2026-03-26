<script>
  import { onMount } from 'svelte';
  import { selectedChatId, chats } from './store.js';
  import { getApiBaseUrl } from './config.js';

  export let token = "";

  // Create Modal State
  const API_BASE = getApiBaseUrl();

  let showModal = false;
  let newChatName = "";
  let isGroupChat = false;
  let memberInput = "";
  let memberUsernames = [];

  async function fetchChats() {
    try {
      const res = await fetch(`${API_BASE}/chats/me`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        let data = await res.json();
        chats.set(data);
      }
    } catch (e) {
      console.error(e);
    }
  }

  function addMember() {
    const trimmed = memberInput.trim();
    if (trimmed && !memberUsernames.includes(trimmed)) {
      memberUsernames = [...memberUsernames, trimmed];
    }
    memberInput = "";
  }

  function removeMember(username) {
    memberUsernames = memberUsernames.filter(u => u !== username);
  }

  function resetModal() {
    newChatName = "";
    isGroupChat = false;
    memberInput = "";
    memberUsernames = [];
    showModal = false;
  }

  async function createChat() {
    if (!newChatName.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/chats/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          name: newChatName,
          is_group: isGroupChat,
          member_usernames: isGroupChat ? memberUsernames : []
        })
      });
      if (res.ok) {
        resetModal();
        fetchChats();
      } else {
        const errorData = await res.json();
        alert(`Error: ${errorData.detail || 'Could not create chat. Ensure usernames are correct.'}`);
      }
    } catch (e) {
      console.error(e);
    }
  }

  onMount(() => {
    fetchChats();
  });

  function selectChat(id) {
    selectedChatId.set(id);
  }

  function getAvatarColor(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    const c = (hash & 0x00FFFFFF).toString(16).toUpperCase();
    return '#' + '00000'.substring(0, 6 - c.length) + c;
  }
</script>

<div class="w-80 bg-base-100 shadow-xl rounded-box flex flex-col shrink-0 h-full overflow-hidden border border-base-300">
  <!-- Header -->
  <div class="bg-base-100 p-5 font-bold border-b border-base-200 flex justify-between items-center z-10">
    <span class="text-xl tracking-wide">Chats</span>
    <button class="btn btn-circle btn-sm btn-ghost hover:bg-base-200 transition-colors" on:click={() => showModal = true}>
      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
      </svg>
    </button>
  </div>

  <!-- Chat List -->
  <div class="flex-1 overflow-y-auto p-3 bg-base-100/50 space-y-1 custom-scrollbar">
    {#each $chats as chat}
      {@const chatName = chat.name || `Chat #${chat.id}`}
      {@const isActive = $selectedChatId === chat.id}
      <button
        class="w-full flex items-center gap-3 p-3 rounded-2xl transition-all duration-200 {isActive ? 'bg-primary/10 border border-primary/20' : 'hover:bg-base-200 border border-transparent'}"
        on:click={() => selectChat(chat.id)}
      >
        <!-- Avatar -->
        <div class="avatar placeholder">
          <div class="bg-neutral text-neutral-content rounded-full w-12 h-12 flex-shrink-0" style="background-color: {getAvatarColor(chatName)}">
            <span class="text-lg font-bold text-white shadow-sm">{chatName.charAt(0).toUpperCase()}</span>
          </div>
        </div>

        <!-- Chat Info -->
        <div class="flex-1 text-left overflow-hidden">
          <div class="font-semibold text-[15px] truncate flex items-center gap-1 {isActive ? 'text-primary drop-shadow-sm' : 'text-base-content'}">
            {#if chat.is_group}
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 opacity-70" viewBox="0 0 20 20" fill="currentColor">
                <path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v3h8v-3zM6 8a2 2 0 11-4 0 2 2 0 014 0zM16 18v-3a5.972 5.972 0 00-.75-2.906A3.005 3.005 0 0119 15v3h-3zM4.75 12.094A5.973 5.973 0 004 15v3H1v-3a3 3 0 013.75-2.906z" />
              </svg>
            {:else}
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 opacity-70" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clip-rule="evenodd" />
              </svg>
            {/if}
            {chatName}
          </div>
          <div class="text-xs text-base-content/50 truncate mt-0.5">
            {chat.is_group ? `${chat.members?.length || 0} Members` : 'Personal Secure Chat'}
          </div>
        </div>

        <!-- Unread / Indicator -->
        {#if isActive}
          <div class="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
        {/if}
      </button>
    {/each}

    {#if $chats.length === 0}
      <div class="flex flex-col items-center justify-center h-40 text-base-content/40 space-y-3">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-10 w-10 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
        <div class="text-sm font-medium">No active chats</div>
      </div>
    {/if}
  </div>
</div>

<!-- Modal for New Chat -->
{#if showModal}
<dialog class="modal modal-open">
  <div class="modal-box rounded-2xl p-0 overflow-hidden shadow-2xl border border-base-300">
    <div class="bg-base-200/50 p-6 border-b border-base-300 flex justify-between items-start">
      <div>
        <h3 class="font-bold text-xl flex items-center gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-primary" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd" />
          </svg>
          Create New Chat
        </h3>
        <p class="text-sm text-base-content/60 mt-1">Start a new stylometry-protected conversation</p>
      </div>
      <!-- Group Chat Toggle Mini -->
      <div class="form-control">
        <label class="label cursor-pointer gap-2">
          <span class="label-text font-semibold text-xs text-base-content/70 uppercase">Group</span>
          <input type="checkbox" class="toggle toggle-primary toggle-sm" bind:checked={isGroupChat} />
        </label>
      </div>
    </div>

    <div class="p-6 space-y-4 bg-base-100">
      <!-- Room Name Input -->
      <div class="form-control w-full">
        <label class="label pt-0"><span class="label-text font-medium text-base-content/80">Room Name</span></label>
        <input
          type="text"
          placeholder="e.g. Project Alpha"
          class="input input-bordered w-full focus:input-primary transition-all rounded-xl"
          bind:value={newChatName}
          on:keydown={(e) => { if (e.key === 'Enter' && !isGroupChat) createChat(); }}
          autofocus
        />
      </div>

      <!-- Additive Modal Component: Dynamic Member Logic for Group Chat -->
      {#if isGroupChat}
      <div class="form-control w-full mt-4 bg-base-200/40 p-3 rounded-xl border border-base-200">
        <label class="label pt-0"><span class="label-text font-medium text-base-content/80">Add Members (Usernames)</span></label>

        <!-- Add Users visually -->
        <div class="flex flex-wrap gap-2 mb-2">
          {#each memberUsernames as member}
            <div class="badge badge-accent badge-lg gap-1 shadow-sm font-semibold">
              {member}
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" class="inline-block w-4 h-4 stroke-current cursor-pointer hover:text-error" on:click={() => removeMember(member)}>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
              </svg>
            </div>
          {/each}
        </div>

        <!-- Input for users -->
        <div class="flex gap-2">
          <input
            type="text"
            placeholder="Type a username..."
            class="input input-bordered input-sm w-full focus:input-accent"
            bind:value={memberInput}
            on:keydown={(e) => e.key === 'Enter' && addMember()}
          />
          <button class="btn btn-sm btn-accent" on:click={addMember}>Add</button>
        </div>
        <span class="text-xs opacity-50 py-1">* You will automatically be included in this room.</span>
      </div>
      {/if}
    </div>

    <!-- Footer Buttons -->
    <div class="p-4 bg-base-200/30 flex justify-end gap-3 rounded-b-2xl">
      <button class="btn btn-ghost rounded-xl px-5" on:click={resetModal}>Cancel</button>
      <button class="btn btn-primary rounded-xl px-6 shadow-md" on:click={createChat} disabled={!newChatName.trim()}>
        {isGroupChat ? 'Create Group Chat' : 'Create Chat'}
      </button>
    </div>
  </div>

  <form method="dialog" class="modal-backdrop bg-neutral/60 backdrop-blur-sm" on:click={resetModal}>
    <button>close</button>
  </form>
</dialog>
{/if}

<style>
  .custom-scrollbar::-webkit-scrollbar {
    width: 6px;
  }
  .custom-scrollbar::-webkit-scrollbar-track {
    background: transparent;
  }
  .custom-scrollbar::-webkit-scrollbar-thumb {
    background-color: rgba(150, 150, 150, 0.2);
    border-radius: 10px;
  }
  .custom-scrollbar:hover::-webkit-scrollbar-thumb {
    background-color: rgba(150, 150, 150, 0.4);
  }
</style>
