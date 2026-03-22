from pydantic import BaseModel, ConfigDict, Field

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
