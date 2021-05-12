import datetime
from typing import Optional

import numpy as np
import pandas as pd
from django.views.generic import ListView, DetailView, FormView
from django.db.models import Count, Sum, Q
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Owner, ExchangeCredentials
from .forms import RebatesForm
from .services import df_from_list, StatisticsCalculator


class OwnerUserPermissionFilterMixin:
    def filter_by_user(self, queryset):
        if not self.request.user.is_staff:
            filters_params = {
                Owner: {'user': self.request.user},
                ExchangeCredentials: {'owner__user': self.request.user},
            }
            queryset = queryset.filter(**(filters_params[self.model]))
        return queryset


class BotStatisticListView(OwnerUserPermissionFilterMixin, LoginRequiredMixin, ListView):
    model = Owner
    template_name = 'bot_statistic/list.html'
    context_object_name = 'owners'

    def get_queryset(self):
        is_active_condition = dict(
            filter=(Q(bot__is_active=True) if 'active_bots' in self.request.GET else {})
        )
        return self.filter_by_user(
            Owner
            .objects
            .annotate(
                total_equity=Sum(
                    'bot__botstatistic__equity',
                    **is_active_condition
                ),
                bots_count=Count(
                    'bot',
                    **is_active_condition
                )
            )
            .filter(bots_count__gte=1)
        )


class ExchangeBalancesListView(OwnerUserPermissionFilterMixin, LoginRequiredMixin, ListView):
    model = Owner
    template_name = 'bot_balance/list.html'
    context_object_name = 'owners'

    def get_queryset(self):
        q = self.filter_by_user(
            Owner
            .objects
            .filter(exchangecredentials__visible=True)
            .distinct()
            .order_by('order_id', 'name')
        )
        return q.all()


class ExchangeBalancesDetailView(OwnerUserPermissionFilterMixin, LoginRequiredMixin, DetailView):
    model = ExchangeCredentials
    template_name = 'bot_balance/detail.html'
    context_object_name = 'creds'

    def get_queryset(self):
        return self.filter_by_user(super().get_queryset())


class RebatesView(LoginRequiredMixin, FormView):
    form_class = RebatesForm
    template_name = 'rebate/detail.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({
            'data': self.request.GET
        })
        return kwargs

    def get(self, request, *args, **kwargs):
        if not request.GET:
            return super().get(request, *args, **kwargs)
        return self.post(request, *args, **kwargs)

    @staticmethod
    def combine_datetime(
        date: Optional[datetime.date],
        time: Optional[datetime.time],
        start: bool = True
    ) -> Optional[datetime.datetime]:
        if not date:
            return None

        if not time:
            time = datetime.time(0, 0) if start else datetime.time(23, 59)

        return datetime.datetime.combine(date, time)

    @classmethod
    def filter_df_by_get_dt(cls, df: pd.DataFrame, form: RebatesForm) -> pd.DataFrame:
        start = cls.combine_datetime(form.cleaned_data.get('start_date'), form.cleaned_data.get('start_time'))
        end = cls.combine_datetime(form.cleaned_data.get('end_date'), form.cleaned_data.get('end_time'), start=False)

        if not len(df):
            return df

        if start and end:
            return df[(df.timestamp >= np.datetime64(start)) & (df.timestamp <= np.datetime64(end))]

        if start:
            return df[df.timestamp >= np.datetime64(start)]

        if end:
            return df[df.timestamp <= np.datetime64(end)]

        return df

    def form_valid(self, form: RebatesForm):
        exchange_credentials: ExchangeCredentials = form.cleaned_data['exchange_credentials']
        rebates = self.filter_df_by_get_dt(
            df_from_list(
                (exchange_credentials.statistics or {}).get('rebates', [])
            ),
            form
        )

        context = {}
        if len(rebates):
            context['rebates_data'] = {
                symbol: StatisticsCalculator.aggregate_rebates_and_calculate_summary(df, form.cleaned_data['timeframe'])
                for symbol, df in StatisticsCalculator.df_dict_group(rebates, 'symbol').items()
            }
        context.update({'form': form, 'exchange_credentials': exchange_credentials})
        return self.render_to_response(context)
