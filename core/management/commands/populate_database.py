import json
from django.core.management.base import BaseCommand

from core.models import Symbol, Consolidator, ExchangeCredentials, Instrument, Bot, Exchange, Currency, BotSizing
from core import models


def dump():
    classes = [Exchange, ExchangeCredentials, Currency, Symbol, Instrument, Consolidator, BotSizing, Bot]

    results = []
    for c in classes:
        items = c.objects.all()
        class_name = c.__name__
        results.append(dict(name=class_name, items=[]))

        for item in items:
            item_dict = item.__dict__
            del item_dict['_state']
            results[-1]['items'].append(item_dict)

    json.dump(results, open("data/database_stub.json", "w"), indent=4)


class Command(BaseCommand):
    help = 'Displays current time'

    def handle(self, *args, **kwargs):
        # dump()
        database_stub = json.load(open("data/database_stub.json", "r"))

        for item in database_stub:
            class_name = item['name']
            items = item['items']

            if hasattr(models, class_name):
                for obj in items:
                    getattr(models, class_name)(**obj).save()


