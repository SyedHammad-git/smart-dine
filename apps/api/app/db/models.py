import uuid
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.db.database import Base

# --- ENUMS (PRD ke mutabiq Statuses) ---
class TableStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    BILL_REQUESTED = "BILL_REQUESTED"
    SETTLING = "SETTLING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"

class SessionStatus(str, enum.Enum):
    OPEN = "OPEN"
    BILL_REQUESTED = "BILL_REQUESTED"
    SETTLING = "SETTLING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"

class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"

class BillStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    REQUESTED = "REQUESTED"
    OPEN = "OPEN"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"

# --- CORE PLATFORM & TENANT MODELS ---
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clerk_user_id = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    status = Column(String, default="ACTIVE")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Restaurant(Base):
    __tablename__ = "restaurants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clerk_org_id = Column(String, unique=True, index=True, nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="PENDING")
    currency = Column(String(3), default="PKR")
    timezone = Column(String, default="Asia/Karachi")
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    settings_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    branches = relationship("Branch", back_populates="restaurant")

class Branch(Base):
    __tablename__ = "branches"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False)
    status = Column(String, default="ACTIVE")
    address = Column(String, nullable=True)
    contact = Column(String, nullable=True)
    manager_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    restaurant = relationship("Restaurant", back_populates="branches")
    tables = relationship("Table", back_populates="branch")

class StaffMember(Base):
    __tablename__ = "staff_members"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    role = Column(String, nullable=False)
    status = Column(String, default="ACTIVE")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- FLOOR, TABLES & SESSIONS ---
class Table(Base):
    __tablename__ = "tables"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    table_number = Column(String, nullable=False)
    qr_public_id = Column(String, unique=True, nullable=False) # Permanent QR identity
    capacity = Column(Integer, default=4)
    status = Column(SQLEnum(TableStatus), default=TableStatus.AVAILABLE)
    is_active = Column(Boolean, default=True)
    
    branch = relationship("Branch", back_populates="tables")

class TableSession(Base):
    __tablename__ = "table_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    table_id = Column(UUID(as_uuid=True), ForeignKey("tables.id"), nullable=False)
    session_code = Column(String, unique=True, nullable=False)
    status = Column(SQLEnum(SessionStatus), default=SessionStatus.OPEN)
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)

class GuestSession(Base):
    __tablename__ = "guest_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_session_id = Column(UUID(as_uuid=True), ForeignKey("table_sessions.id"), nullable=False)
    guest_token_hash = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

# --- MENU MANAGEMENT ---
class Category(Base):
    __tablename__ = "menu_categories"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    name = Column(String, nullable=False)
    sort_order = Column(Integer, default=0)
    status = Column(String, default="ACTIVE")

class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("menu_categories.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    is_available = Column(Boolean, default=True)

class MenuModifier(Base):
    __tablename__ = "menu_modifiers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    menu_item_id = Column(UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False)
    name = Column(String, nullable=False) # e.g., "Extra Toppings"
    min_select = Column(Integer, default=0)
    max_select = Column(Integer, default=1)

class MenuModifierOption(Base):
    __tablename__ = "menu_modifier_options"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    modifier_id = Column(UUID(as_uuid=True), ForeignKey("menu_modifiers.id"), nullable=False)
    label = Column(String, nullable=False) # e.g., "Cheese"
    price_delta = Column(Float, default=0.0)
    active = Column(Boolean, default=True)

# --- ORDERS & KDS ---
class Order(Base):
    __tablename__ = "orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    table_session_id = Column(UUID(as_uuid=True), ForeignKey("table_sessions.id"), nullable=False)
    order_number = Column(String, nullable=False)
    source = Column(String, default="CUSTOMER_QR") # CUSTOMER_QR or STAFF_ASSISTED
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.NEW)
    total = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False)
    name_snapshot = Column(String, nullable=False)
    unit_price_snapshot = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)

class KdsTicket(Base):
    __tablename__ = "kds_tickets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, unique=True)
    status = Column(String, default="NEW")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- BILLING ---
class Bill(Base):
    __tablename__ = "bills"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    table_session_id = Column(UUID(as_uuid=True), ForeignKey("table_sessions.id"), nullable=False, unique=True)
    bill_number = Column(String, nullable=False)
    subtotal = Column(Float, default=0.0)
    tax = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    status = Column(SQLEnum(BillStatus), default=BillStatus.DRAFT)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Payment(Base):
    __tablename__ = "payments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bill_id = Column(UUID(as_uuid=True), ForeignKey("bills.id"), nullable=False)
    method = Column(String, nullable=False) # CASH, CARD
    amount = Column(Float, nullable=False)
    status = Column(String, default="COMPLETED")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- SUPER ADMIN & SAAS PLATFORM MODELS ---
class Plan(Base):
    __tablename__ = "plans"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    price_monthly = Column(Float, nullable=False)
    max_branches = Column(Integer, default=1)
    max_tables = Column(Integer, default=20)
    status = Column(String, default="ACTIVE")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    status = Column(String, default="TRIAL") # TRIAL, ACTIVE, PAST_DUE, CANCELLED
    current_period_end = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=True)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False) # e.g., "FROZE_QR_CODE", "CANCELLED_ORDER"
    entity_type = Column(String, nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id = Column(UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False)
    subject = Column(String, nullable=False)
    status = Column(String, default="OPEN") # OPEN, IN_PROGRESS, RESOLVED
    created_at = Column(DateTime(timezone=True), server_default=func.now())