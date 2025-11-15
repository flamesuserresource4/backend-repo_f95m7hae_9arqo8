import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from bson import ObjectId
from datetime import datetime, timezone
import hashlib
import hmac

from database import db, create_document, get_documents

app = FastAPI(title="Fruito API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utility
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")


def hash_password(password: str) -> str:
    # Simple HMAC-SHA256 hash for demo (not for real prod)
    return hmac.new(SECRET_KEY.encode(), password.encode(), hashlib.sha256).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)


# Schemas
class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str


class ProductIn(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    image: Optional[str] = None
    stock: int = 0


class ProductOut(ProductIn):
    id: str


class OrderItemIn(BaseModel):
    product_id: str
    quantity: int


class OrderOut(BaseModel):
    id: str
    user_id: str
    total: float
    status: str
    created_at: Optional[str] = None


class AdminCreateProductRequest(BaseModel):
    product: ProductIn
    credentials: LoginRequest


# Seed exactly one admin on startup
ADMIN_EMAIL = "deeptesh2006@gmail.com"
ADMIN_PASSWORD = "deep1591"


@app.on_event("startup")
def seed_admin():
    if db is None:
        return
    existing = db["user"].find_one({"email": ADMIN_EMAIL})
    if existing:
        # ensure it's the only admin
        db["user"].update_many({"email": {"$ne": ADMIN_EMAIL}, "role": "admin"}, {"$set": {"role": "user"}})
        db["user"].update_one({"email": ADMIN_EMAIL}, {"$set": {"role": "admin", "password_hash": hash_password(ADMIN_PASSWORD)}})
        return
    db["user"].insert_one({
        "name": "Admin",
        "email": ADMIN_EMAIL,
        "password_hash": hash_password(ADMIN_PASSWORD),
        "role": "admin",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    })
    # demote any other admins if somehow created
    db["user"].update_many({"email": {"$ne": ADMIN_EMAIL}, "role": "admin"}, {"$set": {"role": "user"}})


@app.get("/")
def read_root():
    return {"message": "Fruito API Running"}


@app.post("/auth/user/signup", response_model=UserPublic)
def user_signup(payload: SignupRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    if payload.email == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="This email is reserved for admin")
    if db["user"].find_one({"email": payload.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    uid = create_document("user", {
        "name": payload.name,
        "email": str(payload.email),
        "password_hash": hash_password(payload.password),
        "role": "user",
    })
    return {"id": uid, "name": payload.name, "email": payload.email, "role": "user"}


@app.post("/auth/user/login", response_model=UserPublic)
def user_login(payload: LoginRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    user = db["user"].find_one({"email": str(payload.email)})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("role") != "user":
        raise HTTPException(status_code=403, detail="Not a user account")
    return {"id": str(user["_id"]), "name": user.get("name", ""), "email": user.get("email"), "role": "user"}


@app.post("/auth/admin/login", response_model=UserPublic)
def admin_login(payload: LoginRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    user = db["user"].find_one({"email": str(payload.email)})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # ensure exactly one admin account is the specified one
    if str(payload.email) != ADMIN_EMAIL or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access denied")
    return {"id": str(user["_id"]), "name": user.get("name", "Admin"), "email": user.get("email"), "role": "admin"}


# Admin product management endpoints
@app.post("/admin/products", response_model=ProductOut)
def create_product(req: AdminCreateProductRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    creds = req.credentials
    admin = db["user"].find_one({"email": str(creds.email)})
    if not admin or not verify_password(creds.password, admin.get("password_hash", "")) or str(creds.email) != ADMIN_EMAIL or admin.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access denied")
    pid = create_document("product", req.product.model_dump())
    return {"id": pid, **req.product.model_dump()}


@app.get("/products", response_model=List[ProductOut])
def list_products():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    items = get_documents("product")
    result = []
    for it in items:
        result.append({
            "id": str(it.get("_id")),
            "name": it.get("name"),
            "description": it.get("description"),
            "price": float(it.get("price", 0)),
            "image": it.get("image"),
            "stock": int(it.get("stock", 0)),
        })
    return result


class OrderCreate(BaseModel):
    user_id: str
    items: List[OrderItemIn]


@app.post("/orders", response_model=OrderOut)
def place_order(order: OrderCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    # calculate total and simple stock check
    total = 0.0
    for item in order.items:
        prod = db["product"].find_one({"_id": ObjectId(item.product_id)})
        if not prod:
            raise HTTPException(status_code=404, detail="Product not found")
        if int(prod.get("stock", 0)) < item.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {prod.get('name')}")
        total += float(prod.get("price", 0)) * item.quantity
    # reduce stock
    for item in order.items:
        db["product"].update_one({"_id": ObjectId(item.product_id)}, {"$inc": {"stock": -item.quantity}})
    oid = create_document("order", {
        "user_id": order.user_id,
        "items": [i.model_dump() for i in order.items],
        "total": total,
        "status": "placed",
    })
    return {"id": oid, "user_id": order.user_id, "total": total, "status": "placed"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        from database import db
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
