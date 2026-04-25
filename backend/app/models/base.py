from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantBase(Base):
    # Abstract base enforcing tenant_id on every table (모든 테이블에 tenant_id 강제)
    __abstract__ = True
    tenant_id: Mapped[str] = mapped_column(index=True, nullable=False)
