"""Initial database schema covering all 10 domain entities.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-04 13:30:00.000000

Implements PLAN.md T-DB-11 and TRD.md §D.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. customers table
    op.create_table(
        "customers",
        sa.Column("customer_id_hash", sa.String(length=64), nullable=False, comment="SHA-256 customer hash"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("customer_id_hash"),
    )
    op.create_index("ix_customers_customer_id_hash", "customers", ["customer_id_hash"], unique=False)

    # 2. orders table
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id_hash", sa.String(length=64), nullable=False),
        sa.Column("order_value", sa.Numeric(precision=12, scale=2), nullable=False, comment="Gross order amount in INR"),
        sa.Column("payment_method", sa.String(length=32), nullable=False),
        sa.Column("cod_flag", sa.Boolean(), nullable=False, comment="True if Cash On Delivery"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["customer_id_hash"], ["customers.customer_id_hash"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_customer_id_hash", "orders", ["customer_id_hash"], unique=False)
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)

    # 3. return_requests table
    op.create_table(
        "return_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("return_reason", sa.Text(), nullable=False, comment="Customer-provided free text return rationale"),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_return_requests_order_id", "return_requests", ["order_id"], unique=False)
    op.create_index("ix_return_requests_requested_at", "return_requests", ["requested_at"], unique=False)

    # 4. model_versions table
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mlflow_run_id", sa.String(length=128), nullable=False, comment="Tracking run identifier or artifact hash"),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_versions_mlflow_run_id", "model_versions", ["mlflow_run_id"], unique=False)
    op.create_index("ix_model_versions_model_type", "model_versions", ["model_type"], unique=False)

    # 5. risk_decisions table
    op.create_table(
        "risk_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("return_request_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, comment="Client deduplication token"),
        sa.Column("p_return_abuse", sa.Numeric(precision=5, scale=4), nullable=False, comment="Calibrated abuse probability (0.0000 - 1.0000)"),
        sa.Column("risk_band", sa.String(length=32), nullable=False),
        sa.Column("scoring_source", sa.String(length=32), nullable=False),
        sa.Column("fallback_tier", sa.SmallInteger(), nullable=False, comment="0=Primary, 1=IsolationForest, 2=Rules"),
        sa.Column("fallback_reason", sa.String(length=255), nullable=True),
        sa.Column("model_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"]),
        sa.ForeignKeyConstraint(["return_request_id"], ["return_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_risk_decisions_return_request_id", "risk_decisions", ["return_request_id"], unique=False)
    op.create_index("ix_risk_decisions_idempotency_key", "risk_decisions", ["idempotency_key"], unique=True)
    op.create_index("ix_risk_decisions_risk_band", "risk_decisions", ["risk_band"], unique=False)
    op.create_index("ix_risk_decisions_created_at", "risk_decisions", ["created_at"], unique=False)

    # 6. risk_features table
    op.create_table(
        "risk_features",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("risk_decision_id", sa.Uuid(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False, comment="Complete serialized feature vector dictionary"),
        sa.Column("feature_schema_version", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["risk_decision_id"], ["risk_decisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_risk_features_risk_decision_id", "risk_features", ["risk_decision_id"], unique=True)

    # 7. interventions table
    op.create_table(
        "interventions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("risk_decision_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("expected_net_value", sa.Numeric(precision=12, scale=2), nullable=False, comment="Expected net economic value in INR"),
        sa.Column("selected_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["risk_decision_id"], ["risk_decisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interventions_risk_decision_id", "interventions", ["risk_decision_id"], unique=False)
    op.create_index("ix_interventions_action", "interventions", ["action"], unique=False)
    op.create_index("ix_interventions_created_at", "interventions", ["created_at"], unique=False)

    # 8. agent_runs table
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("risk_decision_id", sa.Uuid(), nullable=False),
        sa.Column("agent_name", sa.String(length=32), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False, comment="Pydantic structured output dump"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["risk_decision_id"], ["risk_decisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_risk_decision_id", "agent_runs", ["risk_decision_id"], unique=False)
    op.create_index("ix_agent_runs_agent_name", "agent_runs", ["agent_name"], unique=False)
    op.create_index("ix_agent_runs_started_at", "agent_runs", ["started_at"], unique=False)

    # 9. policy_decisions table (append-only state transitions)
    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("risk_decision_id", sa.Uuid(), nullable=False),
        sa.Column("previous_action", sa.String(length=16), nullable=True, comment="Prior action state"),
        sa.Column("new_action", sa.String(length=16), nullable=False, comment="Effective action after transition"),
        sa.Column("selected_by", sa.String(length=32), nullable=False, comment="LINUCB, RULES, or MANUAL_OVERRIDE"),
        sa.Column("operator_id", sa.String(length=128), nullable=True, comment="Required for MANUAL_OVERRIDE"),
        sa.Column("reason", sa.Text(), nullable=True, comment="Operator justification for override"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["risk_decision_id"], ["risk_decisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policy_decisions_risk_decision_id", "policy_decisions", ["risk_decision_id"], unique=False)
    op.create_index("ix_policy_decisions_created_at", "policy_decisions", ["created_at"], unique=False)

    # 10. audit_events table (append-only event envelopes)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False, comment="Unique event identifier from envelope"),
        sa.Column("event_type", sa.String(length=64), nullable=False, comment="Envelope event_type"),
        sa.Column("payload", sa.JSON(), nullable=False, comment="Full serialized event envelope dictionary"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_event_id", "audit_events", ["event_id"], unique=True)
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"], unique=False)
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"], unique=False)


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("policy_decisions")
    op.drop_table("agent_runs")
    op.drop_table("interventions")
    op.drop_table("risk_features")
    op.drop_table("risk_decisions")
    op.drop_table("model_versions")
    op.drop_table("return_requests")
    op.drop_table("orders")
    op.drop_table("customers")
