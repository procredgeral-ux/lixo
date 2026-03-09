"""
Authentication utilities for JWT tokens and password hashing
"""

from datetime import datetime, timedelta, date, time
from typing import Optional, Dict, Any
import hashlib
import re
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.config import settings
from core.database import get_db
from models import User


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_PREFIX}/auth/login")


# Cache para verificação de VIP (5 minutos)
_VIP_EXPIRATION_CACHE = {}
_VIP_CACHE_TTL = timedelta(minutes=5)


def _is_vip_expired_cached(user_id: str, vip_end_date: datetime | None) -> bool:
    """Verifica se VIP expirou usando cache"""
    if not vip_end_date:
        return False

    cache_key = f"vip_{user_id}"
    cached = _VIP_EXPIRATION_CACHE.get(cache_key)

    if cached and cached['expires_at'] > datetime.utcnow():
        return cached['is_expired']

    now = datetime.utcnow()
    
    # Converter date para datetime se necessário para comparação
    if isinstance(vip_end_date, date) and not isinstance(vip_end_date, datetime):
        vip_end_date = datetime.combine(vip_end_date, time.min)
    
    is_expired = vip_end_date < now

    _VIP_EXPIRATION_CACHE[cache_key] = {
        'is_expired': is_expired,
        'expires_at': now + _VIP_CACHE_TTL
    }

    return is_expired


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password
    
    Args:
        plain_password: Plain text password
        hashed_password: Hashed password from database
    
    Returns:
        bool: True if password matches
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        # Legacy fallback: some existing DB rows were created with sha256 hex or even plaintext.
        if not hashed_password:
            return False

        sha256_hex = hashlib.sha256(plain_password.encode()).hexdigest()
        if hashed_password == sha256_hex:
            return True

        if hashed_password == plain_password:
            return True

        if re.fullmatch(r"[0-9a-fA-F]{64}", hashed_password) and hashed_password.lower() == sha256_hex:
            return True

        return False


async def maybe_upgrade_password_hash(user: User, plain_password: str, db: AsyncSession) -> None:
    """Upgrade legacy password hashes to bcrypt after a successful login."""
    if not user.hashed_password:
        return

    try:
        # If this does not raise, it's already a bcrypt (or other supported) hash.
        pwd_context.identify(user.hashed_password)
        return
    except Exception:
        pass

    user.hashed_password = get_password_hash(plain_password)
    db.add(user)
    await db.commit()


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt
    
    Args:
        password: Plain text password
    
    Returns:
        str: Hashed password
    """
    # bcrypt has a 72-byte limit, truncate if necessary
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password = password_bytes[:72].decode('utf-8', errors='ignore')
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token
    
    Args:
        data: Data to encode in token (usually {"sub": user_email})
        expires_delta: Optional custom expiration time
    
    Returns:
        str: Encoded JWT token
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any]) -> str:
    """
    Create JWT refresh token
    
    Args:
        data: Data to encode in token
    
    Returns:
        str: Encoded JWT refresh token
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    })
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and validate JWT token
    
    Args:
        token: JWT token to decode
    
    Returns:
        Optional[Dict]: Decoded token data or None if invalid
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Get current authenticated user from JWT token
    
    Args:
        token: JWT token from Authorization header
        db: Database session
    
    Returns:
        User: Authenticated user
    
    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Decode token
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
    
    # Extract email
    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception
    
    # Get user from database
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception

    # Verificar se o VIP expirou (usando cache)
    if user.role in ['vip', 'vip_plus']:
        is_expired = _is_vip_expired_cached(user.id, user.vip_end_date)

        if is_expired:
            # VIP expirou, redefinir para free
            from loguru import logger
            logger.info(f"VIP expirado para usuário {user.email}, redefinindo role para 'free'")
            user.role = 'free'
            user.vip_start_date = None
            user.vip_end_date = None
            user.updated_at = datetime.utcnow()

            # Limpar cache
            cache_key = f"vip_{user.id}"
            _VIP_EXPIRATION_CACHE.pop(cache_key, None)

            await db.commit()

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get current active user
    
    Args:
        current_user: Current authenticated user
    
    Returns:
        User: Active user
    
    Raises:
        HTTPException: If user is inactive
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get current superuser
    
    Args:
        current_user: Current authenticated user
    
    Returns:
        User: Superuser
    
    Raises:
        HTTPException: If user is not a superuser
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges"
        )
    return current_user


def verify_token_type(token: str, expected_type: str = "access") -> bool:
    """
    Verify token type
    
    Args:
        token: JWT token
        expected_type: Expected token type ("access" or "refresh")
    
    Returns:
        bool: True if token type matches
    """
    payload = decode_token(token)
    if payload is None:
        return False
    
    token_type = payload.get("type")
    return token_type == expected_type
