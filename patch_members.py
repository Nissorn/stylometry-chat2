import os

file_path = "backend/app/schemas.py"
with open(file_path, "r") as f:
    text = f.read()

text += """
class MemberActionRequest(BaseModel):
    username: str
"""

with open(file_path, "w") as f:
    f.write(text)

chat_path = "backend/app/chat.py"
with open(chat_path, "r") as f:
    chat_text = f.read()

chat_text += """
@router.post("/{chat_id}/members")
def add_member(chat_id: int, req: schemas.MemberActionRequest, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    member = db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == current_user.id).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member")
        
    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
    if not chat or not chat.is_group:
        raise HTTPException(status_code=400, detail="Not a group chat")
        
    target_user = db.query(models.User).filter(models.User.username == req.username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    existing = db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == target_user.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already a member")
        
    new_member = models.ChatMember(chat_id=chat_id, user_id=target_user.id)
    db.add(new_member)
    db.commit()
    return {"status": "added"}

@router.delete("/{chat_id}/members/{username}")
def remove_member(chat_id: int, username: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    member = db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == current_user.id).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member")
        
    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
    if not chat or not chat.is_group:
        raise HTTPException(status_code=400, detail="Not a group chat")
        
    target_user = db.query(models.User).filter(models.User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    target_member = db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == target_user.id).first()
    if target_member:
        db.delete(target_member)
        db.commit()
    return {"status": "removed"}
"""

with open(chat_path, "w") as f:
    f.write(chat_text)

print("backend member management patched")
