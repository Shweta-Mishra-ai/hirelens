"""
HireLens — Auth API
Fixed:
- Supabase auth calls are SYNC — no await
- Email confirmation handling (Supabase may require email verify)
- Better error messages
- Full name validation
"""

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, field_validator

from app.core.dependencies import get_db, get_current_user
from app.core.security import create_access_token
from app.core.exceptions import AuthError, HireLensException

logger = logging.getLogger("hirelens")
router = APIRouter()


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    company: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Full name is required.")
        if len(v) < 2:
            raise ValueError("Full name must be at least 2 characters.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v:
            raise ValueError("Password is required.")
        return v


@router.post("/signup")
async def signup(body: SignupRequest, db=Depends(get_db)):
    """
    Create a new recruiter account.
    Note: Supabase may send a confirmation email depending on your project settings.
    For development, disable email confirmation in Supabase Auth settings.
    """
    if not db:
        raise HireLensException(
            "Database not configured. Please set SUPABASE_URL and SUPABASE_SERVICE_KEY."
        )

    try:
        # SYNC call — no await
        result = db.auth.sign_up({
            "email": str(body.email),
            "password": body.password,
            "options": {
                "data": {
                    "full_name": body.full_name,
                    "company": body.company or "",
                }
            },
        })

        user = result.user
        if not user:
            # This happens when email confirmation is required
            return {
                "access_token": None,
                "token_type": "bearer",
                "requires_email_confirmation": True,
                "message": "Account created. Check your email to confirm your account, then log in.",
                "user": {"email": str(body.email), "full_name": body.full_name},
            }

        token = create_access_token({
            "sub": str(user.id),
            "email": str(user.email),
        })

        return {
            "access_token": token,
            "token_type": "bearer",
            "requires_email_confirmation": False,
            "user": {
                "id": str(user.id),
                "email": str(user.email),
                "full_name": body.full_name,
                "company": body.company or "",
            },
        }

    except AuthError:
        raise
    except Exception as e:
        err_str = str(e).lower()
        if "already registered" in err_str or "already exists" in err_str or "duplicate" in err_str:
            raise AuthError("An account with this email already exists. Please log in instead.")
        logger.error(f"Signup error for {body.email}: {e}")
        raise AuthError(f"Signup failed. Please try again.")


@router.post("/login")
async def login(body: LoginRequest, db=Depends(get_db)):
    """
    Login with email and password.
    Returns JWT access token valid for 7 days.
    """
    if not db:
        raise HireLensException("Database not configured.")

    try:
        # SYNC call — no await
        result = db.auth.sign_in_with_password({
            "email": str(body.email),
            "password": body.password,
        })

        user = result.user
        if not user:
            raise AuthError("Invalid email or password.")

        token = create_access_token({
            "sub": str(user.id),
            "email": str(user.email),
        })

        meta = user.user_metadata or {}
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "email": str(user.email),
                "full_name": meta.get("full_name", ""),
                "company": meta.get("company", ""),
            },
        }

    except AuthError:
        raise
    except Exception as e:
        err_str = str(e).lower()
        if "invalid" in err_str or "wrong" in err_str or "credentials" in err_str:
            raise AuthError("Invalid email or password.")
        if "email not confirmed" in err_str:
            raise AuthError("Please confirm your email address before logging in.")
        logger.error(f"Login error for {body.email}: {e}")
        raise AuthError("Login failed. Please try again.")


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user's profile."""
    return current_user
