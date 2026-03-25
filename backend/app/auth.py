import base64
import os
from datetime import datetime, timedelta
from io import BytesIO

import pyotp
import qrcode
from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import database, models, schemas

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _decode_bearer(authorization: str | None) -> str:
    """Extract and validate a Bearer JWT from the Authorization header.

    Returns the ``sub`` (username) claim on success.
    Raises HTTPException 401 on any failure.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Authorization header missing or malformed"
        )

    raw_token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(raw_token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Token missing subject claim")
        return username
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@router.post("/register", response_model=schemas.Token)
def register(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    db_user = (
        db.query(models.User).filter(models.User.username == user.username).first()
    )
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = get_password_hash(user.password)
    new_user = models.User(username=user.username, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    access_token = create_access_token(data={"sub": new_user.username})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "is_totp_enabled": False,
    }


@router.post("/login", response_model=schemas.Token)
def login(req: schemas.LoginRequest, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.username == req.username).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    if user.is_totp_enabled:
        if not req.totp_code:
            raise HTTPException(status_code=401, detail="TOTP code required")
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(req.totp_code):
            raise HTTPException(status_code=401, detail="Invalid TOTP code")

    access_token = create_access_token(data={"sub": user.username})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "is_totp_enabled": user.is_totp_enabled,
        "security_enabled": user.security_enabled,
    }


@router.post("/totp/generate")
def generate_totp(username: str, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_totp_enabled:
        raise HTTPException(status_code=400, detail="TOTP is already enabled")

    totp_secret = pyotp.random_base32()
    user.totp_secret = totp_secret
    db.commit()

    totp_uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
        name=user.username, issuer_name="Thai-Stylometry"
    )

    qr = qrcode.make(totp_uri)
    buf = BytesIO()
    qr.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return {"secret": totp_secret, "qr_code": qr_b64}


@router.post("/totp/verify")
def verify_totp(
    username: str,
    req: schemas.TOTPVerifyRequest,
    db: Session = Depends(database.get_db),
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not user.totp_secret:
        raise HTTPException(status_code=400, detail="Invalid request")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(req.totp_code):
        raise HTTPException(status_code=400, detail="Invalid 2FA Code")

    user.is_totp_enabled = True
    db.commit()

    access_token = create_access_token(data={"sub": user.username})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "is_totp_enabled": True,
    }


# ---------------------------------------------------------------------------
# Step-Up Security — PIN registration
# ---------------------------------------------------------------------------


@router.post("/security/enable")
def enable_security(
    req: schemas.EnableSecurityRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(database.get_db),
):
    """JWT-protected endpoint.

    Hashes the supplied 6-digit PIN with bcrypt, stores it on the user row,
    and sets ``security_enabled = True`` so the WebSocket engine knows to
    trigger a step-up challenge instead of a hard kick when trust drops below
    the lockout threshold.
    """
    username = _decode_bearer(authorization)

    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.unlock_pin_hash = pwd_context.hash(req.pin)
    user.security_enabled = True
    db.commit()

    print(f"[SECURITY] Step-up PIN registered for user: {username}")
    return {"detail": "Security mode enabled. Step-up authentication is now active."}
