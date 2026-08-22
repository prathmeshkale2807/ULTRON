from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.conversation.schemas import ConversationSchema, MessageCreate, MessageSchema
from app.security.local_auth import require_local_auth
from app.ai_providers.factory import get_provider_manager
from app.conversation.manager import ConversationManager

def _require_valid_session(session_id: str, db: Session) -> None:
    from app.core.database import SessionRecord
    row = db.get(SessionRecord, session_id)
    if not row or row.invalidated:
        raise HTTPException(status_code=403, detail="Invalid or expired session")


router = APIRouter(prefix="/conversations", tags=["conversations"])

@router.post("/{conversation_id}/messages", response_model=MessageSchema)
async def post_message(
    conversation_id: str,
    message: MessageCreate,
    session_id: str,
    db: Session = Depends(get_db),
    principal = Depends(require_local_auth)
):
    _require_valid_session(session_id, db)
    provider_manager = get_provider_manager()
    manager = ConversationManager(db, provider_manager)
    # Ensure conversation exists and ownership is valid
    conv = manager.get_or_create(conversation_id, session_id)
    if conv.session_id and conv.session_id != session_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this conversation.")

        
    response_text = await manager.process_turn(conversation_id, message.content, session_id, principal.identity)
    
    from app.core.database import MessageRecord
    last_msg = db.query(MessageRecord).filter_by(conversation_id=conversation_id).order_by(MessageRecord.id.desc()).first()
    
    return last_msg

@router.get("/{conversation_id}", response_model=ConversationSchema)
def get_conversation(
    conversation_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    principal = Depends(require_local_auth)
):
    _require_valid_session(session_id, db)
    from app.core.database import ConversationRecord
    conv = db.get(ConversationRecord, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.session_id and conv.session_id != session_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return conv

