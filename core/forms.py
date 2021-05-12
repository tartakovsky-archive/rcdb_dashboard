import datetime
from typing import Optional

from django import forms

from .models import ExchangeCredentials

TIMEFRAMES = [('1H', '1H'), ('1D', '1D'), ('1W', '1W'), ('1M', '1M')]
DATETIME_LOCAL_WIDGET = forms.DateTimeInput(attrs={'type': 'datetime-local', 'value': '2021-05-12T00:00:00'})


class ExchangeCredentialsChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: ExchangeCredentials):
        return f'{obj.name} | {obj.account_type_label} | {obj.label}'


def current_utc_date(replacement: Optional[dict] = None) -> datetime.datetime:
    now = datetime.datetime.utcnow()
    if replacement:
        now = now.replace(**replacement)

    return now


class RebatesForm(forms.Form):
    exchange_credentials = ExchangeCredentialsChoiceField(
        label='Exchange credentials',
        queryset=ExchangeCredentials.objects.all()
    )
    timeframe = forms.ChoiceField(label='Timeframe', choices=TIMEFRAMES, initial=TIMEFRAMES[0])
    start = forms.DateTimeField(
        label='Start date and time',
        widget=DATETIME_LOCAL_WIDGET,
        required=False
    )
    end = forms.DateTimeField(
        label='End date and time',
        widget=DATETIME_LOCAL_WIDGET,
        required=False
    )

    def __init__(self, *args, **kwargs):
        super(RebatesForm, self).__init__(*args, **kwargs)
        self.fields['start'].widget.attrs['value'] = current_utc_date(
            {'hour': 0, 'minute': 0, 'second': 0, 'microsecond': 0}
        ).isoformat()
        self.fields['end'].widget.attrs['value'] = current_utc_date(
            {'hour': 23, 'minute': 59, 'second': 0, 'microsecond': 0}
        ).isoformat()
