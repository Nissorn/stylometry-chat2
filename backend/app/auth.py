import base64
import os
from datetime import datetime, timedelta
from io import BytesIO

import httpx
import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import database, models, schemas
from .crypto import encrypt
from .ws_manager import manager

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# JWT Secret
# ---------------------------------------------------------------------------
SECRET_KEY: str = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY") or ""
if not SECRET_KEY:
    raise RuntimeError(
        "FATAL: Neither JWT_SECRET_KEY nor SECRET_KEY environment variable is set. "
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10080
ML_TRAIN_URL = "http://stylometry-ml-service:8001/train"


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
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
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


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
        "security_enabled": False,
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

@router.get("/me", response_model=schemas.UserMeResponse)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user


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


# ---------------------------------------------------------------------------
# Step-Up Security — PIN registration & Verification
# ---------------------------------------------------------------------------


@router.post("/security/enable")
def enable_security(
    req: schemas.EnableSecurityRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    current_user.unlock_pin_hash = pwd_context.hash(req.pin)
    current_user.security_enabled = True
    db.commit()
    return {"detail": "Security mode enabled."}


@router.post("/verify-pin")
def verify_pin(
    req: schemas.VerifyPinRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    if not current_user.unlock_pin_hash or not verify_password(
        req.pin, current_user.unlock_pin_hash
    ):
        raise HTTPException(status_code=400, detail="Incorrect PIN")

    pending = manager.get_pending_messages(current_user.username)
    return {
        "detail": "PIN verified. Please review suspicious messages.",
        "requires_review": len(pending) > 0,
    }


@router.get("/suspicious-messages", response_model=schemas.SuspiciousMessagesResponse)
def get_suspicious_messages(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    messages = manager.get_pending_messages(current_user.username)

    # Fallback: if in-memory context is missing, use latest user messages.
    if not messages:
        rows = (
            db.query(models.Message)
            .filter(models.Message.sender_id == current_user.id)
            .order_by(models.Message.id.desc())
            .limit(5)
            .all()
        )
        messages = [m.text for m in reversed(rows)]

    return {
        "messages": messages,
        "requires_review": len(messages) > 0,
    }


@router.post("/review-messages")
async def review_messages(
    req: schemas.ReviewMessagesRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    username = current_user.username
    messages = manager.get_pending_messages(username)

    review_count = len(messages)
    appended_count = 0
    train_triggered = False

    if req.approved and messages:
        data_dir = "/ml_workspace/data"
        os.makedirs(data_dir, exist_ok=True)
        baseline_path = os.path.join(data_dir, f"{username}_baseline.txt")

        with open(baseline_path, "a", encoding="utf-8") as f:
            for msg in messages:
                clean_msg = str(msg).strip()
                if not clean_msg:
                    continue
                f.write(encrypt(clean_msg) + "\n")
                appended_count += 1

        if appended_count > 0:
            line_count = 0
            with open(baseline_path, "r", encoding="utf-8") as f:
                line_count = sum(1 for ln in f if ln.strip())

            if line_count >= 50 and (line_count == 50 or line_count % 10 == 0):
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(f"{ML_TRAIN_URL}/{username}", timeout=30.0)
                    train_triggered = True
                except Exception as exc:
                    print(f"[AUTH] Retrain trigger failed for {username}: {exc}")

    manager.clear_pending_messages(username)
    current_user.is_frozen = False
    db.commit()
    manager.unlock(username)
    manager.reset_user_trust_score(username)

    return {
        "detail": "Review submitted and session restored.",
        "approved": req.approved,
        "reviewed_count": review_count,
        "appended_count": appended_count,
        "train_triggered": train_triggered,
    }
