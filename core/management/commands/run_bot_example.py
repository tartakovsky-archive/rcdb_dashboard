import joblib
import time
import ccxt

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Bot, BotSignal
from core.libs.data_feed.functions import get_bot_feed_dataframe
from core.libs.helpers.features import get_calc_features_fn


def get_feature_config():
    from rcdb_libs.job_manager import km, t, col
    import numpy_ext as npext
    from rcdb_libs import features as ft

    diff_step = npext.expstep_range(1, 30, min_step=1, step_mult=1.1).astype(int)

    config = dict(
        price=[
            dict(
                alias='change',
                fn=ft.misc.frac_change,
                pg=km(step=diff_step),
                dm=km(series=['close']),
                tr=[t.symlog()]
            ),
        ],
        timediff=[
            dict(
                alias='itself',
                fn=ft.misc.diff,
                pg=km(step=diff_step),
                dm=km(series=['timestamp']),
                tr=[t.symlog()]
            ),
        ],
    )

    return config


def train_model(X, y, bot_id):
    from rcdb_research.models import LGBMClassifierEnsemble
    common_config = dict(
        n_estimators=200,
        learning_rate=0.03,
        max_depth=12,
        num_leaves=80,
        bagging_fraction=0.1,
        feature_fraction=1,
        bagging_freq=1,
        n_jobs=4,
    )

    clf = LGBMClassifierEnsemble(common_config, n_seeds=5)
    model = clf.fit(X, y)
    joblib.dump(model, f'data/models/bot_{bot_id}--{int(time.time())}.model')
    return model


def get_model():
    import joblib
    m = joblib.load(f'data/models/prod_model.joblib')
    return m


@transaction.atomic
def transaction__predict_and_push_signal(bot_id, model, features_fn):
    bot = Bot.objects.get(id=bot_id)
    bot_signal_latest = BotSignal.get_active(bot)

    bot_signal = None
    if bot_signal_latest is None or \
            bot.data_feed.update_timestamp > bot_signal_latest.timestamp_consolidator:
        # new bar exists, should be executed
        bars = get_bot_feed_dataframe(bot=bot, rows_count=101)
        X, y, X_to_predict = features_fn(bars)
        y_pred = model.predict_proba(X_to_predict)
        # as long as X_to_predict is 1 bar only
        signal = y_pred[0][1]
        bot_signal = BotSignal.push_signal(bot, signal)
    return bot_signal


def clean_database(bot):
    bot.botperformancelog_set.all().delete()
    bot.botorderlog_set.all().delete()
    bot.botpositionlog_set.all().delete()
    bot.bottargetstate_set.all().delete()
    bot.botsignal_set.all().delete()


class Command(BaseCommand):
    help = 'Displays current time'

    def handle(self, *args, **kwargs):
        BOT_ID = 6

        bot = Bot.objects.get(id=BOT_ID)
        BAR_SIZE = bot.data_feed.get_kwargs()['bar_size']

        if not bot.is_active:
            return

        clean_database(bot)

        for b in Bot.objects.filter(parent=bot):
            clean_database(b)

        features_fn = get_calc_features_fn(get_feature_config())

        # bars = get_bot_feed_dataframe(bot=Bot.objects.get(id=BOT_ID), rows_count=None)
        # datasets = add_noise_to_dataset(bars, noise_levels=np.linspace(BAR_SIZE*0.01, BAR_SIZE*0.1, 10))
        #
        # X, y, X_to_predict = features_fn(bars)
        # for df in datasets:
        #     df_X, df_y, _ = features_fn(df)
        #     X = X.append(df_X)
        #     y = y.append(df_y)
        #
        # m = train_model(X, y, bot.id)

        m = get_model()

        while True:
            try:
                bot_signal = transaction__predict_and_push_signal(bot_id=BOT_ID, model=m, features_fn=features_fn)
            except (ccxt.base.errors.RequestTimeout):
                pass
            print("Bot signal: ", bot_signal)
            time.sleep(2)
