from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
import json
import secrets

from app.security.local_auth import require_local_auth
from app.integrations.google_workspace import get_oauth_flow, save_credentials, revoke_credentials, get_credentials
from app.core.config import get_settings

router = APIRouter(prefix="/google", tags=["google"])

REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

@router.get("/auth")
def authorize_google(principal = Depends(require_local_auth)):
    settings = get_settings()
    if not settings.google_client_id or settings.google_client_id == "mock_client_id":
        raise HTTPException(status_code=400, detail="Google OAuth is not configured securely on this server.")
    state_data = {"principal": principal.identity, "nonce": secrets.token_urlsafe(16)}
    state = json.dumps(state_data)
    flow = get_oauth_flow(REQUIRED_SCOPES, state=state)
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return RedirectResponse(auth_url)

@router.get("/callback")
def google_callback(request: Request, state: str, code: str):
    try:
        state_data = json.loads(state)
        principal_id = state_data["principal"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    flow = get_oauth_flow(REQUIRED_SCOPES, state=state)
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch token: {e}")
    credentials = flow.credentials
    if credentials.refresh_token:
        save_credentials(principal_id, credentials.refresh_token, REQUIRED_SCOPES)
    return {"message": "Google Workspace connected successfully."}

@router.delete("/disconnect")
def disconnect_google(principal = Depends(require_local_auth)):
    revoke_credentials(principal.identity)
    return {"message": "Google Workspace disconnected."}

@router.get("/status")
def google_status(principal = Depends(require_local_auth)):
    creds = get_credentials(principal.identity, REQUIRED_SCOPES)
    return {"connected": creds is not None}
