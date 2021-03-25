import os

from celery import Celery
from django.conf import settings

from .sentry import init_sentry


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rcdb_execution.settings')
celery = Celery('rcdb_execution')
celery.autodiscover_tasks()
celery.config_from_object("django.conf:settings", namespace="CELERY")

init_sentry(settings.SENTRY_DSN)
