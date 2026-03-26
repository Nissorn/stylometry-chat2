import base64
import os
from datetime import datetime, timedelta
from io import BytesIO

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import database, models, schemas

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# JWT Secret — fail fast so the app never silently runs with a weak default.
# Supports the canonical JWT_SECRET_KEY name and the legacy SECRET_KEY alias
# so existing .env files keep working without modification.
# ---------------------------------------------------------------------------
SECRET_KEY: str = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY") or ""
if not SECRET_KEY:
    raise RuntimeError(
        "FATAL: Neither JWT_SECRET_KEY nor SECRET_KEY environment variable is set. "
        "The application cannot start without a JWT signing secret. "
        "Set JWT_SECRET_KEY to a long, random string (e.g. `openssl rand -hex 32`)."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10080


def get_password_hash(password):
    return pwd_context.hash(password)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            print("AUTH FAILED: No sub in payload")
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError as e:
        print(f"AUTH FAILED: JWTError {e}")
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        print(f"AUTH FAILED: User {username} not found in DB")
        raise HTTPException(status_code=401, detail="User not found")
    return user


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
        "security_enabled": True,
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
        "security_enabled": user.security_enabled,
    }


@router.get("/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user
