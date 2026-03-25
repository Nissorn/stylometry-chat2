from sqlalchemy import Boolean, Column, Integer, String

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    totp_secret = Column(String, nullable=True)
    is_totp_enabled = Column(Boolean, default=False)
    security_enabled = Column(Boolean, default=False)
    unlock_pin_hash = Column(String, nullable=True)
