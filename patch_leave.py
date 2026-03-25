import os

# 1. Update Backend
chat_path = "backend/app/chat.py"
with open(chat_path, "r") as f:
    chat_text = f.read()

delete_chat_code = """
@router.delete("/{chat_id}")
def delete_chat(chat_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    # Verify membership
    member = db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == current_user.id).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this chat")
        
    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
        
    # Delete all members and messages (Cascade usually handles docs, but explicit is safer here)
    db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id).delete()
    db.query(models.Message).filter(models.Message.chat_id == chat_id).delete()
    
    # Delete chat
    db.delete(chat)
    db.commit()
    return {"status": "deleted"}
"""
chat_text += delete_chat_code
with open(chat_path, "w") as f:
    f.write(chat_text)


# 2. Update Frontend
app_path = "frontend/src/App.svelte"
with open(app_path, "r") as f:
    app_text = f.read()

# Add logic for delete/leave
script_logic = """
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
"""

app_text = app_text.replace("async function addGroupMember() {", script_logic + "\n  async function addGroupMember() {")


# Update UI (Header dropdown)
old_hdr = """            <button class="btn btn-sm btn-outline btn-accent rounded-xl" on:click={() => showMemberModal = true}>
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 mr-1">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 8.614 8.614 0 00-5.46-1.503M15 19.128a3.001 3.001 0 01-5.714 0m5.714 0a3.002 3.002 0 01-5.714 0M15 19.128a9.38 9.38 0 01-2.625.372 8.614 8.614 0 015.46-1.503M8.25 15.6a9.381 9.381 0 015.714 0m-5.714 0A8.616 8.616 0 0110.875 14m-2.625 1.6a9.381 9.381 0 01-2.625-.372" />
              </svg>
              Manage Members
            </button>
          {/if}
        </div>"""

new_hdr = """            <button class="btn btn-sm btn-outline btn-accent rounded-xl" on:click={() => showMemberModal = true}>
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 mr-1">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 8.614 8.614 0 00-5.46-1.503M15 19.128a3.001 3.001 0 01-5.714 0m5.714 0a3.002 3.002 0 01-5.714 0M15 19.128a9.38 9.38 0 01-2.625.372 8.614 8.614 0 015.46-1.503M8.25 15.6a9.381 9.381 0 015.714 0m-5.714 0A8.616 8.616 0 0110.875 14m-2.625 1.6a9.381 9.381 0 01-2.625-.372" />
              </svg>
              Manage Members
            </button>
          {/if}
          
          {#if activeChat}
            <div class="dropdown dropdown-end ml-2">
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
        </div>"""

app_text = app_text.replace(old_hdr, new_hdr)

with open(app_path, "w") as f:
    f.write(app_text)

print("done")
