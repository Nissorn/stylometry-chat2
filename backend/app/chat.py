from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import auth, models, schemas
from . import ws_manager as ws_mgr
from .database import get_db

router = APIRouter()


@router.post("/", response_model=schemas.ChatResponse)
def create_chat(
    chat: schemas.ChatCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # Resolve all requested users
    users = (
        db.query(models.User)
        .filter(models.User.username.in_(chat.member_usernames))
        .all()
    )
    if len(users) != len(chat.member_usernames):
        raise HTTPException(status_code=400, detail="One or more users not found")

    # Always include the creator
    if current_user not in users:
        users.append(current_user)

    new_chat = models.Chat(name=chat.name, is_group=chat.is_group)
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)

    for u in users:
        member = models.ChatMember(chat_id=new_chat.id, user_id=u.id)
        db.add(member)
    db.commit()
    db.refresh(new_chat)

    return {
        "id": new_chat.id,
        "name": new_chat.name,
        "is_group": new_chat.is_group,
        "created_at": new_chat.created_at,
        "members": [
            {"id": m.user.id, "username": m.user.username, "security_enabled": m.user.security_enabled} for m in new_chat.members
        ],
    }


@router.get("/me", response_model=List[schemas.ChatResponse])
def get_my_chats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    chat_members = (
        db.query(models.ChatMember)
        .filter(models.ChatMember.user_id == current_user.id)
        .all()
    )
    chat_ids = [m.chat_id for m in chat_members]

    chats = (
        db.query(models.Chat)
        .filter(models.Chat.id.in_(chat_ids))
        .order_by(models.Chat.created_at.desc())
        .all()
    )

    return [
        {
            "id": c.id,
            "name": c.name,
            "is_group": c.is_group,
            "created_at": c.created_at,
            "members": [
                {"id": m.user.id, "username": m.user.username, "security_enabled": m.user.security_enabled} for m in c.members
            ],
        }
        for c in chats
    ]


@router.get("/{chat_id}/messages", response_model=List[schemas.MessageResponse])
def get_chat_messages(
    chat_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # Authorization check — must be a member of this chat
    member = (
        db.query(models.ChatMember)
        .filter(
            models.ChatMember.chat_id == chat_id,
            models.ChatMember.user_id == current_user.id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this chat")

    # Always return messages in chronological order (oldest first)
    messages = (
        db.query(models.Message)
        .filter(models.Message.chat_id == chat_id)
        .order_by(models.Message.timestamp.asc())
        .all()
    )

    return [
        {
            "id": m.id,
            "chat_id": m.chat_id,
            "sender_id": m.sender_id,
            "text": m.text,
            "timestamp": m.timestamp,
            "sender_username": m.sender.username,
        }
        for m in messages
    ]


@router.post("/{chat_id}/members")
async def add_member(
    chat_id: int,
    req: schemas.MemberActionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Add a user to a group chat.

    After the DB commit, a ``group_updated`` WebSocket payload is broadcast to
    every user currently connected to the room so their member list refreshes
    reactively — no page reload required.
    """
    # Requester must already be a member
    member = (
        db.query(models.ChatMember)
        .filter(
            models.ChatMember.chat_id == chat_id,
            models.ChatMember.user_id == current_user.id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member")

    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
    if not chat or not chat.is_group:
        raise HTTPException(status_code=400, detail="Not a group chat")

    target_user = (
        db.query(models.User).filter(models.User.username == req.username).first()
    )
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = (
        db.query(models.ChatMember)
        .filter(
            models.ChatMember.chat_id == chat_id,
            models.ChatMember.user_id == target_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already a member")

    new_member = models.ChatMember(chat_id=chat_id, user_id=target_user.id)
    db.add(new_member)
    db.commit()

    # Re-query to get the freshly committed member list
    db.refresh(chat)
    updated_members = [
        {"id": m.user.id, "username": m.user.username, "security_enabled": m.user.security_enabled} for m in chat.members
    ]

    # ── Sacred Rule guard ──────────────────────────────────────────────────
    # Broadcast group_updated to ALL currently connected sockets in this room.
    # Users not yet connected (or connected to a different chat) will pick up
    # the change the next time they call GET /chats/me.
    await ws_mgr.manager.broadcast(
        chat_id,
        {
            "type": "group_updated",
            "chat_id": chat_id,
            "members": updated_members,
        },
    )

    return {"status": "added", "members": updated_members}


@router.delete("/{chat_id}/members/{username}")
async def remove_member(
    chat_id: int,
    username: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Remove a user from a group chat.

    After the DB commit, a ``group_updated`` payload is broadcast so remaining
    members see the updated list immediately.  The removed user's client will
    receive the event too (they're still connected when the broadcast fires)
    with a ``kicked_user`` field so the frontend can close their session.
    """
    member = (
        db.query(models.ChatMember)
        .filter(
            models.ChatMember.chat_id == chat_id,
            models.ChatMember.user_id == current_user.id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member")

    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
    if not chat or not chat.is_group:
        raise HTTPException(status_code=400, detail="Not a group chat")

    target_user = db.query(models.User).filter(models.User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    target_member = (
        db.query(models.ChatMember)
        .filter(
            models.ChatMember.chat_id == chat_id,
            models.ChatMember.user_id == target_user.id,
        )
        .first()
    )
    if target_member:
        db.delete(target_member)
        db.commit()

    # Build updated member list AFTER deletion
    db.refresh(chat)
    updated_members = [
        {"id": m.user.id, "username": m.user.username, "security_enabled": m.user.security_enabled} for m in chat.members
    ]

    # Broadcast to everyone still in the room (including the just-removed user
    # who may still have an open socket).  The frontend uses `kicked_user` to
    # detect whether to close its own session.
    await ws_mgr.manager.broadcast(
        chat_id,
        {
            "type": "group_updated",
            "chat_id": chat_id,
            "members": updated_members,
            "kicked_user": username,
        },
    )

    return {"status": "removed", "members": updated_members}


@router.delete("/{chat_id}")
def delete_chat(
    chat_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    member = (
        db.query(models.ChatMember)
        .filter(
            models.ChatMember.chat_id == chat_id,
            models.ChatMember.user_id == current_user.id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this chat")

    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Explicit cascade delete (safer than relying on DB-level cascade with SQLite)
    db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id).delete()
    db.query(models.Message).filter(models.Message.chat_id == chat_id).delete()
    db.delete(chat)
    db.commit()

    return {"status": "deleted"}
