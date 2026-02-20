"""
SQLAlchemy ORM Entities for DealFinder
Based on database schema from Bauplan IDEE 5
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Index,
    UniqueConstraint,
    UUID,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from uuid import uuid4


class Base(DeclarativeBase):
    pass


class User(Base):
    """User entity with GDPR support"""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email = Column(String(255), unique=True, nullable=False)
    email_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)
    gdpr_consent_given = Column(Boolean, default=False)
    gdpr_consent_date = Column(DateTime, nullable=True)

    # Relationships
    filters = relationship(
        "DealFilter", back_populates="user", cascade="all, delete-orphan"
    )
    clicks = relationship("DealClick", back_populates="user")
    deletion_requests = relationship("GdprDeletionRequest", back_populates="user")


class DealFilter(Base):
    """Deal filter configuration entity"""

    __tablename__ = "deal_filters"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(100), nullable=False)

    # Filter Configuration (JSON for flexibility)
    categories = Column(JSON, default=list)
    price_range = Column(JSON, default={"min": 0, "max": 10000, "currency": "EUR"})
    discount_range = Column(JSON, default={"min": 0, "max": 100})
    min_rating = Column(Numeric(3, 1), default=Decimal("4.0"))
    min_review_count = Column(Integer, default=10)
    max_sales_rank = Column(Integer, default=100000)

    # Schedule
    email_enabled = Column(Boolean, default=True)
    email_schedule = Column(
        JSON,
        default={
            "time": "06:00",
            "timezone": "Europe/Berlin",
            "days": ["MON", "TUE", "WED", "THU", "FRI"],
        },
    )

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Relationships
    user = relationship("User", back_populates="filters")
    reports = relationship(
        "DealReport", back_populates="filter", cascade="all, delete-orphan"
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="unique_user_filter_name"),
        Index("idx_filters_user_active", "user_id", "is_active"),
        Index("idx_filters_email_enabled", "email_enabled", "is_active"),
    )


class Deal(Base):
    """Deal/product entity"""

    __tablename__ = "deals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    asin = Column(String(10), nullable=False)
    domain = Column(String(10), nullable=False)
    title = Column(String(500), nullable=False)
    category = Column(String(100))

    # Pricing
    current_price = Column(Numeric(10, 2), nullable=False)
    original_price = Column(Numeric(10, 2))
    discount_percent = Column(Integer)

    # Quality Metrics
    rating = Column(Numeric(3, 1))
    review_count = Column(Integer)
    sales_rank = Column(Integer)

    # Metadata
    amazon_url = Column(String(500))
    image_url = Column(String(500))
    seller_name = Column(String(100))
    is_amazon_seller = Column(Boolean)

    # Freshness
    last_updated = Column(DateTime, default=datetime.utcnow)

    # Relationships
    snapshots = relationship(
        "DealSnapshot", back_populates="deal", cascade="all, delete-orphan"
    )

    # Constraints - unique ASIN per domain
    __table_args__ = (
        UniqueConstraint("asin", "domain", name="unique_asin_per_domain"),
        Index("idx_deals_rating", "rating"),
        Index("idx_deals_sales_rank", "sales_rank"),
        Index("idx_deals_discount", "discount_percent"),
        Index("idx_deals_category", "category"),
        Index("idx_deals_updated", "last_updated"),
        Index("idx_deals_asin", "asin"),
    )


class DealSnapshot(Base):
    """Scored deal snapshot entity"""

    __tablename__ = "deal_snapshots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    asin = Column(String(10), nullable=False)
    domain = Column(String(10), nullable=False)

    # Deal Score
    deal_score = Column(Numeric(5, 2))
    score_breakdown = Column(JSON)

    # Spam Detection
    spam_flag = Column(Boolean, default=False)
    spam_reason = Column(String(255))

    # Freshness
    created_at = Column(DateTime, default=datetime.utcnow)
    valid_until = Column(DateTime, nullable=True)

    # Relationships
    deal = relationship("Deal", back_populates="snapshots")

    # Indexes
    __table_args__ = (
        Index("idx_snapshots_asin_domain", "asin", "domain"),
        Index("idx_snapshots_asin_created", "asin", "created_at"),
        Index("idx_snapshots_score", "deal_score"),
    )


class DealReport(Base):
    """Generated deal report entity"""

    __tablename__ = "deal_reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    filter_id = Column(
        String(36),
        ForeignKey("deal_filters.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Report Content
    deals = Column(JSON, default=list)
    deal_count = Column(Integer, default=0)
    generated_at = Column(DateTime, default=datetime.utcnow)

    # Delivery
    email_sent_at = Column(DateTime, nullable=True)
    email_status = Column(String(20), default="PENDING")
    email_message_id = Column(String(255))

    # Analytics
    open_count = Column(Integer, default=0)
    click_count = Column(Integer, default=0)

    # Relationships
    filter = relationship("DealFilter", back_populates="reports")
    clicks = relationship("DealClick", back_populates="report")
    opens = relationship("ReportOpen", back_populates="report")

    # Indexes
    __table_args__ = (
        Index("idx_reports_filter_time", "filter_id", "generated_at"),
        Index("idx_reports_email_status", "email_status"),
    )


class DealClick(Base):
    """Deal click tracking entity"""

    __tablename__ = "deal_clicks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    report_id = Column(String(36), ForeignKey("deal_reports.id"), nullable=False)
    asin = Column(String(10), nullable=False)

    clicked_at = Column(DateTime, default=datetime.utcnow)
    utm_source = Column(String(50))
    utm_medium = Column(String(50))

    # Relationships
    user = relationship("User", back_populates="clicks")
    report = relationship("DealReport", back_populates="clicks")

    # Indexes
    __table_args__ = (
        Index("idx_clicks_user_asin", "user_id", "asin"),
        Index("idx_clicks_report", "report_id"),
        Index("idx_clicks_time", "clicked_at"),
    )


class ReportOpen(Base):
    """Email open tracking entity"""

    __tablename__ = "report_opens"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    report_id = Column(String(36), ForeignKey("deal_reports.id"), nullable=False)

    opened_at = Column(DateTime, default=datetime.utcnow)
    user_agent = Column(String(255))
    ip_address = Column(String(50))

    # Relationships
    report = relationship("DealReport", back_populates="opens")

    # Indexes
    __table_args__ = (
        Index("idx_opens_report", "report_id"),
        Index("idx_opens_time", "opened_at"),
    )


class KeepaApiLog(Base):
    """Keepa API logging entity"""

    __tablename__ = "keepa_api_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    api_key_hash = Column(String(64))
    endpoint = Column(String(50))
    status_code = Column(Integer)
    request_params = Column(JSON)
    response_summary = Column(JSON)
    error_message = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index("idx_keepa_status", "status_code"),
        Index("idx_keepa_time", "created_at"),
    )


class GdprConsentLog(Base):
    """GDPR consent logging entity"""

    __tablename__ = "gdpr_consent_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    consent_type = Column(String(20))
    given = Column(Boolean)
    ip_address = Column(String(50))
    user_agent = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Indexes
    __table_args__ = (Index("idx_consent_user", "user_id", "consent_type"),)


class GdprDeletionRequest(Base):
    """GDPR deletion request entity"""

    __tablename__ = "gdpr_deletion_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    requested_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    delete_personal_data = Column(Boolean, default=True)
    delete_reports = Column(Boolean, default=True)
    delete_analytics = Column(Boolean, default=False)

    status = Column(String(20), default="PENDING")

    # Relationships
    user = relationship("User", back_populates="deletion_requests")

    # Indexes
    __table_args__ = (Index("idx_deletion_status", "status"),)
