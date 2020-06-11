import os
import json
import time

from joblib import Parallel, delayed
from django.core.management.base import BaseCommand
from django.conf import settings

from core.models import Consolidator
from core.libs.data_feed.consolidation_from_ticks import TickToTimeframeConsolidator, BackfillProxyApi
from core.libs.helpers.tick_rest_stream import TickApiProxy

import logging
logging.basicConfig()
logging.getLogger().setLevel(settings.LOG_LEVEL)


exchange_names_to_slug = {
    "bitfinex": "bfnx"
}


def consolidate(
        feed_id,
        exchange,
        instrument_class,
        base, quote, custom_kwargs
):
    logging.debug(
        f"""
        consolidate api: 
            KAIKO_API_KEY: {bool(settings.KAIKO_API_KEY)}
            feed_id: {feed_id}
            exchange: {exchange}
            instrument_class: {instrument_class} {base}/{quote} **{custom_kwargs}
        """)

    backfill_api = BackfillProxyApi(api=TickApiProxy(
        kaiko_api_params=dict(api_key=settings.KAIKO_API_KEY)
    ))

    time_frame_seconds = custom_kwargs['time_frame_seconds']

    cons = TickToTimeframeConsolidator(
        exchange, instrument_class,
        base, quote, time_frame_seconds, f"{settings.BARS_DIRECTORY}/{feed_id}.h5",
        backfill_api=backfill_api,
        dataset_flush_auto=False
    )
    has_new_bars, latest_bar_data = cons.backfill(
        until_timestamp=time.time() // time_frame_seconds * time_frame_seconds, one_batch_only=True)
    cons.dataset_flush()

    return {
        "feed_id": feed_id,
        "has_new_bars": has_new_bars,
        "latest_bar_data": latest_bar_data
    }


class Command(BaseCommand):
    help = 'Consolidate TickToTimeFrame consolidators'

    def handle(self, *args, **kwargs):
        while True:
            try:
                # fetch consolidators without parents (means "consolidate from raw ticks")
                consolidators = Consolidator.objects.all().filter(parent__isnull=True, is_active=True)
                jobs = []
                for cons in consolidators:
                    if cons.type == "TIME":
                        time_frame_seconds = cons.get_kwargs()['time_frame_seconds']
                        if cons.update_timestamp // time_frame_seconds + 1 < time.time() // time_frame_seconds:
                            jobs.append(dict(
                                feed_id=cons.id,
                                exchange=cons.instrument.exchange.slug,  # Bitfinex exchange
                                base=cons.instrument.symbol.base.slug.lower(),
                                quote=cons.instrument.symbol.quote.slug.lower(),
                                custom_kwargs=json.loads(cons.kwargs),
                                instrument_class=cons.instrument.kaiko_type.lower(),  # Spot market
                            ))

                # TODO: dedicated process per instrument, to prevent blocking on new instrument history fetch

                if jobs:
                    # run consolidation jobs in parallel
                    resps = Parallel(n_jobs=1, verbose=0)(
                        delayed(consolidate)(**job) for job in jobs
                    )

                    for feed_resp in resps:
                        if feed_resp['has_new_bars']:
                            # for each job response handle new bar only
                            c = Consolidator.objects.get(id=feed_resp['feed_id'])
                            c.new_bars_event(feed_resp['latest_bar_data'])
            except Exception as ex:
                logging.exception("Tick consolidation unhandled exception")
               
            time.sleep(1)
