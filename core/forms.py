from django import forms

from .models import ExchangeCredentials

TIMEFRAMES = [('1H', '1H'), ('1D', '1D'), ('1W', '1W'), ('1M', '1M')]
DATETIME_LOCAL_WIDGET = forms.DateTimeInput(attrs={'type': 'datetime-local'})


class RebatesForm(forms.Form):
    exchange_credentials = forms.ModelChoiceField(queryset=ExchangeCredentials.objects.all())
    timeframe = forms.ChoiceField(choices=TIMEFRAMES, initial=TIMEFRAMES[0])
    start = forms.DateTimeField(widget=DATETIME_LOCAL_WIDGET, required=False)
    end = forms.DateTimeField(widget=DATETIME_LOCAL_WIDGET, required=False)
