"""
auth.py — Authentication and Authorization for The Curator Mail.

Handles:
  - Password hashing (PBKDF2-SHA256)
  - JWT creation and validation
  - User extraction dependency for FastAPI
"""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

try:
    from passlib.context import CryptContext
except Exception:
    CryptContext = None

# ─── Configuration ────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("SECRET_KEY", "editorial-excellence-curator-mail-secret-2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
PBKDF2_ITERATIONS = 260_000

legacy_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") if CryptContext else None
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


# ─── Password Hashing ─────────────────────────────────────────────────────────

def _pbkdf2_hash(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if hashed_password.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_b64, digest_b64 = hashed_password.split("$", 3)
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected = base64.b64decode(digest_b64.encode("ascii"))
            actual = _pbkdf2_hash(plain_password, salt, int(iterations))
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False

    # Backward compatibility for accounts created before the PBKDF2 switch.
    if legacy_pwd_context:
        try:
            return legacy_pwd_context.verify(plain_password, hashed_password)
        except Exception:
            return False
    return False


def get_password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _pbkdf2_hash(password, salt)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_b64}${digest_b64}"


# ─── Token Generation ─────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# ─── Dependency ───────────────────────────────────────────────────────────────

def decode_user_id_from_token(token: str) -> str:
    """Extract user_id from a JWT token. Raises 401 if invalid."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return user_id
    except JWTError:
        raise credentials_exception


async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> str:
    """Extracts user_id from JWT. Raises 401 if invalid."""
    return decode_user_id_from_token(token)
