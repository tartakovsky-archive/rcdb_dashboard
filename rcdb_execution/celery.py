import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rcdb_execution.settings')
celery = Celery('rcdb_execution')
celery.autodiscover_tasks()
celery.config_from_object("django.conf:settings", namespace="CELERY")
