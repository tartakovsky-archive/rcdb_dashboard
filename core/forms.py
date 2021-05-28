import datetime
from typing import Optional

from django import forms
from django.db.models import TextChoices
from django.core.exceptions import ValidationError

from .models import ExchangeCredentials

TIMEFRAMES = [('H', '1H'), ('D', '1D'), ('W', '1W'), ('M', '1M')]


class ReportType(TextChoices):
    BY_ACCOUNT = 'BY_ACCOUNT', 'By Account'
    OVERALL = 'OVERALL', 'Overall'


class RebateCurrency(TextChoices):
    ALL = 'ALL', 'All'
    EUR = 'EUR', 'EUR'
    GBP = 'GBP', 'GBP'
    BRL = 'BRL', 'BRL'
    TRY = 'TRY', 'TRY'
    RUB = 'RUB', 'RUB'
    UAH = 'UAH', 'UAH'
    AUD = 'AUD', 'AUD'


class ExchangeCredentialsLabelMixin:
    def label_from_instance(self, obj: ExchangeCredentials):
        return f'{obj.name} | {obj.account_type_label} | {obj.label}'


class ExchangeCredentialsChoiceField(ExchangeCredentialsLabelMixin, forms.ModelChoiceField):
    pass


class ExchangeCredentialsMultipleChoiceField(ExchangeCredentialsLabelMixin, forms.ModelMultipleChoiceField):
    pass


class RebatesForm(forms.Form):
    type = forms.ChoiceField(label='Type', choices=ReportType.choices, initial=ReportType.BY_ACCOUNT.value)
    exchange_credentials = ExchangeCredentialsChoiceField(
        label='Exchange credentials',
        queryset=ExchangeCredentials.objects.all(),
        required=False
    )
    excluded_exchange_credentials = ExchangeCredentialsMultipleChoiceField(
        queryset=ExchangeCredentials.objects.all(),
        widget=forms.CheckboxSelectMultiple(),
        required=False
    )
    currencies = forms.MultipleChoiceField(
        choices=RebateCurrency.choices,
        widget=forms.CheckboxSelectMultiple(),
        required=True
    )
    timeframe = forms.ChoiceField(label='Timeframe', choices=TIMEFRAMES, initial=TIMEFRAMES[0])
    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), required=False)
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False)
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), required=False)
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), required=False)

    def __init__(self, *args, **kwargs):
        super(RebatesForm, self).__init__(*args, **kwargs)
        now = datetime.datetime.utcnow()
        self.fields['start_date'].widget.attrs['value'] = now.date().isoformat()
        self.fields['start_time'].widget.attrs['value'] = datetime.time(0, 0).isoformat()

        self.fields['end_date'].widget.attrs['value'] = now.date().isoformat()
        self.fields['end_time'].widget.attrs['value'] = datetime.time(23, 59).isoformat()

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('exchange_credentials') and cleaned_data.get('type') == ReportType.BY_ACCOUNT.value:
            raise ValidationError('exchange_credentials should be selected when used BY_ACCOUNT')
        return cleaned_data

    @property
    def start(self) -> Optional[datetime.datetime]:
        return self.combine_datetime(
            self.cleaned_data.get('start_date'),
            self.cleaned_data.get('start_time')
        )

    @property
    def end(self) -> Optional[datetime.datetime]:
        return self.combine_datetime(
            self.cleaned_data.get('end_date'),
            self.cleaned_data.get('end_time'),
            start=False
        )

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
