"""
Firebase Auth middleware — ID token doğrulama.

Kullanım:
    @router.get("/protected")
    async def endpoint(user: AuthUser = Depends(get_current_user)):
        ...
"""

from __future__ import annotations

import logging
from pathlib import Path

import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger(__name__)

# ── Firebase Admin başlatma ──────────────────────────────────────────────────
_CRED_PATH = Path(__file__).resolve().parent.parent / "firebase_credentials.json"

if not firebase_admin._apps:
    cred = credentials.Certificate(str(_CRED_PATH))
    firebase_admin.initialize_app(cred, {
        "storageBucket": "esnaf-kopilot.firebasestorage.app",
    })
    log.info("[Auth] Firebase Admin SDK başlatıldı — proje: esnaf-kopilot")

# ── Bearer token scheme ──────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=True)


class AuthUser:
    """Doğrulanmış kullanıcı bilgisi."""

    def __init__(self, uid: str, email: str):
        self.uid   = uid
        self.email = email

    def __repr__(self) -> str:
        return f"AuthUser(uid={self.uid!r}, email={self.email!r})"


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> AuthUser:
    """
    FastAPI dependency — Authorization: Bearer <firebase_id_token> doğrular.

    Raises:
        401: Token geçersiz veya süresi dolmuş
        403: Kullanıcı Firebase'de bulunamadı
    """
    token = creds.credentials
    try:
        decoded = auth.verify_id_token(token)
    except auth.ExpiredIdTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token süresi dolmuş.")
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz token.")
    except Exception as e:
        log.warning("[Auth] Token doğrulama hatası: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kimlik doğrulama başarısız.")

    uid   = decoded.get("uid", "")
    email = decoded.get("email", "")

    if not uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="UID bulunamadı.")

    return AuthUser(uid=uid, email=email)
