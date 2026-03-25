import os

file_path = "frontend/src/App.svelte"
with open(file_path, "r") as f:
    text = f.read()

# 1. Update Manage Members button to an icon
old_member_btn = """          {#if activeChat && activeChat.is_group}
            <button class="btn btn-sm btn-outline btn-accent rounded-xl" on:click={() => showMemberModal = true}>
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 mr-1">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 8.614 8.614 0 00-5.46-1.503M15 19.128a3.001 3.001 0 01-5.714 0m5.714 0a3.002 3.002 0 01-5.714 0M15 19.128a9.38 9.38 0 01-2.625.372 8.614 8.614 0 015.46-1.503M8.25 15.6a9.381 9.381 0 015.714 0m-5.714 0A8.616 8.616 0 0110.875 14m-2.625 1.6a9.381 9.381 0 01-2.625-.372" />
              </svg>
              Manage Members
            </button>
          {/if}"""

new_member_btn = """          <div class="flex items-center gap-1">
            {#if activeChat && activeChat.is_group}
              <button class="btn btn-sm btn-circle btn-ghost text-base-content/70 hover:text-primary transition-colors tooltip tooltip-bottom" data-tip="Manage Members" on:click={() => showMemberModal = true}>
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 8.614 8.614 0 00-5.46-1.503M15 19.128a3.001 3.001 0 01-5.714 0m5.714 0a3.002 3.002 0 01-5.714 0M15 19.128a9.38 9.38 0 01-2.625.372 8.614 8.614 0 015.46-1.503M8.25 15.6a9.381 9.381 0 015.714 0m-5.714 0A8.616 8.616 0 0110.875 14m-2.625 1.6a9.381 9.381 0 01-2.625-.372" />
                </svg>
              </button>
            {/if}"""
text = text.replace(old_member_btn, new_member_btn)

# Make sure the block closes properly for the flex row
old_hdr_end = """          {#if activeChat}
            <div class="dropdown dropdown-end ml-2">"""
new_hdr_end = """          {#if activeChat}
            <!-- 3 dots is already implemented -->
            <div class="dropdown dropdown-end">"""
text = text.replace(old_hdr_end, new_hdr_end)

# Add </div> to close the <div class="flex items-center gap-1">
text = text.replace("</div>\n        </div>\n        \n        {#if !$selectedChatId}", "</div>\n          </div>\n        </div>\n        \n        {#if !$selectedChatId}")

# 2. Fix sender_username bug and add timestamp format helper
old_fetch = """      if (res.ok) {
         messages = await res.json();
         scrollToBottom();
      }"""
new_fetch = """      if (res.ok) {
         const rawMessages = await res.json();
         messages = rawMessages.map(m => ({ 
             sender: m.sender_username, 
             text: m.text, 
             timestamp: m.timestamp 
         }));
         scrollToBottom();
      }"""
text = text.replace(old_fetch, new_fetch)

# Update WS block to add timestamp
old_wsmsg = """        const text = data.is_broadcast ? data.message : (data.text || data.message || "");
        messages = [...messages, { sender: data.sender, text }];"""
new_wsmsg = """        const text = data.is_broadcast ? data.message : (data.text || data.message || "");
        messages = [...messages, { sender: data.sender, text, timestamp: new Date().toISOString() }];"""
text = text.replace(old_wsmsg, new_wsmsg)

# Update WS block fallback
old_ws_fallback = """      } else if (data.sender && (data.text || data.message)) { // fallback
        const text = data.message || data.text;
        messages = [...messages, { sender: data.sender, text }];"""

new_ws_fallback = """      } else if (data.sender && (data.text || data.message)) { // fallback
        const text = data.message || data.text;
        messages = [...messages, { sender: data.sender, text, timestamp: new Date().toISOString() }];"""
text = text.replace(old_ws_fallback, new_ws_fallback)

# 3. Message Bubbles
old_bubble = """          {#each messages as msg}
            <div class="chat {msg.sender === currentUser ? 'chat-end' : 'chat-start'}">
              <div class="chat-header text-xs opacity-50 mb-1">
                {msg.sender}
              </div>
              <div class="chat-bubble {msg.sender === currentUser ? 'chat-bubble-primary' : 'chat-bubble-secondary'}">
                {msg.text}
              </div>
            </div>
          {/each}"""

new_bubble = """          {#each messages as msg}
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
          {/each}"""
text = text.replace(old_bubble, new_bubble)

# Add autoscroll trigger 
scroll_logic = """  $: messages, scrollToBottom();\n"""
text = text.replace("function scrollToBottom() {", scroll_logic + "\n  function scrollToBottom() {")

with open(file_path, "w") as f:
    f.write(text)

print("done ui")
