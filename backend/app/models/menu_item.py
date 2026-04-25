from datetime import datetime

from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantBase


class MenuItem(TenantBase):
    # ORM model for menu_items table — migrated from legacy (레거시에서 마이그레이션된 menu_items 테이블 ORM 모델)
    # tenant_id replaces legacy store_id for RLS compliance (RLS 준수를 위해 store_id를 tenant_id로 대체)
    __tablename__ = "menu_items"

    variant_id: Mapped[str] = mapped_column(String, primary_key=True)
    # tenant_id inherited from TenantBase (tenant_id는 TenantBase에서 상속)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)  # US cents (미국 센트 단위)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
