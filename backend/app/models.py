from sqlalchemy import Column, Integer, String, Boolean
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    totp_secret = Column(String, nullable=True)
    is_totp_enabled = Column(Boolean, default=False)

    # Step-Up Auth (Session Freeze + PIN)
    security_enabled = Column(Boolean, default=False)
    unlock_pin_hash = Column(String, nullable=True)
