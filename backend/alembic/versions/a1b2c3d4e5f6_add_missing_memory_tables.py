"""add missing memory tables

Revision ID: a1b2c3d4e5f6
Revises: 41d67dc67154
Create Date: 2026-09-01

Adds 9 tables that were defined in the models but missing from the
initial migration: memory_alerts, memory_sprints, memory_checkin_records,
memory_milestones, memory_spends, memory_decision_history,
memory_action_queue, memory_fact_relations, memory_state_snapshots.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1b2c3d4e5f6"
down_revision = "41d67dc67154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── memory_alerts ──
    op.create_table(
        "memory_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_id", sa.String(64), nullable=False, unique=True),
        sa.Column("alert_type", sa.String(40), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False, server_default=""),
        sa.Column("project", sa.String(200), nullable=True),
        sa.Column("person", sa.String(200), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("evidence_fact_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("escalation_level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("acknowledged_at", sa.DateTime, nullable=True),
        sa.Column("escalated_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_alerts_workspace_id", "memory_alerts", ["workspace_id"])
    op.create_index("ix_memory_alerts_alert_id", "memory_alerts", ["alert_id"], unique=True)
    op.create_index("ix_memory_alerts_project", "memory_alerts", ["project"])
    op.create_index("ix_alerts_status", "memory_alerts", ["workspace_id", "status"])
    op.create_index("ix_alerts_type", "memory_alerts", ["workspace_id", "alert_type"])

    # ── memory_sprints ──
    op.create_table(
        "memory_sprints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sprint_id", sa.String(64), nullable=False, unique=True),
        sa.Column("project", sa.String(200), nullable=False),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("start_date", sa.DateTime, nullable=False),
        sa.Column("end_date", sa.DateTime, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="planning"),
        sa.Column("task_ids", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_sprints_workspace_id", "memory_sprints", ["workspace_id"])
    op.create_index("ix_memory_sprints_sprint_id", "memory_sprints", ["sprint_id"], unique=True)
    op.create_index("ix_sprints_project", "memory_sprints", ["workspace_id", "project"])

    # ── memory_checkin_records ──
    op.create_table(
        "memory_checkin_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_name", sa.String(200), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("thread_ts", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_checkin_records_workspace_id", "memory_checkin_records", ["workspace_id"])
    op.create_index("ix_checkin_person", "memory_checkin_records", ["workspace_id", "person_name"])

    # ── memory_milestones ──
    op.create_table(
        "memory_milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("milestone_id", sa.String(64), nullable=False, unique=True),
        sa.Column("project", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("target_date", sa.String(32), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="upcoming"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_milestones_workspace_id", "memory_milestones", ["workspace_id"])
    op.create_index("ix_memory_milestones_milestone_id", "memory_milestones", ["milestone_id"], unique=True)
    op.create_index("ix_milestones_project", "memory_milestones", ["workspace_id", "project"])

    # ── memory_spends ──
    op.create_table(
        "memory_spends",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("spend_id", sa.String(64), nullable=False, unique=True),
        sa.Column("project", sa.String(200), nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("category", sa.String(100), nullable=False, server_default="general"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_spends_workspace_id", "memory_spends", ["workspace_id"])
    op.create_index("ix_memory_spends_spend_id", "memory_spends", ["spend_id"], unique=True)
    op.create_index("ix_spends_project", "memory_spends", ["workspace_id", "project"])

    # ── memory_decision_history ──
    op.create_table(
        "memory_decision_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_id", sa.String(64), nullable=False, unique=True),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("audience", sa.String(40), nullable=False, server_default="founder_non_technical"),
        sa.Column("response_text", sa.Text, nullable=False, server_default=""),
        sa.Column("reasoning", sa.Text, nullable=False, server_default=""),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("suggested_actions", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("outcome_notes", sa.Text, nullable=True),
        sa.Column("outcome_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_decision_history_workspace_id", "memory_decision_history", ["workspace_id"])
    op.create_index("ix_memory_decision_history_decision_id", "memory_decision_history", ["decision_id"], unique=True)
    op.create_index("ix_decisions_workspace", "memory_decision_history", ["workspace_id", "created_at"])

    # ── memory_action_queue ──
    op.create_table(
        "memory_action_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.String(128), nullable=False, unique=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target", sa.String(300), nullable=False, server_default=""),
        sa.Column("message", sa.Text, nullable=False, server_default=""),
        sa.Column("urgency", sa.String(20), nullable=False, server_default="low"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_action_queue_workspace_id", "memory_action_queue", ["workspace_id"])
    op.create_index("ix_memory_action_queue_action_id", "memory_action_queue", ["action_id"], unique=True)
    op.create_index("ix_actions_status", "memory_action_queue", ["workspace_id", "status"])

    # ── memory_fact_relations ──
    op.create_table(
        "memory_fact_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_fact_id", sa.String(64), nullable=False),
        sa.Column("to_fact_id", sa.String(64), nullable=False),
        sa.Column("relation_type", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_fact_relations_workspace_id", "memory_fact_relations", ["workspace_id"])
    op.create_index("ix_memory_fact_relations_from_fact_id", "memory_fact_relations", ["from_fact_id"])
    op.create_index("ix_memory_fact_relations_to_fact_id", "memory_fact_relations", ["to_fact_id"])

    # ── memory_state_snapshots ──
    op.create_table(
        "memory_state_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_name", sa.String(200), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("risk_signals", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("open_commitments", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_since_last", sa.Integer, nullable=False, server_default="0"),
        sa.Column("missed_or_late", sa.Integer, nullable=False, server_default="0"),
        sa.Column("days_since_last_seen", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_state_snapshots_workspace_id", "memory_state_snapshots", ["workspace_id"])
    op.create_index("ix_state_snapshots_entity", "memory_state_snapshots", ["workspace_id", "entity_type", "entity_name"])


def downgrade() -> None:
    for table in (
        "memory_state_snapshots",
        "memory_fact_relations",
        "memory_action_queue",
        "memory_decision_history",
        "memory_spends",
        "memory_milestones",
        "memory_checkin_records",
        "memory_sprints",
        "memory_alerts",
    ):
        op.drop_table(table)
