from pydantic import BaseModel


class MenuItemOut(BaseModel):
    # Output schema for a single menu item (메뉴 항목 출력 스키마)
    variant_id: str
    item_id: str
    name: str
    category: str
    price: int  # cents (센트 단위)
    stock_quantity: int
    model_config = {"from_attributes": True}
