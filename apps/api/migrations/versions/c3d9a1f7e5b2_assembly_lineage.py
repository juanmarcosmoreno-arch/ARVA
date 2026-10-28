"""assembly lineage: assemblies.kind ('assembly' | 'polished') and parent_assembly_id (the draft of a polished one)

Revision ID: c3d9a1f7e5b2
Revises: b5c2e81f4a97
Create Date: 2026-10-28 17:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d9a1f7e5b2"
down_revision: str | Sequence[str] | None = "b5c2e81f4a97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assemblies", sa.Column(
        "kind", sa.Enum("assembly", "polished", name="assemblykind", native_enum=False), nullable=False,
        server_default="assembly"))
    op.alter_column("assemblies", "kind", server_default=None)
    op.add_column("assemblies", sa.Column("parent_assembly_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_assemblies_parent_assembly_id", "assemblies", "assemblies", ["parent_assembly_id"], ["id"],
                          ondelete="SET NULL")
    op.create_index("ix_assemblies_parent_assembly_id", "assemblies", ["parent_assembly_id"])


def downgrade() -> None:
    # Without these columns a polished assembly would look like an assembler's output; refuse instead.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM assemblies WHERE kind = 'polished'"))
    if count:
        raise RuntimeError(
            f"{count} polished assembly record(s) exist. Remove them first with "
            "\"DELETE FROM assemblies WHERE kind = 'polished'\" if you accept losing their records."
        )
    op.drop_index("ix_assemblies_parent_assembly_id", table_name="assemblies")
    op.drop_constraint("fk_assemblies_parent_assembly_id", "assemblies", type_="foreignkey")
    op.drop_column("assemblies", "parent_assembly_id")
    op.drop_column("assemblies", "kind")
