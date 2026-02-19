# DealFinder Services
from src.services.keepa_client import (
    KeepaClient,
    get_keepa_client,
    close_keepa_client,
    KeepaApiError,
    KeepaRateLimitError,
    KeepaAuthError,
    KeepaTimeoutError,
    NoDealAccessError,
)
from src.services.deal_scoring import (
    DealScoringService,
    get_deal_scoring_service,
    ScoringResult,
)
from src.services.report_generator import ReportGeneratorService, get_report_generator
from src.services.email_sender import (
    EmailSenderService,
    get_email_sender,
    EmailSendError,
    EmailAuthError,
    EmailRateLimitError,
    EmailSMTPError,
)
from src.services.elasticsearch_service import (
    ElasticsearchService,
    get_elasticsearch_service,
    close_elasticsearch_service,
)

__all__ = [
    "KeepaClient",
    "get_keepa_client",
    "close_keepa_client",
    "KeepaApiError",
    "KeepaRateLimitError",
    "KeepaAuthError",
    "KeepaTimeoutError",
    "DealScoringService",
    "get_deal_scoring_service",
    "ScoringResult",
    "ReportGeneratorService",
    "get_report_generator",
    "EmailSenderService",
    "get_email_sender",
    "EmailSendError",
    "EmailAuthError",
    "EmailRateLimitError",
    "EmailSMTPError",
    "ElasticsearchService",
    "get_elasticsearch_service",
    "close_elasticsearch_service",
]
