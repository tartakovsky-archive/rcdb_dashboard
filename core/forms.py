import datetime

from django import forms

from .models import ExchangeCredentials

TIMEFRAMES = [('1H', '1H'), ('1D', '1D'), ('1W', '1W'), ('1M', '1M')]


class ExchangeCredentialsChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: ExchangeCredentials):
        return f'{obj.name} | {obj.account_type_label} | {obj.label}'


class RebatesForm(forms.Form):
    exchange_credentials = ExchangeCredentialsChoiceField(
        label='Exchange credentials',
        queryset=ExchangeCredentials.objects.all()
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
