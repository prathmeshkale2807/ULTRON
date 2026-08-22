from fastapi import APIRouter, Depends, HTTPException
from typing import List

from sqlalchemy.orm import Session
from app.core.database import get_db
from app.security.local_auth import Principal, require_local_auth
from app.memory.store import MemoryStore
from app.memory.models import MemoryCreate, MemoryUpdate, MemorySchema

router = APIRouter(prefix="/api/memory", tags=["memory"])

@router.post("", response_model=MemorySchema, status_code=201)
def create_memory(
    data: MemoryCreate,
    principal: Principal = Depends(require_local_auth),
    db: Session = Depends(get_db)
):
    store = MemoryStore(db, principal.identity)
    return store.create(data)

@router.get("", response_model=List[MemorySchema])
def list_memories(
    query: str = "",
    principal: Principal = Depends(require_local_auth),
    db: Session = Depends(get_db)
):
    store = MemoryStore(db, principal.identity)
    return store.search(query=query)

@router.get("/{memory_id}", response_model=MemorySchema)
def get_memory(
    memory_id: str,
    principal: Principal = Depends(require_local_auth),
    db: Session = Depends(get_db)
):
    store = MemoryStore(db, principal.identity)
    mem = store.get(memory_id)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    return mem

@router.patch("/{memory_id}", response_model=MemorySchema)
def update_memory(
    memory_id: str,
    data: MemoryUpdate,
    principal: Principal = Depends(require_local_auth),
    db: Session = Depends(get_db)
):
    store = MemoryStore(db, principal.identity)
    mem = store.update(memory_id, data)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    return mem

@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: str,
    principal: Principal = Depends(require_local_auth),
    db: Session = Depends(get_db)
):
    store = MemoryStore(db, principal.identity)
    if not store.delete(memory_id, hard=True):
        raise HTTPException(status_code=404, detail="Memory not found")

@router.delete("", status_code=204)
def forget_all(
    principal: Principal = Depends(require_local_auth),
    db: Session = Depends(get_db)
):
    store = MemoryStore(db, principal.identity)
    store.delete_all(hard=True)
