import os

file_path = "frontend/src/App.svelte"
with open(file_path, "r") as f:
    text = f.read()

# Add script variables
script_addition = """  import { chats } from './store.js';

  $: activeChat = $chats.find(c => c.id === $selectedChatId);
  let showMemberModal = false;
  let newMemberUsername = "";

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
"""

text = text.replace(
    "import { selectedChatId } from './store.js';",
    "import { selectedChatId } from './store.js';\n" + script_addition
)

# Replace Chat header
old_hdr = """        <div class="bg-base-200 p-4 font-bold border-b border-base-300">
          {$selectedChatId ? `Room #${$selectedChatId}` : 'Select a Chat'}
        </div>"""

new_hdr = """        <div class="bg-base-200 p-4 border-b border-base-300 flex justify-between items-center z-10 shadow-sm">
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
          {#if activeChat && activeChat.is_group}
            <button class="btn btn-sm btn-outline btn-accent rounded-xl" on:click={() => showMemberModal = true}>
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 mr-1">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 8.614 8.614 0 00-5.46-1.503M15 19.128a3.001 3.001 0 01-5.714 0m5.714 0a3.002 3.002 0 01-5.714 0M15 19.128a9.38 9.38 0 01-2.625.372 8.614 8.614 0 015.46-1.503M8.25 15.6a9.381 9.381 0 015.714 0m-5.714 0A8.616 8.616 0 0110.875 14m-2.625 1.6a9.381 9.381 0 01-2.625-.372" />
              </svg>
              Manage Members
            </button>
          {/if}
        </div>"""

text = text.replace(old_hdr, new_hdr)


# Add Modal HTML at the very end of main
modal_html = """
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
"""

text = text.replace("</main>", modal_html)

with open(file_path, "w") as f:
    f.write(text)

print("frontend app.svelte member UI patched")
