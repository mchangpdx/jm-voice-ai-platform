from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu_item import MenuItem


async def get_menu(tenant_id: str, db: AsyncSession) -> list[MenuItem]:
    # SELECT * FROM menu_items WHERE tenant_id = :tenant_id ORDER BY category, name
    # CRITICAL: tenant_id filter is mandatory for RLS compliance (RLS 준수를 위해 tenant_id 필터 필수)
    stmt = (
        select(MenuItem)
        .where(MenuItem.tenant_id == tenant_id)
        .order_by(MenuItem.category, MenuItem.name)
    )
    result = await db.execute(stmt)
    return result.scalars().all()
