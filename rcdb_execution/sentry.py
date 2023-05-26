import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration


IGNORED_STRINGS = [
    'Django can only handle ASGI/HTTP connections, not lifespan.',
    'System is under maintenance',
    'Timeout waiting for response from backend server',
    'RequestTimeout',
    'ExchangeNotAvailable'
]


def before_send(event, hint):
    check_strings = set()
    if hint.get('log_record'):
        check_strings.add(hint.get('log_record').msg)

    if 'exc_info' in hint:
        _, exc_value, _ = hint['exc_info']
        check_strings.add(str(exc_value))

    if check_strings and any(
        ignore_pattern in check_string
        for ignore_pattern in IGNORED_STRINGS
        for check_string in check_strings
    ):
        return None
    return event


def init_sentry(dsn):
    if dsn:
        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                DjangoIntegration(),
                CeleryIntegration()
            ],
            before_send=before_send,
            traces_sample_rate=0.
        )
        print('Sentry enabled', dsn)
    else:
        print('Sentry disabled')
