import uuid
from datetime import UTC, datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.work import CandidateState, Task, TaskCandidate, TaskDependency


class ApprovalError(RuntimeError):
    pass


class TaskApprovalService:
    async def materialize(self, session: AsyncSession, candidate: TaskCandidate) -> Task:
        if candidate.state == CandidateState.REJECTED:
            raise ApprovalError("Rejected candidates cannot be materialized")
        if candidate.task_id:
            task = await session.get(Task, candidate.task_id)
            if task:
                return task
        task = Task(
            workspace_id=candidate.workspace_id,
            owner_id=candidate.owner_id,
            title=candidate.title,
            description=candidate.description,
            due_at=candidate.due_at,
            confidence=candidate.confidence,
            evidence=candidate.evidence,
        )
        session.add(task)
        await session.flush()
        candidate.task_id, candidate.state = task.id, CandidateState.MATERIALIZED
        return task

    async def materialize_dependencies(self, session: AsyncSession, candidate: TaskCandidate) -> None:
        if not candidate.task_id:
            return
        candidates = (
            (await session.execute(
                select(TaskCandidate).where(TaskCandidate.extraction_id == candidate.extraction_id)
            )).scalars().all()
        )
        by_ref = {item.ref: item for item in candidates}
        for dependency_ref in candidate.dependency_refs:
            dependency = by_ref.get(dependency_ref)
            if dependency and dependency.task_id:
                session.add(TaskDependency(
                    task_id=candidate.task_id, depends_on_task_id=dependency.task_id
                ))

    async def review(
        self,
        session: AsyncSession,
        candidate_id: uuid.UUID,
        decision: str,
        reviewer_id: uuid.UUID,
        edit: dict | None = None,
    ) -> TaskCandidate:
        candidate = await session.get(TaskCandidate, candidate_id)
        if not candidate:
            raise ApprovalError("Candidate not found")
        if candidate.state in (CandidateState.REJECTED, CandidateState.MATERIALIZED):
            return candidate
        if decision == "reject":
            candidate.state, candidate.reviewed_by_id, candidate.reviewed_at = (
                CandidateState.REJECTED, reviewer_id, datetime.now(UTC),
            )
            await session.commit()
            return candidate
        if decision == "edit":
            if not edit:
                raise ApprovalError("Edit payload required")
            for key in ("title", "description", "due_at", "owner_id"):
                if key in edit:
                    setattr(candidate, key, edit[key])
            candidate.state = CandidateState.EDITED
        elif decision != "approve":
            raise ApprovalError("Unsupported approval decision")
        candidate.reviewed_by_id, candidate.reviewed_at = reviewer_id, datetime.now(UTC)
        await self.materialize(session, candidate)
        await self.materialize_dependencies(session, candidate)
        await session.commit()
        return candidate
