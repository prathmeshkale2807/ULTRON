import json
import keyring
from google.oauth2.credentials import Credentials
from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger("google_workspace")

SERVICE_NAME = "ultron_google_oauth"

def _get_keyring_key(principal_id: str) -> str:
    return f"{principal_id}_refresh_token"

def save_credentials(principal_id: str, refresh_token: str, scopes: list[str]) -> None:
    """Stores the OAuth refresh token in the OS credential manager."""
    data = {
        "refresh_token": refresh_token,
        "scopes": scopes
    }
    keyring.set_password(SERVICE_NAME, _get_keyring_key(principal_id), json.dumps(data))

def get_credentials(principal_id: str, required_scopes: list[str]) -> Credentials | None:
    """Retrieves credentials and builds a Google Credentials object."""
    stored = keyring.get_password(SERVICE_NAME, _get_keyring_key(principal_id))
    if not stored:
        return None
        
    try:
        data = json.loads(stored)
    except json.JSONDecodeError:
        return None
        
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return None
        
    stored_scopes = set(data.get("scopes", []))
    for rs in required_scopes:
        if rs not in stored_scopes:
            return None
            
    settings = get_settings()
    
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=data.get("scopes")
    )

def revoke_credentials(principal_id: str) -> None:
    """Removes the stored credentials."""
    try:
        keyring.delete_password(SERVICE_NAME, _get_keyring_key(principal_id))
    except keyring.errors.PasswordDeleteError:
        pass


def get_oauth_flow(scopes: list[str], state: str | None = None):
    """Creates a Google OAuth Flow object using secure backend credentials."""
    from google_auth_oauthlib.flow import Flow
    settings = get_settings()
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "project_id": "ultron",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": settings.google_client_secret,
        }
    }
    flow = Flow.from_client_config(client_config, scopes=scopes, state=state)
    flow.redirect_uri = "http://localhost:8000/api/google/callback"
    return flow
