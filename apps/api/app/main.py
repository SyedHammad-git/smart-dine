import os
import uuid
from datetime import date
from typing import List, Optional
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from svix.webhooks import Webhook, WebhookVerificationError

from app.db.database import engine, get_db
from app.db import models

# Naye models ke hisaab se tables banayega
models.Base.metadata.create_all(bind=engine)
with engine.begin() as connection:
    connection.execute(text("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'PENDING'"))
    connection.execute(text("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS address VARCHAR"))
    connection.execute(text("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS city VARCHAR"))
    connection.execute(text("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS logo_url VARCHAR"))
    connection.execute(text("ALTER TABLE branches ADD COLUMN IF NOT EXISTS address VARCHAR"))
    connection.execute(text("ALTER TABLE branches ADD COLUMN IF NOT EXISTS contact VARCHAR"))
    connection.execute(text("ALTER TABLE branches ADD COLUMN IF NOT EXISTS manager_name VARCHAR"))
    connection.execute(text("ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS image_url TEXT"))

app = FastAPI(title="Smart Dine API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to Smart Dine API v2.0 (Complete Architecture)!"}

# --- Clerk Webhook Endpoint ---
@app.post("/api/v1/webhooks/clerk")
async def clerk_webhook(request: Request, db: Session = Depends(get_db)):
    CLERK_WEBHOOK_SECRET = os.getenv("CLERK_WEBHOOK_SECRET")
    if not CLERK_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret missing")

    headers = request.headers
    svix_id = headers.get("svix-id")
    svix_timestamp = headers.get("svix-timestamp")
    svix_signature = headers.get("svix-signature")

    if not svix_id or not svix_timestamp or not svix_signature:
        raise HTTPException(status_code=400, detail="Missing Svix headers")

    payload = await request.body()
    wh = Webhook(CLERK_WEBHOOK_SECRET)
    try:
        evt = wh.verify(payload, headers)
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = evt.get("type")
    data = evt.get("data")

    if event_type == "user.created":
        clerk_id = data.get("id")
        email = data.get("email_addresses")[0].get("email_address")
        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip() or "Smart Dine Owner"

        user = db.query(models.User).filter(models.User.clerk_user_id == clerk_id).first()
        if not user:
            email_user = db.query(models.User).filter(models.User.email == email).first()
            if email_user and email_user.clerk_user_id != clerk_id:
                raise HTTPException(status_code=409, detail="Email is already linked to another account")
            user = email_user
        if not user:
            user = models.User(clerk_user_id=clerk_id, email=email, full_name=full_name)
            db.add(user)
            db.flush()
        else:
            user.clerk_user_id = clerk_id
            user.email = email
            user.full_name = full_name

        restaurant = db.query(models.Restaurant).filter(
            models.Restaurant.owner_user_id == user.id
        ).first()
        if not restaurant:
            restaurant = models.Restaurant(
                clerk_org_id=f"org_{uuid.uuid4().hex[:16]}",
                owner_user_id=user.id,
                name=f"{full_name}'s Restaurant",
                slug=f"rest-{uuid.uuid4().hex[:8]}",
                status="PENDING",
            )
            db.add(restaurant)
            db.flush()

        branch = db.query(models.Branch).filter(
            models.Branch.restaurant_id == restaurant.id
        ).first()
        if not branch:
            db.add(models.Branch(
                restaurant_id=restaurant.id,
                name="Main Branch",
                code="MAIN-01",
            ))
        db.commit()
        print(f"✅ SUCCESS: User, Pending Restaurant & Branch created for {email}")

    return {"success": True}

# --- PYDANTIC SCHEMAS ---
class CategoryCreate(BaseModel):
    name: str

class MenuItemCreate(BaseModel):
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    price: float
    category_id: str

class MenuAvailabilityUpdate(BaseModel):
    is_available: bool

class TableCreate(BaseModel):
    table_number: str
    capacity: int = 4

class TableStatusUpdate(BaseModel):
    status: Optional[models.TableStatus] = None

class SessionCreate(BaseModel):
    qr_public_id: str

class OrderItemCreate(BaseModel):
    menu_item_id: str
    quantity: int
    notes: Optional[str] = None

class OrderCreate(BaseModel):
    table_session_id: str
    table_id: Optional[str] = None
    items: List[OrderItemCreate]

class OrderStatusUpdate(BaseModel):
    status: models.OrderStatus

class BillCreate(BaseModel):
    table_session_id: str

class PaymentCreate(BaseModel):
    method: str
    amount: float

class RestaurantUpdate(BaseModel):
    name: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    address: Optional[str] = None
    logo_url: Optional[str] = None
    city: Optional[str] = None

class OnboardingCreate(BaseModel):
    clerk_user_id: str
    email: str
    full_name: str
    restaurant_name: str
    phone: str
    address: str
    cuisine_type: str

@app.post("/api/v1/onboarding")
def complete_restaurant_onboarding(data: OnboardingCreate, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(
        models.User.clerk_user_id == data.clerk_user_id
    ).first()
    if not user:
        email_user = db.query(models.User).filter(models.User.email == data.email).first()
        if email_user and email_user.clerk_user_id != data.clerk_user_id:
            raise HTTPException(status_code=409, detail="Email is already linked to another account")
        user = email_user or models.User(
            clerk_user_id=data.clerk_user_id,
            email=data.email,
            full_name=data.full_name,
        )
        if email_user is None:
            db.add(user)
            db.flush()

    restaurant = db.query(models.Restaurant).filter(
        models.Restaurant.owner_user_id == user.id
    ).first()
    if not restaurant:
        restaurant = models.Restaurant(
            clerk_org_id=f"org_{uuid.uuid4().hex[:16]}",
            owner_user_id=user.id,
            name=data.restaurant_name,
            slug=f"rest-{uuid.uuid4().hex[:8]}",
            status="PENDING",
        )
        db.add(restaurant)
        db.flush()
    else:
        restaurant.name = data.restaurant_name
        restaurant.address = data.address
        restaurant.settings_json = {
            **(restaurant.settings_json or {}),
            "phone": data.phone,
            "cuisine_type": data.cuisine_type,
        }

    restaurant.address = data.address
    restaurant.settings_json = {
        **(restaurant.settings_json or {}),
        "phone": data.phone,
        "cuisine_type": data.cuisine_type,
        "onboarding_complete": True,
    }
    branch = db.query(models.Branch).filter(
        models.Branch.restaurant_id == restaurant.id
    ).order_by(models.Branch.created_at.asc()).first()
    if not branch:
        branch = models.Branch(
            restaurant_id=restaurant.id,
            name="Main Branch",
            code="MAIN-01",
            status="ACTIVE",
            address=data.address,
            contact=data.phone,
        )
        db.add(branch)
        db.flush()
    else:
        branch.name = "Main Branch"
        branch.code = "MAIN-01"
        branch.address = data.address
        branch.contact = data.phone

    db.commit()
    db.refresh(restaurant)
    db.refresh(branch)
    return {
        "success": True,
        "restaurant_id": str(restaurant.id),
        "branch_id": str(branch.id),
        "restaurant_name": restaurant.name,
        "branch_name": branch.name,
        "status": restaurant.status,
        "onboarding_complete": True,
    }

class BranchCreate(BaseModel):
    name: str
    code: str
    status: str = "ACTIVE"
    address: Optional[str] = None
    contact: Optional[str] = None
    manager_name: Optional[str] = None
    tables_count: int = 0

class BranchUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    status: Optional[str] = None
    address: Optional[str] = None
    contact: Optional[str] = None
    manager_name: Optional[str] = None
    tables_count: Optional[int] = None

class StaffCreate(BaseModel):
    name: str
    email: str
    role: str

class StaffUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None

def branch_response(branch: models.Branch, db: Session):
    return {
        "id": str(branch.id),
        "restaurant_id": str(branch.restaurant_id),
        "name": branch.name,
        "code": branch.code,
        "status": branch.status,
        "address": branch.address,
        "contact": branch.contact,
        "manager_name": branch.manager_name,
        "tables_count": db.query(models.Table).filter(models.Table.branch_id == branch.id).count(),
        "staff_count": db.query(models.StaffMember).filter(models.StaffMember.branch_id == branch.id).count(),
        "today_orders": db.query(models.Order).filter(
            models.Order.branch_id == branch.id,
            text("DATE(created_at) = CURRENT_DATE"),
        ).count(),
    }

def staff_response(member: models.StaffMember):
    return {
        "id": str(member.id),
        "branch_id": str(member.branch_id),
        "name": member.name,
        "email": member.email,
        "role": member.role,
        "status": member.status,
    }

@app.get("/api/v1/restaurants/{restaurant_id}/branches")
def get_branches(restaurant_id: str, db: Session = Depends(get_db)):
    branches = db.query(models.Branch).filter(
        models.Branch.restaurant_id == restaurant_id
    ).order_by(models.Branch.created_at.asc()).all()
    return {"success": True, "branches": [branch_response(branch, db) for branch in branches]}

@app.post("/api/v1/restaurants/{restaurant_id}/branches")
def create_branch(restaurant_id: str, data: BranchCreate, db: Session = Depends(get_db)):
    restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if data.status not in {"ACTIVE", "INACTIVE"}:
        raise HTTPException(status_code=400, detail="Unsupported branch status")
    if data.tables_count < 0 or data.tables_count > 500:
        raise HTTPException(status_code=400, detail="Table count must be between 0 and 500")
    branch = models.Branch(
        restaurant_id=restaurant.id,
        name=data.name.strip(),
        code=data.code.strip(),
        status=data.status,
        address=data.address,
        contact=data.contact,
        manager_name=data.manager_name,
    )
    db.add(branch)
    db.flush()
    for number in range(1, data.tables_count + 1):
        db.add(models.Table(
            branch_id=branch.id,
            table_number=f"{number:02d}",
            qr_public_id=uuid.uuid4().hex[:12],
        ))
    db.commit()
    db.refresh(branch)
    return {"success": True, "branch": branch_response(branch, db)}

@app.put("/api/v1/branches/{branch_id}")
def update_branch(branch_id: str, data: BranchUpdate, db: Session = Depends(get_db)):
    branch = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    updates = data.dict(exclude_unset=True)
    if updates.get("status") not in (None, "ACTIVE", "INACTIVE"):
        raise HTTPException(status_code=400, detail="Unsupported branch status")
    tables_count = updates.pop("tables_count", None)
    if tables_count is not None:
        if tables_count < 0 or tables_count > 500:
            raise HTTPException(status_code=400, detail="Table count must be between 0 and 500")
        branch_tables = db.query(models.Table).filter(
            models.Table.branch_id == branch.id
        ).order_by(models.Table.table_number.asc()).all()
        if tables_count < len(branch_tables):
            removable_tables = branch_tables[tables_count:]
            for table in removable_tables:
                has_session = db.query(models.TableSession).filter(
                    models.TableSession.table_id == table.id
                ).first()
                if has_session:
                    raise HTTPException(status_code=409, detail="Cannot remove a table with session history")
            for table in removable_tables:
                db.delete(table)
        elif tables_count > len(branch_tables):
            next_number = max((int(table.table_number) for table in branch_tables if table.table_number.isdigit()), default=0) + 1
            for number in range(next_number, next_number + tables_count - len(branch_tables)):
                db.add(models.Table(
                    branch_id=branch.id,
                    table_number=f"{number:02d}",
                    qr_public_id=uuid.uuid4().hex[:12],
                ))
    for key, value in updates.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(branch, key, value)
    db.commit()
    db.refresh(branch)
    return {"success": True, "branch": branch_response(branch, db)}

@app.get("/api/v1/branches/{branch_id}/staff")
def get_branch_staff(branch_id: str, db: Session = Depends(get_db)):
    branch = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    staff = db.query(models.StaffMember).filter(
        models.StaffMember.branch_id == branch.id
    ).order_by(models.StaffMember.name.asc()).all()
    return {"success": True, "staff": [staff_response(member) for member in staff]}

@app.post("/api/v1/branches/{branch_id}/staff")
def create_staff(branch_id: str, data: StaffCreate, db: Session = Depends(get_db)):
    branch = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    allowed_roles = {"Manager", "Chef", "Waiter", "Cashier", "Host"}
    if data.role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Unsupported staff role")
    email = data.email.strip().lower()
    if db.query(models.StaffMember).filter(
        models.StaffMember.branch_id == branch.id,
        models.StaffMember.email == email,
    ).first():
        raise HTTPException(status_code=409, detail="Staff member already exists")
    member = models.StaffMember(
        branch_id=branch.id,
        name=data.name.strip(),
        email=email,
        role=data.role,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return {"success": True, "staff": staff_response(member)}

@app.patch("/api/v1/staff/{staff_id}")
def update_staff(staff_id: str, data: StaffUpdate, db: Session = Depends(get_db)):
    member = db.query(models.StaffMember).filter(models.StaffMember.id == staff_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Staff member not found")
    updates = data.dict(exclude_unset=True)
    if updates.get("role") not in (None, "Manager", "Chef", "Waiter", "Cashier", "Host"):
        raise HTTPException(status_code=400, detail="Unsupported staff role")
    if updates.get("status") not in (None, "ACTIVE", "INACTIVE"):
        raise HTTPException(status_code=400, detail="Unsupported staff status")
    for key, value in updates.items():
        setattr(member, key, value.strip().lower() if key == "email" else value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(member)
    return {"success": True, "staff": staff_response(member)}

# --- 1. SETUP ENDPOINTS (Menu & Tables) ---
@app.post("/api/v1/branches/{branch_id}/categories")
def create_category(branch_id: str, data: CategoryCreate, db: Session = Depends(get_db)):
    branch = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    new_category = models.Category(branch_id=branch.id, name=data.name)
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return {"success": True, "category": {"id": str(new_category.id), "name": new_category.name}}

@app.post("/api/v1/branches/{branch_id}/items")
def create_menu_item(branch_id: str, data: MenuItemCreate, db: Session = Depends(get_db)):
    new_item = models.MenuItem(
        branch_id=branch_id, category_id=data.category_id, 
        name=data.name, description=data.description, image_url=data.image_url, price=data.price
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return {"success": True, "item": {"id": str(new_item.id), "name": new_item.name, "price": new_item.price, "image_url": new_item.image_url}}

@app.post("/api/v1/branches/{branch_id}/tables")
def create_table(branch_id: str, data: TableCreate, db: Session = Depends(get_db)):
    qr_id = uuid.uuid4().hex[:12]
    new_table = models.Table(branch_id=branch_id, table_number=data.table_number, capacity=data.capacity, qr_public_id=qr_id)
    db.add(new_table)
    db.commit()
    db.refresh(new_table)
    return {"success": True, "table": {
        "id": str(new_table.id),
        "table_number": new_table.table_number,
        "qr_id": qr_id,
        "qr_public_id": qr_id,
    }}

@app.get("/api/v1/branches/{branch_id}/menu")
def get_branch_menu(branch_id: str, db: Session = Depends(get_db)):
    categories = db.query(models.Category).filter(models.Category.branch_id == branch_id).all()
    menu_data = []
    for cat in categories:
        items = db.query(models.MenuItem).filter(models.MenuItem.category_id == cat.id).all()
        menu_data.append({
            "category_id": str(cat.id),
            "category_name": cat.name,
            "items": [{
                "id": str(i.id),
                "name": i.name,
                "description": i.description,
                "image_url": i.image_url,
                "price": i.price,
                "is_available": i.is_available,
            } for i in items]
        })
    return {"success": True, "menu": menu_data}

@app.patch("/api/v1/branches/{branch_id}/items/{item_id}/availability")
def update_menu_item_availability(
    branch_id: str,
    item_id: str,
    data: MenuAvailabilityUpdate,
    db: Session = Depends(get_db),
):
    item = db.query(models.MenuItem).filter(
        models.MenuItem.id == item_id,
        models.MenuItem.branch_id == branch_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    item.is_available = data.is_available
    db.commit()
    return {"success": True, "item_id": str(item.id), "is_available": item.is_available}

@app.get("/api/v1/branches/{branch_id}/tables")
def get_branch_tables(branch_id: str, db: Session = Depends(get_db)):
    tables = db.query(models.Table).filter(
        models.Table.branch_id == branch_id
    ).order_by(models.Table.table_number).all()
    return {
        "success": True,
        "tables": [{
            "id": str(table.id),
            "table_number": table.table_number,
            "capacity": table.capacity,
            "status": table.status.value,
            "is_active": table.is_active,
            "qr_public_id": table.qr_public_id,
        } for table in tables],
    }

# --- 2. OPERATIONAL ENDPOINTS (Sessions, Orders, Billing) ---

@app.post("/api/v1/public/sessions")
def create_or_join_session(data: SessionCreate, db: Session = Depends(get_db)):
    table = db.query(models.Table).filter(models.Table.qr_public_id == data.qr_public_id).first()
    if not table:
        raise HTTPException(status_code=404, detail="Invalid QR Code")
    
    branch = db.query(models.Branch).filter(models.Branch.id == table.branch_id).first()
    
    active_session = db.query(models.TableSession).filter(
        models.TableSession.table_id == table.id,
        models.TableSession.status == "OPEN"
    ).first()
    
    if active_session:
        return {
            "success": True,
            "session_id": str(active_session.id),
            "branch_id": str(branch.id),
            "table_id": str(table.id),
            "table_number": table.table_number,
            "message": "Joined existing session",
        }
        
    new_session = models.TableSession(
        restaurant_id=branch.restaurant_id,
        branch_id=branch.id,
        table_id=table.id,
        session_code=uuid.uuid4().hex[:6].upper()
    )
    table.status = "OCCUPIED"
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return {
        "success": True,
        "session_id": str(new_session.id),
        "branch_id": str(branch.id),
        "table_id": str(table.id),
        "table_number": table.table_number,
        "session_code": new_session.session_code,
    }

@app.post("/api/v1/public/orders")
def place_order(data: OrderCreate, db: Session = Depends(get_db)):
    session = db.query(models.TableSession).filter(models.TableSession.id == data.table_session_id).first()
    if not session or session.status != "OPEN":
        raise HTTPException(status_code=400, detail="Invalid or closed session")
    if data.table_id and str(session.table_id) != data.table_id:
        raise HTTPException(status_code=400, detail="Table does not match session")
        
    total = 0.0
    order_items_to_add = []
    
    for item_data in data.items:
        menu_item = db.query(models.MenuItem).filter(models.MenuItem.id == item_data.menu_item_id).first()
        if not menu_item or not menu_item.is_available:
            raise HTTPException(status_code=404, detail=f"Menu item unavailable")
            
        line_total = menu_item.price * item_data.quantity
        total += line_total
        
        order_items_to_add.append(models.OrderItem(
            menu_item_id=menu_item.id,
            name_snapshot=menu_item.name,
            unit_price_snapshot=menu_item.price,
            quantity=item_data.quantity,
            notes=item_data.notes
        ))
        
    new_order = models.Order(
        restaurant_id=session.restaurant_id,
        branch_id=session.branch_id,
        table_session_id=session.id,
        order_number=f"ORD-{uuid.uuid4().hex[:6].upper()}",
        total=total
    )
    db.add(new_order)
    db.flush()
    
    for oi in order_items_to_add:
        oi.order_id = new_order.id
        db.add(oi)
        
    new_kds_ticket = models.KdsTicket(
        branch_id=session.branch_id,
        order_id=new_order.id
    )
    db.add(new_kds_ticket)
    db.commit()
    return {
        "success": True,
        "order_id": str(new_order.id),
        "order_number": new_order.order_number,
        "total": total,
        "status": new_order.status.value,
    }

@app.get("/api/v1/branches/{branch_id}/orders")
def get_branch_orders(
    branch_id: str,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    query = db.query(models.Order).filter(models.Order.branch_id == branch_id)
    if active_only:
        query = query.filter(models.Order.status.notin_(
            [models.OrderStatus.DELIVERED, models.OrderStatus.CANCELLED, models.OrderStatus.VOIDED]
        ))
    orders = query.order_by(models.Order.created_at.desc()).all()
    response_orders = []
    for order in orders:
        session = db.query(models.TableSession).filter(
            models.TableSession.id == order.table_session_id
        ).first()
        table = db.query(models.Table).filter(
            models.Table.id == session.table_id
        ).first() if session else None
        items = db.query(models.OrderItem).filter(
            models.OrderItem.order_id == order.id
        ).all()
        response_orders.append({
            "id": str(order.id),
            "order_number": order.order_number,
            "status": order.status.value,
            "table_id": str(table.id) if table else None,
            "table_number": table.table_number if table else "",
            "total": order.total,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "items": [{
                "id": str(item.id),
                "menu_item_id": str(item.menu_item_id),
                "image_url": db.query(models.MenuItem.image_url).filter(
                    models.MenuItem.id == item.menu_item_id
                ).scalar(),
                "name": item.name_snapshot,
                "quantity": item.quantity,
                "unit_price": item.unit_price_snapshot,
                "notes": item.notes,
            } for item in items],
        })
    return {"success": True, "orders": response_orders}

@app.get("/api/v1/public/sessions/{session_id}/orders")
def get_session_orders(session_id: str, db: Session = Depends(get_db)):
    session = db.query(models.TableSession).filter(
        models.TableSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    orders = db.query(models.Order).filter(
        models.Order.table_session_id == session.id
    ).order_by(models.Order.created_at.asc()).all()
    response_orders = []
    for order in orders:
        items = db.query(models.OrderItem).filter(
            models.OrderItem.order_id == order.id
        ).all()
        response_orders.append({
            "id": str(order.id),
            "order_number": order.order_number,
            "status": order.status.value,
            "table_id": str(session.table_id),
            "table_number": db.query(models.Table.table_number).filter(
                models.Table.id == session.table_id
            ).scalar() or "",
            "total": order.total,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "items": [{
                "id": str(item.id),
                "menu_item_id": str(item.menu_item_id),
                "image_url": db.query(models.MenuItem.image_url).filter(
                    models.MenuItem.id == item.menu_item_id
                ).scalar(),
                "name": item.name_snapshot,
                "quantity": item.quantity,
                "unit_price": item.unit_price_snapshot,
                "notes": item.notes,
            } for item in items],
        })
    return {"success": True, "orders": response_orders}

@app.patch("/api/v1/orders/{order_id}/status")
def update_order_status(
    order_id: str,
    data: OrderStatusUpdate,
    db: Session = Depends(get_db),
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    allowed_statuses = {
        models.OrderStatus.NEW,
        models.OrderStatus.ACCEPTED,
        models.OrderStatus.PREPARING,
        models.OrderStatus.READY,
        models.OrderStatus.DELIVERED,
        models.OrderStatus.CANCELLED,
    }
    if data.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Unsupported order status")
    order.status = data.status
    db.commit()
    db.refresh(order)
    return {
        "success": True,
        "order_id": str(order.id),
        "order_number": order.order_number,
        "status": order.status.value,
    }

@app.post("/api/v1/public/bills")
@app.post("/api/v1/bills")
def generate_bill(data: BillCreate, db: Session = Depends(get_db)):
    session = db.query(models.TableSession).filter(models.TableSession.id == data.table_session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    orders = db.query(models.Order).filter(models.Order.table_session_id == session.id).all()
    subtotal = sum(o.total for o in orders)
    
    existing_bill = db.query(models.Bill).filter(models.Bill.table_session_id == session.id).first()
    if existing_bill:
        existing_bill.subtotal = subtotal
        existing_bill.total = subtotal
        db.commit()
        return {
            "success": True,
            "bill_id": str(existing_bill.id),
            "bill_number": existing_bill.bill_number,
            "subtotal": existing_bill.subtotal,
            "tax": existing_bill.tax,
            "total": existing_bill.total,
            "status": existing_bill.status.value,
        }
        
    new_bill = models.Bill(
        restaurant_id=session.restaurant_id,
        table_session_id=session.id,
        bill_number=f"BILL-{uuid.uuid4().hex[:6].upper()}",
        subtotal=subtotal,
        total=subtotal,
        status="REQUESTED"
    )
    db.add(new_bill)
    session.status = "BILL_REQUESTED"
    
    table = db.query(models.Table).filter(models.Table.id == session.table_id).first()
    if table:
        table.status = "BILL_REQUESTED"
        
    db.commit()
    db.refresh(new_bill)
    return {
        "success": True,
        "bill_id": str(new_bill.id),
        "bill_number": new_bill.bill_number,
        "subtotal": new_bill.subtotal,
        "tax": new_bill.tax,
        "total": new_bill.total,
        "status": new_bill.status.value,
    }

@app.get("/api/v1/public/sessions/{session_id}/bill")
def get_session_bill(session_id: str, db: Session = Depends(get_db)):
    session = db.query(models.TableSession).filter(
        models.TableSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    bill = db.query(models.Bill).filter(
        models.Bill.table_session_id == session.id
    ).first()
    if not bill:
        return {"success": True, "bill": None}
    return {
        "success": True,
        "bill": {
            "bill_id": str(bill.id),
            "bill_number": bill.bill_number,
            "subtotal": bill.subtotal,
            "tax": bill.tax,
            "total": bill.total,
            "status": bill.status.value,
        },
    }

@app.post("/api/v1/sessions/{session_id}/close")
def close_session(session_id: str, data: PaymentCreate, db: Session = Depends(get_db)):
    session = db.query(models.TableSession).filter(models.TableSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    bill = db.query(models.Bill).filter(models.Bill.table_session_id == session.id).first()
    if not bill:
        raise HTTPException(status_code=400, detail="Bill not generated yet")
        
    new_payment = models.Payment(
        bill_id=bill.id,
        method=data.method,
        amount=data.amount
    )
    db.add(new_payment)
    
    bill.status = "PAID"
    session.status = "CLOSED"
    
    table = db.query(models.Table).filter(models.Table.id == session.table_id).first()
    if table:
        table.status = "AVAILABLE"
        
    db.commit()
    return {"success": True, "message": "Payment recorded, session closed, and table is now Available"}

# --- 3. SUPER ADMIN & RESTAURANT STATUS ENDPOINTS ---

# Get Restaurant Status & Details for Frontend Verification Check
@app.get("/api/v1/restaurants/status/{user_id}")
def get_restaurant_status(user_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.clerk_user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    restaurant = db.query(models.Restaurant).filter(models.Restaurant.owner_user_id == user.id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    branch = db.query(models.Branch).filter(
        models.Branch.restaurant_id == restaurant.id
    ).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
        
    return {
        "success": True,
        "restaurant_id": str(restaurant.id),
        "branch_id": str(branch.id),
        "branch_name": branch.name,
        "status": restaurant.status,
        "onboarding_complete": bool((restaurant.settings_json or {}).get("onboarding_complete", False)),
        "name": restaurant.name,
        "address": restaurant.address,
        "city": restaurant.city,
        "logo_url": restaurant.logo_url
    }

# Super Admin: Activate a Pending Restaurant
@app.get("/api/v1/super-admin/restaurants")
def get_platform_restaurants(db: Session = Depends(get_db)):
    restaurants = db.query(models.Restaurant).order_by(models.Restaurant.created_at.desc()).all()
    response = []
    for restaurant in restaurants:
        branches = db.query(models.Branch).filter(
            models.Branch.restaurant_id == restaurant.id
        ).all()
        table_count = sum(
            db.query(models.Table).filter(models.Table.branch_id == branch.id).count()
            for branch in branches
        )
        subscription = db.query(models.Subscription).filter(
            models.Subscription.restaurant_id == restaurant.id
        ).first()
        plan = db.query(models.Plan).filter(
            models.Plan.id == subscription.plan_id
        ).first() if subscription else None
        response.append({
            "id": str(restaurant.id),
            "name": restaurant.name,
            "city": restaurant.city or "",
            "plan": plan.name if plan else "Unassigned",
            "monthly_price": plan.price_monthly if plan else 0,
            "status": restaurant.status or "PENDING",
            "tables": table_count,
        })
    return {"success": True, "restaurants": response}

@app.get("/api/v1/super-admin/audit-logs")
def get_platform_audit_logs(db: Session = Depends(get_db)):
    entries = db.query(models.AuditLog).order_by(
        models.AuditLog.created_at.desc()
    ).limit(100).all()
    return {
        "success": True,
        "audit_logs": [{
            "id": str(entry.id),
            "action": entry.action,
            "actor": str(entry.actor_user_id) if entry.actor_user_id else "System",
            "target": f"{entry.entity_type} {entry.entity_id or ''}".strip(),
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        } for entry in entries],
    }

@app.get("/api/v1/health")
def health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"success": True, "api": "operational", "database": "operational"}

@app.put("/api/v1/super-admin/restaurants/{restaurant_id}/activate")
def activate_restaurant(restaurant_id: str, db: Session = Depends(get_db)):
    restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    
    restaurant.status = "ACTIVE"
    db.commit()
    return {"success": True, "message": "Restaurant activated successfully by Super Admin"}

# --- 4. SETTINGS & PROFILE UPDATES ---

@app.put("/api/v1/restaurants/{restaurant_id}")
def update_restaurant(restaurant_id: str, data: RestaurantUpdate, db: Session = Depends(get_db)):
    restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    
    for key, value in data.dict(exclude_unset=True).items():
        setattr(restaurant, key, value)
        
    db.commit()
    db.refresh(restaurant)
    return {
        "success": True, 
        "restaurant": {
            "id": str(restaurant.id), 
            "name": restaurant.name, 
            "currency": restaurant.currency,
            "address": restaurant.address,
            "city": restaurant.city,
            "logo_url": restaurant.logo_url,
            "status": restaurant.status
        }
    }

@app.post("/api/v1/tables/{table_id}/toggle")
def toggle_table_status(
    table_id: str,
    data: Optional[TableStatusUpdate] = None,
    db: Session = Depends(get_db),
):
    table = db.query(models.Table).filter(models.Table.id == table_id).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    
    if data and data.status:
        table.status = data.status
        table.is_active = data.status != models.TableStatus.OUT_OF_SERVICE
    else:
        table.is_active = not table.is_active
        if not table.is_active:
            table.status = models.TableStatus.OUT_OF_SERVICE
        elif table.status == models.TableStatus.OUT_OF_SERVICE:
            table.status = models.TableStatus.AVAILABLE
    db.commit()
    
    status_msg = "Unfrozen (Active)" if table.is_active else "Frozen (Inactive)"
    return {
        "success": True,
        "is_active": table.is_active,
        "status": table.status.value,
        "message": f"Table QR is now {status_msg}",
    }