"""
Database Schemas for Fruito

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user"
- Product -> "product"
- Order -> "order"
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="BCrypt hash of the password")
    role: str = Field("user", description="Role of the account: user")

class Product(BaseModel):
    name: str = Field(..., description="Fruit name")
    description: Optional[str] = Field(None, description="Short description")
    price: float = Field(..., ge=0, description="Price in USD")
    image: Optional[str] = Field(None, description="Image URL")
    stock: int = Field(0, ge=0, description="Units in stock")

class OrderItem(BaseModel):
    product_id: str = Field(..., description="Product ID")
    name: str = Field(..., description="Snapshot of product name at purchase time")
    price: float = Field(..., ge=0, description="Unit price at purchase time")
    quantity: int = Field(..., ge=1, description="Quantity ordered")

class Order(BaseModel):
    user_id: str = Field(..., description="ID of the user placing the order")
    items: List[OrderItem] = Field(..., description="Line items")
    total: float = Field(..., ge=0, description="Order total")
    status: str = Field("placed", description="Order status")
