from __future__ import annotations

import base64
import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..auth import create_access_token, get_current_user
from ..database import get_db
from ..ws_manager import manager

router = APIRouter()

RP_ID = os.getenv("WEBAUTHN_RP_ID", "stylometry.nissorn.codes")
RP_NAME = os.getenv("WEBAUTHN_RP_NAME", "Stylometry Chat")
EXPECTED_ORIGIN = os.getenv("WEBAUTHN_ORIGIN", "https://stylometry.nissorn.codes")
CHALLENGE_TTL_SECONDS = 300

_challenge_lock = threading.Lock()
_challenge_store: dict[tuple[int, str], tuple[str, datetime]] = {}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _new_challenge() -> str:
    return _b64url_encode(secrets.token_bytes(32))


def _normalize_challenge_bytes(challenge: str | bytes) -> bytes:
    if isinstance(challenge, bytes):
        return challenge
    return _b64url_decode(challenge)


def _set_challenge(user_id: int, purpose: str, challenge: str) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    with _challenge_lock:
        _challenge_store[(int(user_id), purpose)] = (challenge, expires_at)


def _pop_challenge(user_id: int, purpose: str) -> str:
    key = (int(user_id), purpose)
    with _challenge_lock:
        item = _challenge_store.pop(key, None)
    if not item:
        raise HTTPException(status_code=400, detail="Challenge missing or expired")
    challenge, expires_at = item
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="Challenge expired")
    return challenge


def _extract_credential_id(credential: Dict[str, Any]) -> str:
    credential_id = credential.get("id")
    if not credential_id:
        raise HTTPException(status_code=400, detail="Credential id is required")
    return str(credential_id)


def _require_webauthn():
    try:
        from webauthn import verify_authentication_response, verify_registration_response
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"WebAuthn dependency missing: {exc}",
        )
    return verify_registration_response, verify_authentication_response


def _raise_as_client_error(exc: Exception, fallback: str) -> None:
    try:
        from webauthn.helpers.exceptions import (
            InvalidAuthenticationResponse,
            InvalidRegistrationResponse,
        )

        if isinstance(exc, (InvalidRegistrationResponse, InvalidAuthenticationResponse)):
            raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception:
        pass

    if isinstance(exc, HTTPException):
        raise exc
    raise HTTPException(status_code=400, detail=fallback)


def _verify_registration(credential: Dict[str, Any], expected_challenge: str):
    verify_registration_response, _ = _require_webauthn()

    parsed_credential: Any = credential
    try:
        from webauthn.helpers import parse_registration_credential_json

        parsed_credential = parse_registration_credential_json(json.dumps(credential))
    except Exception:
        parsed_credential = credential

    return verify_registration_response(
        credential=parsed_credential,
        expected_challenge=_normalize_challenge_bytes(expected_challenge),
        expected_origin=EXPECTED_ORIGIN,
        expected_rp_id=RP_ID,
        require_user_verification=True,
    )


def _verify_authentication(
    credential: Dict[str, Any],
    expected_challenge: str,
    stored_public_key: str,
    stored_sign_count: int,
):
    _, verify_authentication_response = _require_webauthn()

    parsed_credential: Any = credential
    try:
        from webauthn.helpers import parse_authentication_credential_json

        parsed_credential = parse_authentication_credential_json(json.dumps(credential))
    except Exception:
        parsed_credential = credential

    return verify_authentication_response(
        credential=parsed_credential,
        expected_challenge=_normalize_challenge_bytes(expected_challenge),
        expected_origin=EXPECTED_ORIGIN,
        expected_rp_id=RP_ID,
        credential_public_key=_b64url_decode(stored_public_key),
        credential_current_sign_count=stored_sign_count,
        require_user_verification=True,
    )


def _build_security_enabled(db: Session, user_id: int) -> bool:
    return (
        db.query(models.Passkey)
        .filter(models.Passkey.user_id == user_id)
        .first()
        is not None
    )


class LoginOptionsRequest(BaseModel):
    username: str = Field(..., min_length=3)


class CredentialVerifyRequest(BaseModel):
    credential: Dict[str, Any]
    device_name: Optional[str] = None


class LoginVerifyRequest(CredentialVerifyRequest):
    username: str = Field(..., min_length=3)


@router.post("/register/options")
def register_options(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    challenge = _new_challenge()
    _set_challenge(current_user.id, "register", challenge)

    exclude_credentials = [
        {"id": p.credential_id, "type": "public-key"}
        for p in db.query(models.Passkey).filter(models.Passkey.user_id == current_user.id).all()
    ]

    return {
        "challenge": challenge,
        "rp": {"name": RP_NAME, "id": RP_ID},
        "user": {
            "id": _b64url_encode(str(current_user.id).encode("utf-8")),
            "name": current_user.username,
            "displayName": current_user.username,
        },
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},
            {"type": "public-key", "alg": -257},
        ],
        "timeout": 60000,
        "attestation": "none",
        "authenticatorSelection": {
            "residentKey": "preferred",
            "userVerification": "preferred",
        },
        "excludeCredentials": exclude_credentials,
    }


@router.post("/register/verify")
def register_verify(
    req: CredentialVerifyRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expected_challenge = _pop_challenge(current_user.id, "register")
    try:
        verification = _verify_registration(req.credential, expected_challenge)
    except Exception as exc:
        _raise_as_client_error(exc, f"Passkey registration failed: {exc}")

    credential_id = _extract_credential_id(req.credential)
    if db.query(models.Passkey).filter(models.Passkey.credential_id == credential_id).first():
        raise HTTPException(status_code=400, detail="Passkey already registered")

    public_key_bytes = getattr(verification, "credential_public_key", None)
    if not isinstance(public_key_bytes, (bytes, bytearray)):
        raise HTTPException(status_code=400, detail="Invalid passkey registration response")

    sign_count = int(getattr(verification, "sign_count", 0) or 0)

    passkey = models.Passkey(
        user_id=current_user.id,
        user_handle=str(current_user.id),
        credential_id=credential_id,
        public_key=_b64url_encode(bytes(public_key_bytes)),
        sign_count=sign_count,
        device_name=req.device_name,
    )
    db.add(passkey)
    current_user.security_enabled = True
    db.commit()

    return {"detail": "Passkey registered successfully."}


@router.post("/login/options")
def login_options(req: LoginOptionsRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == req.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    passkeys = db.query(models.Passkey).filter(models.Passkey.user_id == user.id).all()
    if not passkeys:
        raise HTTPException(status_code=400, detail="No passkeys registered for this account")

    challenge = _new_challenge()
    _set_challenge(user.id, "login", challenge)

    return {
        "challenge": challenge,
        "rpId": RP_ID,
        "timeout": 60000,
        "userVerification": "preferred",
        "allowCredentials": [
            {"id": p.credential_id, "type": "public-key"}
            for p in passkeys
        ],
    }


@router.post("/login/verify")
def login_verify(req: LoginVerifyRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == req.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    expected_challenge = _pop_challenge(user.id, "login")
    credential_id = _extract_credential_id(req.credential)
    passkey = (
        db.query(models.Passkey)
        .filter(models.Passkey.user_id == user.id, models.Passkey.credential_id == credential_id)
        .first()
    )
    if not passkey:
        raise HTTPException(status_code=400, detail="Unknown passkey")

    verification = _verify_authentication(
        credential=req.credential,
        expected_challenge=expected_challenge,
        stored_public_key=passkey.public_key,
        stored_sign_count=passkey.sign_count,
    )

    new_sign_count = int(getattr(verification, "new_sign_count", passkey.sign_count) or 0)
    if new_sign_count < passkey.sign_count:
        raise HTTPException(status_code=400, detail="Passkey sign counter replay detected")

    passkey.sign_count = new_sign_count
    user.security_enabled = _build_security_enabled(db, user.id)
    db.commit()

    access_token = create_access_token(data={"sub": user.username})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "is_totp_enabled": user.is_totp_enabled,
        "security_enabled": user.security_enabled,
    }


@router.post("/stepup/options")
def stepup_options(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    passkeys = db.query(models.Passkey).filter(models.Passkey.user_id == current_user.id).all()
    if not passkeys:
        raise HTTPException(status_code=400, detail="No passkeys registered for this account")

    challenge = _new_challenge()
    _set_challenge(current_user.id, "stepup", challenge)

    return {
        "challenge": challenge,
        "rpId": RP_ID,
        "timeout": 60000,
        "userVerification": "preferred",
        "allowCredentials": [
            {"id": p.credential_id, "type": "public-key"}
            for p in passkeys
        ],
    }


@router.post("/stepup/verify")
def stepup_verify(
    req: CredentialVerifyRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expected_challenge = _pop_challenge(current_user.id, "stepup")
    credential_id = _extract_credential_id(req.credential)
    passkey = (
        db.query(models.Passkey)
        .filter(models.Passkey.user_id == current_user.id, models.Passkey.credential_id == credential_id)
        .first()
    )
    if not passkey:
        raise HTTPException(status_code=400, detail="Unknown passkey")

    verification = _verify_authentication(
        credential=req.credential,
        expected_challenge=expected_challenge,
        stored_public_key=passkey.public_key,
        stored_sign_count=passkey.sign_count,
    )

    new_sign_count = int(getattr(verification, "new_sign_count", passkey.sign_count) or 0)
    if new_sign_count < passkey.sign_count:
        raise HTTPException(status_code=400, detail="Passkey sign counter replay detected")

    passkey.sign_count = new_sign_count
    db.commit()

    pending = manager.get_pending_messages(current_user.username)
    return {
        "detail": "Passkey verified. Please review suspicious messages.",
        "requires_review": len(pending) > 0,
    }
