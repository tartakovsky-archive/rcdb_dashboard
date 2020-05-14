from django.core.management.base import BaseCommand
from core.models import *


def export_states(bot_id):
    results = []
    states = BotTargetState.objects.filter(bot=bot_id).order_by('id')
    for state in states:
        change_quote_value = 0
        change_base_value = 0
        state_price_avg = None
        orders = state.botorderlog_set.all()
        if orders:
            for o in orders:
                change_quote_value += o.size * o.price_avg
                change_base_value += o.size
            state_price_avg = change_quote_value / change_base_value
        state_positions = state.botpositionlog_set.all().order_by('-id')
        position_size_final = 0
        if state_positions:
            position_size_final = state.botpositionlog_set.all().order_by('-id')[0].size
        data_point = dict(
            timestamp=state.bot_signal.timestamp_consolidator,
            signal=state.bot_signal.signal,
            target_size=state.instrument_target_size,
            target_price=state.instrument_target_execution_price,
            size_avg=change_base_value,
            price_avg=state_price_avg,
            position_size_final=position_size_final
        )
        results.append(data_point)
    res = pd.DataFrame(results)
    res.to_hdf(f"{settings.BASE_DIR}/data/results/bot_results__{bot_id}.hdf", key='table', mode="w")
    print(pd.read_hdf(f"{settings.BASE_DIR}/data/results/bot_results__{bot_id}.hdf", key='table'))


def export_performance(bot_id):
    bot = Bot.objects.get(id=bot_id)
    res = bot.get_performance()

    res.to_hdf(f"{settings.BASE_DIR}/data/results/bot_performance__{bot_id}.hdf", key='table', mode="w")
    print(pd.read_hdf(f"{settings.BASE_DIR}/data/results/bot_performance__{bot_id}.hdf", key='table'))


class Command(BaseCommand):
    help = 'Displays current time'

    def add_arguments(self, parser):
        parser.add_argument('bot_id', type=int)

    def handle(self, *args, **kwargs):
        print(kwargs)
        bot_id = kwargs['bot_id']
        export_states(bot_id)
        export_performance(bot_id)

