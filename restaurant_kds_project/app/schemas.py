from pydantic import BaseModel
from typing import List, Optional


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    source_role: str
    items: List[OrderItemCreate]
    waiter_id: Optional[int] = None
    waiter_name: Optional[str] = None
    order_label: Optional[str] = None


class OrderUpdate(BaseModel):
    items: List[OrderItemCreate]


class StatusUpdate(BaseModel):
    actor_role: str
    status: str


class ProductCreate(BaseModel):
    name: str
