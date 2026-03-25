from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime

class UserCreate(BaseModel):
    username: str = Field(..., pattern=r"^[a-zA-Z0-9_]{3,20}$")
    password: str = Field(..., min_length=6)
    
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str
    is_totp_enabled: bool = False

class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = None

class TOTPVerifyRequest(BaseModel):
    totp_code: str = Field(..., pattern=r"^\d{6}$")

class UserResponse(BaseModel):
    id: int
    username: str

    model_config = ConfigDict(from_attributes=True)

class ChatCreate(BaseModel):
    name: Optional[str] = None
    is_group: bool = False
    member_usernames: List[str]

class ChatResponse(BaseModel):
    id: int
    name: Optional[str] = None
    is_group: bool
    created_at: datetime
    members: List[UserResponse]

    model_config = ConfigDict(from_attributes=True)

class MessageResponse(BaseModel):
    id: int
    chat_id: int
    sender_id: int
    text: str
    timestamp: datetime
    sender_username: str

    model_config = ConfigDict(from_attributes=True)

class MemberActionRequest(BaseModel):
    username: str
