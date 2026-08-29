"""Firebase ID token verification for the broker's three routes.

Every route requires `Authorization: Bearer <firebase-id-token>`; the
verified token's `uid` becomes `user_id` everywhere downstream (replacing
the hardcoded "gradio-user" at gradio-ui/app.py:218 -- plan Proposed
Changes for broker/main.py).
"""
import logging
from typing import NamedTuple

import firebase_admin
from firebase_admin import auth as firebase_auth

logger = logging.getLogger("broker.auth")

_app = None


def _get_app():
    global _app
    if _app is None:
        # Uses Application Default Credentials -- the same service account
        # Cloud Run injects, no separate service account key needed.
        _app = firebase_admin.initialize_app()
    return _app


class AuthError(Exception):
    """Raised for any authentication failure; the caller maps this to 401."""


class AuthenticatedUser(NamedTuple):
    uid: str
    # True iff this token was issued to a Firebase Anonymous Auth session
    # (Firebase's own `firebase.sign_in_provider` claim == "anonymous", as
    # opposed to e.g. "google.com"). campaign_limits uses this to apply the
    # tighter per-uid lifetime trigger cap requested for Anonymous Auth --
    # see main.py's handle_create_campaign/handle_resume_campaign.
    is_anonymous: bool


def verify_id_token(authorization_header: str) -> AuthenticatedUser:
    """Verify the bearer token and return the caller's identity.

    Raises AuthError on a missing header, malformed token, or any
    verification failure (expired, revoked, wrong audience/project, etc.).
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise AuthError("missing or malformed Authorization header")

    token = authorization_header.removeprefix("Bearer ").strip()
    if not token:
        raise AuthError("empty bearer token")

    try:
        _get_app()
        decoded = firebase_auth.verify_id_token(token)
    except Exception as e:
        logger.warning("Firebase ID token verification failed: %s", e)
        raise AuthError(str(e)) from e

    uid = decoded.get("uid")
    if not uid:
        raise AuthError("decoded token has no uid")

    sign_in_provider = (decoded.get("firebase") or {}).get("sign_in_provider")
    return AuthenticatedUser(uid=uid, is_anonymous=sign_in_provider == "anonymous")
