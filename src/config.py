"""
DealFinder Configuration Loader
Environment-based configuration with .env support
"""

import os
from pathlib import Path
from functools import lru_cache
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    debug: bool = False
    log_level: str = "INFO"

    # Keepa API
    keepa_api_key: str = Field(default="", validation_alias="KEEPA_API_KEY")

    # Database
    database_url: str = Field(
        default="postgresql://dealfinder:dealfinder_secret@localhost:5432/dealfinder_db",
        validation_alias="DATABASE_URL",
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0", validation_alias="REDIS_URL"
    )

    # RabbitMQ
    rabbitmq_url: str = Field(
        default="amqp://localhost:5672/", validation_alias="RABBITMQ_URL"
    )

    # Deal scanning
    deal_scan_interval_seconds: int = Field(
        default=300, validation_alias="DEAL_SCAN_INTERVAL_SECONDS"
    )
    deal_scan_batch_size: int = Field(
        default=50, validation_alias="DEAL_SCAN_BATCH_SIZE"
    )
    deal_source_mode: str = Field(
        default="product_only", validation_alias="DEAL_SOURCE_MODE"
    )
    deal_seed_asins: str = Field(default="", validation_alias="DEAL_SEED_ASINS")
    deal_targets_file: str = Field(
        default="data/seed_targets_core_qwertz.csv",
        validation_alias="DEAL_TARGETS_FILE",
    )
    deal_seed_file: str = Field(
        default="data/seed_asins_eu_qwertz.json",
        validation_alias="DEAL_SEED_FILE",
    )

    kafka_bootstrap_servers: str = Field(
        default="localhost:9092",
        validation_alias="KAFKA_BOOTSTRAP_SERVERS",
    )

    # Email
    sendgrid_api_key: Optional[str] = Field(
        default=None, validation_alias="SENDGRID_API_KEY"
    )
    from_email: str = Field(
        default="deals@dealfinder.app", validation_alias="FROM_EMAIL"
    )

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Convenience accessors
def get_keepa_api_key() -> str:
    return get_settings().keepa_api_key


def get_database_url() -> str:
    return get_settings().database_url


def get_redis_url() -> str:
    return get_settings().redis_url


def get_rabbitmq_url() -> str:
    return get_settings().rabbitmq_url
