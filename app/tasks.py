"""Tasks module for the DESTINY Climate and Health Repository API."""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("tasks", broker=settings.celery_broker_url)
