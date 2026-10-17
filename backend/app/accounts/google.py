"""Google sign-in: check the ID token the "Sign in with Google" button gives the browser.

The browser never sends us a Google password. Google's button returns an ID token (a JWT) signed by
Google. We check the signature against Google's published public keys, that it was issued for OUR
client id (`aud`) by Google (`iss`), that it hasn't expired, and that Google verified the email.
Only then do we trust the email and the account id (`sub`) inside it.
"""

import asyncio
from dataclasses import dataclass

import jwt

from app.config import get_settings

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

_jwks = jwt.PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600)  # keys are fetched once an hour


class GoogleTokenError(Exception):
    pass


@dataclass(frozen=True)
class GoogleAccount:
    sub: str
    email: str
    name: str


def _verify(credential: str, client_id: str) -> GoogleAccount:
    try:
        key = _jwks.get_signing_key_from_jwt(credential)
        claims = jwt.decode(
            credential,
            key.key,
            algorithms=["RS256"],
            audience=client_id,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise GoogleTokenError(f"Google sign-in could not be verified ({type(exc).__name__}).") from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleTokenError("This token was not issued by Google.")
    if not claims.get("email") or claims.get("email_verified") is not True:
        raise GoogleTokenError("Google has not verified this account's email address.")
    email = str(claims["email"]).strip().lower()
    return GoogleAccount(sub=str(claims["sub"]), email=email, name=str(claims.get("name") or email.split("@")[0]))


async def verify_credential(credential: str) -> GoogleAccount:
    client_id = get_settings().google_client_id
    if not client_id:
        raise GoogleTokenError("Google sign-in is not set up on this server (GOOGLE_CLIENT_ID is empty).")
    # PyJWKClient fetches Google's keys with blocking I/O; keep it off the event loop.
    return await asyncio.to_thread(_verify, credential, client_id)
