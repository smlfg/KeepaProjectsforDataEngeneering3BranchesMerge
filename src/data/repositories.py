"""
Repository Layer for DealFinder
Implements CRUD operations for all entities
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, update, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.data.entities import (
    User,
    DealFilter,
    Deal,
    DealSnapshot,
    DealReport,
    DealClick,
    ReportOpen,
    GdprConsentLog,
    GdprDeletionRequest,
)


class UserRepository:
    """Repository for User operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, email: str) -> User:
        """Create a new user"""
        user = User(email=email)
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID"""
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def update_consent(self, user_id: UUID, consent_given: bool) -> User:
        """Update GDPR consent"""
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                gdpr_consent_given=consent_given,
                gdpr_consent_date=datetime.utcnow() if consent_given else None,
            )
        )
        return await self.get_by_id(user_id)

    async def soft_delete(self, user_id: UUID) -> bool:
        """Soft delete user (GDPR)"""
        await self.session.execute(
            update(User).where(User.id == user_id).values(deleted_at=datetime.utcnow())
        )
        return True


class FilterRepository:
    """Repository for DealFilter operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: UUID,
        name: str,
        categories: list,
        price_min: float,
        price_max: float,
        discount_min: int,
        discount_max: int,
        min_rating: float,
        min_review_count: int,
        max_sales_rank: int,
        email_enabled: bool = True,
        email_time: str = "06:00",
    ) -> DealFilter:
        """Create a new deal filter"""
        filter_obj = DealFilter(
            user_id=user_id,
            name=name,
            categories=categories,
            price_range={"min": price_min, "max": price_max, "currency": "EUR"},
            discount_range={"min": discount_min, "max": discount_max},
            min_rating=min_rating,
            min_review_count=min_review_count,
            max_sales_rank=max_sales_rank,
            email_enabled=email_enabled,
            email_schedule={
                "time": email_time,
                "timezone": "Europe/Berlin",
                "days": ["MON", "TUE", "WED", "THU", "FRI"],
            },
        )
        self.session.add(filter_obj)
        await self.session.flush()
        return filter_obj

    async def get_by_id(self, filter_id: UUID) -> Optional[DealFilter]:
        """Get filter by ID"""
        result = await self.session.execute(
            select(DealFilter)
            .options(selectinload(DealFilter.user))
            .where(DealFilter.id == filter_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self, user_id: UUID, active_only: bool = True
    ) -> List[DealFilter]:
        """Get all filters for a user"""
        query = select(DealFilter).where(DealFilter.user_id == user_id)
        if active_only:
            query = query.where(DealFilter.is_active == True)
        query = query.order_by(DealFilter.created_at.desc())

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_active_for_scheduling(self) -> List[DealFilter]:
        """Get all active filters for scheduled email sending"""
        today = datetime.utcnow().strftime("%a").upper()
        result = await self.session.execute(
            select(DealFilter)
            .options(selectinload(DealFilter.user))
            .where(and_(DealFilter.is_active == True, DealFilter.email_enabled == True))
        )
        filters = result.scalars().all()

        # Filter by today's day
        filtered = []
        for f in filters:
            schedule = f.email_schedule or {}
            days = schedule.get("days", [])
            if today in days or not days:
                filtered.append(f)

        return filtered

    async def update(
        self,
        filter_id: UUID,
        name: Optional[str] = None,
        categories: Optional[list] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        discount_min: Optional[int] = None,
        discount_max: Optional[int] = None,
        min_rating: Optional[float] = None,
        email_enabled: Optional[bool] = None,
        email_time: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[DealFilter]:
        """Update filter configuration"""
        updates = {"updated_at": datetime.utcnow()}

        if name is not None:
            updates["name"] = name
        if categories is not None:
            updates["categories"] = categories
        if price_min is not None or price_max is not None:
            current = await self._get_price_range(filter_id)
            updates["price_range"] = {
                "min": price_min if price_min is not None else current["min"],
                "max": price_max if price_max is not None else current["max"],
                "currency": "EUR",
            }
        if discount_min is not None or discount_max is not None:
            current = await self._get_discount_range(filter_id)
            updates["discount_range"] = {
                "min": discount_min if discount_min is not None else current["min"],
                "max": discount_max if discount_max is not None else current["max"],
            }
        if min_rating is not None:
            updates["min_rating"] = min_rating
        if email_enabled is not None:
            updates["email_enabled"] = email_enabled
        if email_time is not None:
            current_schedule = await self._get_email_schedule(filter_id)
            updates["email_schedule"] = {**current_schedule, "time": email_time}
        if is_active is not None:
            updates["is_active"] = is_active

        await self.session.execute(
            update(DealFilter).where(DealFilter.id == filter_id).values(**updates)
        )
        return await self.get_by_id(filter_id)

    async def delete(self, filter_id: UUID) -> bool:
        """Hard delete filter"""
        await self.session.execute(delete(DealFilter).where(DealFilter.id == filter_id))
        return True

    async def deactivate(self, filter_id: UUID) -> bool:
        """Soft delete (deactivate) filter"""
        await self.session.execute(
            update(DealFilter)
            .where(DealFilter.id == filter_id)
            .values(is_active=False, updated_at=datetime.utcnow())
        )
        return True

    async def _get_price_range(self, filter_id: UUID) -> dict:
        """Get current price range for update"""
        result = await self.session.execute(
            select(DealFilter.price_range).where(DealFilter.id == filter_id)
        )
        return result.scalar_one() or {"min": 0, "max": 10000}

    async def _get_discount_range(self, filter_id: UUID) -> dict:
        """Get current discount range for update"""
        result = await self.session.execute(
            select(DealFilter.discount_range).where(DealFilter.id == filter_id)
        )
        return result.scalar_one() or {"min": 0, "max": 100}

    async def _get_email_schedule(self, filter_id: UUID) -> dict:
        """Get current email schedule for update"""
        result = await self.session.execute(
            select(DealFilter.email_schedule).where(DealFilter.id == filter_id)
        )
        return result.scalar_one() or {
            "time": "06:00",
            "timezone": "Europe/Berlin",
            "days": ["MON", "TUE", "WED", "THU", "FRI"],
        }


class DealRepository:
    """Repository for Deal operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, deal_data: dict) -> Deal:
        """Insert or update a deal"""
        asin = deal_data["asin"]
        domain = deal_data.get("domain", "DE")
        result = await self.session.execute(
            select(Deal).where(and_(Deal.asin == asin, Deal.domain == domain))
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing
            for key, value in deal_data.items():
                if value is not None and hasattr(existing, key):
                    setattr(existing, key, value)
            existing.last_updated = datetime.utcnow()
            return existing
        else:
            # Insert new
            deal = Deal(**deal_data)
            self.session.add(deal)
            await self.session.flush()
            return deal

    async def get_by_asin(self, asin: str, domain: str = "DE") -> Optional[Deal]:
        """Get deal by ASIN and domain"""
        result = await self.session.execute(
            select(Deal).where(and_(Deal.asin == asin, Deal.domain == domain))
        )
        return result.scalar_one_or_none()

    async def get_deals_for_filter(
        self,
        categories: list,
        price_min: float,
        price_max: float,
        min_rating: float,
        max_sales_rank: int,
        limit: int = 50,
    ) -> List[Deal]:
        """Get deals matching filter criteria"""
        query = (
            select(Deal)
            .where(
                and_(
                    Deal.category.in_(categories) if categories else True,
                    Deal.current_price >= price_min,
                    Deal.current_price <= price_max,
                    Deal.rating >= min_rating if min_rating else True,
                    Deal.sales_rank <= max_sales_rank if max_sales_rank else True,
                )
            )
            .limit(limit)
        )

        result = await self.session.execute(query)
        return list(result.scalars().all())


class ReportRepository:
    """Repository for DealReport operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, filter_id: UUID, deals: list, deal_count: int) -> DealReport:
        """Create a new report"""
        report = DealReport(filter_id=filter_id, deals=deals, deal_count=deal_count)
        self.session.add(report)
        await self.session.flush()
        return report

    async def get_by_id(self, report_id: UUID) -> Optional[DealReport]:
        """Get report by ID"""
        result = await self.session.execute(
            select(DealReport)
            .options(selectinload(DealReport.filter))
            .where(DealReport.id == report_id)
        )
        return result.scalar_one_or_none()

    async def get_by_filter(self, filter_id: UUID, limit: int = 10) -> List[DealReport]:
        """Get recent reports for a filter"""
        result = await self.session.execute(
            select(DealReport)
            .where(DealReport.filter_id == filter_id)
            .order_by(DealReport.generated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_sent(self, report_id: UUID, message_id: str) -> bool:
        """Mark report as sent"""
        await self.session.execute(
            update(DealReport)
            .where(DealReport.id == report_id)
            .values(
                email_sent_at=datetime.utcnow(),
                email_status="SENT",
                email_message_id=message_id,
            )
        )
        return True

    async def increment_opens(self, report_id: UUID) -> bool:
        """Increment open count"""
        await self.session.execute(
            update(DealReport)
            .where(DealReport.id == report_id)
            .values(open_count=DealReport.open_count + 1)
        )
        return True

    async def increment_clicks(self, report_id: UUID) -> bool:
        """Increment click count"""
        await self.session.execute(
            update(DealReport)
            .where(DealReport.id == report_id)
            .values(click_count=DealReport.click_count + 1)
        )
        return True


class ClickRepository:
    """Repository for DealClick operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: UUID,
        report_id: UUID,
        asin: str,
        utm_source: str = "email",
        utm_medium: str = "deal_link",
    ) -> DealClick:
        """Record a deal click"""
        click = DealClick(
            user_id=user_id,
            report_id=report_id,
            asin=asin,
            utm_source=utm_source,
            utm_medium=utm_medium,
        )
        self.session.add(click)
        await self.session.flush()
        return click

    async def get_user_clicks(self, user_id: UUID, limit: int = 50) -> List[DealClick]:
        """Get recent clicks for a user"""
        result = await self.session.execute(
            select(DealClick)
            .where(DealClick.user_id == user_id)
            .order_by(DealClick.clicked_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class GdprRepository:
    """Repository for GDPR operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_consent(
        self,
        user_id: UUID,
        consent_type: str,
        given: bool,
        ip_address: str = None,
        user_agent: str = None,
    ) -> GdprConsentLog:
        """Log GDPR consent"""
        consent = GdprConsentLog(
            user_id=user_id,
            consent_type=consent_type,
            given=given,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(consent)
        await self.session.flush()
        return consent

    async def create_deletion_request(
        self,
        user_id: UUID,
        delete_personal_data: bool = True,
        delete_reports: bool = True,
        delete_analytics: bool = False,
    ) -> GdprDeletionRequest:
        """Create GDPR deletion request"""
        request = GdprDeletionRequest(
            user_id=user_id,
            delete_personal_data=delete_personal_data,
            delete_reports=delete_reports,
            delete_analytics=delete_analytics,
        )
        self.session.add(request)
        await self.session.flush()
        return request

    async def get_pending_requests(self) -> List[GdprDeletionRequest]:
        """Get all pending deletion requests"""
        result = await self.session.execute(
            select(GdprDeletionRequest)
            .where(GdprDeletionRequest.status == "PENDING")
            .order_by(GdprDeletionRequest.requested_at)
        )
        return list(result.scalars().all())

    async def mark_processed(self, request_id: UUID) -> bool:
        """Mark deletion request as processed"""
        await self.session.execute(
            update(GdprDeletionRequest)
            .where(GdprDeletionRequest.id == request_id)
            .values(status="COMPLETED", processed_at=datetime.utcnow())
        )
        return True
