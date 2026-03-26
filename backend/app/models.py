from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    totp_secret = Column(String, nullable=True)
    is_totp_enabled = Column(Boolean, default=False)
    security_enabled = Column(Boolean, default=True)
    unlock_pin_hash = Column(String, nullable=True)
    is_frozen = Column(Boolean, default=False)
    
    chats = relationship("ChatMember", back_populates="user")
    messages = relationship("Message", back_populates="sender")

class Chat(Base):
    __tablename__ = "chats"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    is_group = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    members = relationship("ChatMember", back_populates="chat")
    messages = relationship("Message", back_populates="chat")

class ChatMember(Base):
    __tablename__ = "chat_members"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    
    chat = relationship("Chat", back_populates="members")
    user = relationship("User", back_populates="chats")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    text = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    chat = relationship("Chat", back_populates="messages")
    sender = relationship("User", back_populates="messages")
