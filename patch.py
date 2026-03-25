import os
file_path = "backend/app/main.py"
with open(file_path, "r") as f:
    content = f.read()

# Replace websocket route
content = content.replace(
    "@app.websocket(\"/ws/chat\")",
    "@app.websocket(\"/ws/chat/{chat_id}\")"
)

# And signature
content = content.replace(
    "async def websocket_endpoint(websocket: WebSocket, token: str = None, db: Session = Depends(get_db)):",
    "async def websocket_endpoint(websocket: WebSocket, chat_id: int, token: str = None, db: Session = Depends(get_db)):"
)

# Membership check
old_check = """    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        print(f"DEBUG: Connection closed - User {username} not found in DB")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── Session State"""
new_check = """    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        print(f"DEBUG: Connection closed - User {username} not found in DB")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    member = db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == user.id).first()
    if not member:
        print(f"DEBUG: Connection closed - User {username} not in chat {chat_id}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── Session State"""
content = content.replace(old_check, new_check)

content = content.replace(
    "await manager.connect(username, websocket)",
    "await manager.connect(chat_id, username, websocket)"
)

old_save = """                    # Stylometry buffering — plaintext goes into buffer for /predict
                    clean_text = text.strip()
                    if len(clean_text) > 0:
                        msg_buffer.append(clean_text)"""
new_save = """                    # Stylometry buffering — plaintext goes into buffer for /predict
                    clean_text = text.strip()
                    if len(clean_text) > 0:
                        msg_buffer.append(clean_text)
                        
                        new_msg = models.Message(chat_id=chat_id, sender_id=user.id, text=clean_text)
                        db.add(new_msg)
                        db.commit()"""
content = content.replace(old_save, new_save)

content = content.replace(
    "await manager.broadcast({",
    "await manager.broadcast(chat_id, {"
)

content = content.replace(
    "manager.disconnect(username)",
    "manager.disconnect(chat_id, username)"
)

with open(file_path, "w") as f:
    f.write(content)
print("done")
