from sqlalchemy import JSON, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AppSetting(TimestampMixin, Base):
    """A setting stored server-side, so that the API and the worker read the same value (e.g. the performance
    profile under the key "performance")."""

    __tablename__ = "app_settings"
    __table_args__ = (PrimaryKeyConstraint("key", name="pk_app_settings"),)

    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
