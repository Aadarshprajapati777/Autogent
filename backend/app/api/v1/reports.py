"""Reports endpoints. The founder can view weekly reports and trigger
generation on demand."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...api.pagination import pagination_params
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.operations import Insight, WeeklyReport

router = APIRouter(prefix="/reports", tags=["reports"])


async def _check_member(workspace_id, user: User, session: AsyncSession) -> None:
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        raise HTTPException(403, "Not a member of this workspace")


@router.get("")
async def list_reports(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination_params),
) -> dict:
    await _check_member(workspace_id, user, session)
    base_query = select(WeeklyReport).where(WeeklyReport.workspace_id == workspace_id)
    total = await session.scalar(select(func.count()).select_from(base_query.subquery()))
    reports = (await session.execute(
        base_query.order_by(desc(WeeklyReport.period_start)).offset(page["skip"]).limit(page["limit"])
    )).scalars().all()
    return {
        "count": len(reports),
        "total": total,
        "skip": page["skip"],
        "limit": page["limit"],
        "has_more": (page["skip"] + len(reports)) < (total or 0),
        "reports": [
            {
                "id": str(r.id),
                "period_start": r.period_start.isoformat() if r.period_start else None,
                "status": r.status,
                "summary": r.data.get("summary") if r.data else None,
                "briefing": r.data.get("founder briefing") if r.data else None,
            }
            for r in reports
        ],
    }


@router.get("/{report_id}")
async def get_report(
    report_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(workspace_id, user, session)
    report = await session.scalar(
        select(WeeklyReport).where(
            WeeklyReport.workspace_id == workspace_id,
            WeeklyReport.id == report_id,
        )
    )
    if not report:
        raise HTTPException(404, "Report not found")
    insights = (await session.scalars(
        select(Insight).where(Insight.weekly_report_id == report.id)
    )).all()
    return {
        "id": str(report.id),
        "period_start": report.period_start.isoformat() if report.period_start else None,
        "status": report.status,
        "data": report.data,
        "insights": [
            {
                "key": i.key,
                "value": i.value,
                "confidence": i.confidence,
                "explanation": i.explanation,
            }
            for i in insights
        ],
    }


@router.post("/generate")
async def generate_report(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(workspace_id, user, session)
    from ...services.weekly_report import generate_weekly_report
    report = await generate_weekly_report(session, workspace_id)
    return {
        "id": str(report.id),
        "status": report.status,
        "briefing": report.data.get("founder briefing") if report.data else None,
    }
