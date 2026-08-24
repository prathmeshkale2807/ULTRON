import os
import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AttachmentRecord

logger = logging.getLogger(__name__)

def get_attachments_dir() -> str:
    settings = get_settings()
    # Normally settings.database_url is sqlite:///... 
    # Let's put attachments in the same folder as the DB or logs.
    # In Windows, %LOCALAPPDATA%/ULTRON/data/attachments/
    
    app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    base_dir = os.path.join(app_data, "ULTRON", "data", "attachments")
    os.makedirs(base_dir, exist_ok=True)
    return base_dir

def save_attachment(
    db: Session,
    principal_id: str,
    conversation_id: str,
    mime_type: str,
    data: bytes,
    message_id: int | None = None
) -> AttachmentRecord:
    """
    Saves an attachment to disk and records it in the database.
    """
    attach_id = str(uuid.uuid4())
    file_path = os.path.join(get_attachments_dir(), attach_id)
    
    # Write to disk
    with open(file_path, "wb") as f:
        f.write(data)
        
    record = AttachmentRecord(
        attachment_id=attach_id,
        principal_id=principal_id,
        conversation_id=conversation_id,
        message_id=message_id,
        mime_type=mime_type,
        size=len(data),
        file_path=file_path,
        created_at=datetime.now(timezone.utc)
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    
    logger.info(f"Saved attachment {attach_id} for conversation {conversation_id}.")
    return record

def get_attachment(db: Session, attachment_id: str, principal_id: str) -> tuple[AttachmentRecord, bytes]:
    """
    Retrieves an attachment record and its raw bytes. Enforces ownership.
    """
    record = db.execute(
        select(AttachmentRecord)
        .where(AttachmentRecord.attachment_id == attachment_id)
        .where(AttachmentRecord.principal_id == principal_id)
    ).scalar_one_or_none()
    
    if not record:
        raise ValueError("Attachment not found or permission denied.")
        
    try:
        with open(record.file_path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        logger.error(f"Physical file missing for attachment {attachment_id}")
        raise ValueError("Attachment physical file is missing.")
        
    return record, data

def cleanup_attachments_for_message(db: Session, message_id: int) -> None:
    """
    Deletes the physical files for all attachments associated with a message.
    """
    records = db.execute(
        select(AttachmentRecord).where(AttachmentRecord.message_id == message_id)
    ).scalars().all()
    
    for r in records:
        try:
            os.remove(r.file_path)
        except OSError as e:
            logger.warning(f"Failed to remove attachment file {r.file_path}: {e}")
        db.delete(r)
    db.commit()

def reconcile_orphaned_attachments(db: Session) -> None:
    """
    Deletes files in the attachments directory that have no corresponding DB record,
    and removes DB records that have no physical file.
    """
    base_dir = get_attachments_dir()
    disk_files = set(os.listdir(base_dir))
    
    records = db.execute(select(AttachmentRecord)).scalars().all()
    db_files = {os.path.basename(r.file_path): r for r in records}
    
    # Files on disk not in DB
    orphans_on_disk = disk_files - set(db_files.keys())
    for f in orphans_on_disk:
        path = os.path.join(base_dir, f)
        if os.path.isfile(path):
            try:
                os.remove(path)
                logger.info(f"Removed orphaned attachment file {path}")
            except Exception as e:
                logger.warning(f"Failed to remove orphan file {path}: {e}")
                
    # Records in DB not on disk
    orphans_in_db = set(db_files.keys()) - disk_files
    for f in orphans_in_db:
        record = db_files[f]
        db.delete(record)
        logger.info(f"Removed orphaned DB record {record.attachment_id}")
        
    db.commit()
