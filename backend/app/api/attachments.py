from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.security.local_auth import require_local_auth
from app.conversation.attachments import get_attachment

router = APIRouter(prefix="/attachments", tags=["attachments"])

@router.get("/{attachment_id}")
def download_attachment(
    attachment_id: str,
    db: Session = Depends(get_db),
    principal = Depends(require_local_auth)
):
    try:
        record, data = get_attachment(db, attachment_id, principal.identity)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
        
    return Response(content=data, media_type=record.mime_type)
