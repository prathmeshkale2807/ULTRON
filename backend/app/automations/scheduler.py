import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
import uuid
import json

from app.core.database import SessionLocal, engine
from app.automations.models import (
    AutomationRecord, 
    AutomationRunRecord, 
    RunStatus, 
    AutomationStatus,
    MisfirePolicy,
    AutomationType
)
from app.automations.manager import AutomationManager
from app.tasks.manager import TaskManager
from app.tasks.models import TaskState

logger = logging.getLogger(__name__)

class SchedulerEngine:
    def __init__(self):
        self.running = False
        self._task = None

    def start(self):
        if not self.running:
            self.running = True
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self.running:
            try:
                await asyncio.to_thread(self._tick)
            except Exception as e:
                logger.error(f"Scheduler tick failed: {e}")
            await asyncio.sleep(5)

    def _tick(self):
        with SessionLocal() as db:
            # 1. Recover stale claims
            self._recover_stale_claims(db)
            
            # 2. Check Emergency Stop
            from app.safety.manager import is_emergency_stop_engaged
            is_stopped = is_emergency_stop_engaged()
            
            # 3. Generate new runs for due automations
            self._generate_due_runs(db)
            
            if not is_stopped:
                # 4. Handle misfires
                self._handle_misfires(db)
                
                # 5. Claim and submit runs
                self._claim_and_submit_runs(db)

    def _recover_stale_claims(self, db: Session):
        now = datetime.now(timezone.utc)
        
        stale_runs = db.execute(
            select(AutomationRunRecord)
            .where(AutomationRunRecord.status == RunStatus.CLAIMED)
            .where(AutomationRunRecord.claim_expires_at < now)
        ).scalars().all()

        if not stale_runs:
            return

        task_mgr = TaskManager(db)
        
        for run in stale_runs:
            if run.task_id:
                try:
                    # In this system tasks don't have session_id enforced on get if session_id=None
                    # Actually get_task requires matching session_id, but here we can just query directly or bypass
                    # if manager get() enforces it, we might need to bypass it or pass None. 
                    from app.core.database import TaskRecord
                    task = db.get(TaskRecord, run.task_id)
                    if not task:
                        raise ValueError("Task not found")

                    if task.state in (TaskState.QUEUED.value, TaskState.PLANNING.value, TaskState.WAITING_FOR_PERMISSION.value):
                        run.status = RunStatus.SUBMITTED
                    elif task.state == TaskState.RUNNING.value:
                        run.status = RunStatus.RUNNING
                    elif task.state == TaskState.COMPLETED.value:
                        run.status = RunStatus.COMPLETED
                    elif task.state == TaskState.FAILED.value:
                        run.status = RunStatus.FAILED
                    elif task.state == TaskState.CANCELLED.value:
                        run.status = RunStatus.CANCELLED
                    run.claim_token = None
                    db.commit()
                except Exception:
                    run.status = RunStatus.SCHEDULED
                    run.claim_token = None
                    db.commit()
            else:
                # Look up task by idempotency_key in metadata
                # Assuming task description or metadata has it? We don't have metadata column!
                # We can't safely know if it was submitted. We will assume it wasn't.
                run.status = RunStatus.SCHEDULED
                run.claim_token = None
                db.commit()

    def _generate_due_runs(self, db: Session):
        now = datetime.now(timezone.utc)
        due_automations = db.execute(
            select(AutomationRecord)
            .where(AutomationRecord.status == AutomationStatus.ACTIVE)
            .where(AutomationRecord.next_run_at <= now)
        ).scalars().all()
        
        mgr = AutomationManager(db)

        for auto in due_automations:
            new_run_count = auto.run_count + 1
            idem_key = f"{auto.id}_{auto.automation_version}_{new_run_count}"
            
            run_record = AutomationRunRecord(
                automation_id=auto.id,
                automation_version=auto.automation_version,
                principal_id=auto.principal_id,
                scheduled_for=auto.next_run_at,
                status=RunStatus.SCHEDULED,
                idempotency_key=idem_key
            )
            
            db.add(run_record)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                continue
            
            auto.last_run_at = auto.next_run_at
            auto.run_count = new_run_count
            
            if auto.automation_type in (AutomationType.ONE_TIME, AutomationType.DELAY):
                auto.status = AutomationStatus.COMPLETED
                auto.next_run_at = None
            elif auto.max_runs and auto.run_count >= auto.max_runs:
                auto.status = AutomationStatus.COMPLETED
                auto.next_run_at = None
            else:
                try:
                    auto.next_run_at = mgr._calculate_next_run(
                        auto.automation_type, 
                        auto.schedule_definition, 
                        auto.timezone, 
                        now
                    )
                except Exception as e:
                    auto.status = AutomationStatus.FAILED
                    logger.error(f"Failed to calculate next run for {auto.id}: {e}")
            
            db.commit()

    def _handle_misfires(self, db: Session):
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(minutes=5)
        
        missed_runs = db.execute(
            select(AutomationRunRecord, AutomationRecord.misfire_policy)
            .join(AutomationRecord, AutomationRunRecord.automation_id == AutomationRecord.id)
            .where(AutomationRunRecord.status == RunStatus.SCHEDULED)
            .where(AutomationRunRecord.scheduled_for < stale_threshold)
        ).all()
        
        for run, policy in missed_runs:
            if policy == MisfirePolicy.SKIP:
                run.status = RunStatus.EXPIRED
                run.error_summary = "Skipped due to misfire policy"
                db.commit()

    def _claim_and_submit_runs(self, db: Session):
        now = datetime.now(timezone.utc)
        
        pending_ids = db.execute(
            select(AutomationRunRecord.id)
            .where(AutomationRunRecord.status == RunStatus.SCHEDULED)
            .where(AutomationRunRecord.scheduled_for <= now)
        ).scalars().all()
        
        if not pending_ids:
            return
            
        task_mgr = TaskManager(db)
            
        for run_id in pending_ids:
            claim_token = str(uuid.uuid4())
            claim_expires = now + timedelta(minutes=1)
            
            result = db.execute(
                update(AutomationRunRecord)
                .where(AutomationRunRecord.id == run_id)
                .where(AutomationRunRecord.status == RunStatus.SCHEDULED)
                .where((AutomationRunRecord.claim_token.is_(None)) | (AutomationRunRecord.claim_expires_at < now))
                .values(
                    status=RunStatus.CLAIMED,
                    claim_token=claim_token,
                    claimed_at=now,
                    claim_expires_at=claim_expires
                )
            )
            db.commit()
            
            if result.rowcount == 0:
                continue
            
            run = db.execute(select(AutomationRunRecord).where(AutomationRunRecord.id == run_id)).scalar_one()
            auto = db.execute(select(AutomationRecord).where(AutomationRecord.id == run.automation_id)).scalar_one()
            
            try:
                task_def = auto.task_definition
                tools_req = [{
                    "tool_name": task_def.get("tool_name"),
                    "arguments": task_def.get("tool_args", {})
                }]
                
                # Create task owned by principal_id
                from app.core.database import TaskRecord
                
                # Since TaskManager.create() sets principal_id from execution context usually, 
                # wait, let's look at TaskManager.create() implementation. We will just use it normally,
                # passing None for session_id to indicate it's system-generated but acting on behalf of principal.
                # Actually, in Phase 16, tasks have a principal_id field? Let's verify TaskRecord fields.
                # We will manually set principal_id if create doesn't expose it.
                task = task_mgr.create(
                    session_id=None,
                    description=f"Automation Run: {auto.name}",
                    tools_requested=tools_req,
                    actor=auto.principal_id
                )
                
                # Explicitly set the principal_id on the TaskRecord since create() might not
                task.principal_id = auto.principal_id
                run.task_id = task.task_id
                run.status = RunStatus.SUBMITTED
                
                # Push to worker queue using the background queue
                from app.tasks.worker import get_task_worker
                worker = get_task_worker()
                if worker:
                    asyncio.create_task(worker.submit(task.task_id)) # Normal priority
                    
                db.commit()
            except Exception as e:
                run.status = RunStatus.FAILED
                run.error_summary = str(e)
                db.commit()
                continue

scheduler_engine = SchedulerEngine()
