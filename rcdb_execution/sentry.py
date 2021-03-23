import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.redis import RedisIntegration


def init_sentry(dsn):
    if dsn:
        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                DjangoIntegration(),
                RedisIntegration(),
                CeleryIntegration()
            ],
            traces_sample_rate=0.
        )
        print('Sentry enabled', dsn)
    else:
        print('Sentry disabled')
