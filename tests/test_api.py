import json
from importlib import resources

import pytest

from core import models

use_db = pytest.mark.django_db


@pytest.fixture
def auth_client(client, django_user_model):
    username = "user1"
    password = "bar"
    user = django_user_model.objects.create_user(username=username, password=password, is_active=True)
    client.force_login(user)
    yield client


@pytest.fixture
def auth_client_token(auth_client):
    auth_client.defaults = {
        **auth_client.defaults,
        'HTTP_Authorization': f'Bearer {auth_client.get("/api/auth-token").json()["access_token"]}'
    }
    yield auth_client


@use_db
def test_token_auth(auth_client):
    response = auth_client.get('/api/auth-token')
    assert response.json() == {
        'access_token': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpZCI6MX0.EX8vUmWssJATfjhZ7f6gT3sq1sN3wXKdlNWUo0yD6kw',
        'token_type': 'bearer'
    }


@use_db
def test_get_bot_config_not_found(auth_client_token):
    response = auth_client_token.get('/api/bot/1')
    assert response.status_code == 404


@use_db
def test_get_bot_config(auth_client_token, bot: models.Bot):
    response = auth_client_token.get(f'/api/bot/{bot.id}')
    assert response.json() == {
        **json.load(resources.open_text('tests.datasets', 'bot_config_response.json')),
        'bot_id': bot.id
    }


@use_db
@pytest.mark.parametrize('url', ['/api/bot/1', '/api/exchange-credentials'])
def test_auth_unauth_user(auth_client, url):
    response = auth_client.get(url)
    assert response.status_code == 401


@use_db
def test_get_exchange_credentials(auth_client_token, bot: models.Bot):
    models.ExchangeCredentials(
        owner=bot.exchange_credentials.owner,
        exchange=bot.instrument.exchange,
        name='Empty parameters',
        parameters=None
    ).save()
    response = auth_client_token.get('/api/exchange-credentials')
    assert models.ExchangeCredentials.objects.count() == 2
    assert tuple(response.json()) == (
        {'exchange': {'name': 'binance', 'slug': 'binance'}, 'name': 'Creds', 'label': '', 'parameters': {'some': 1}},
    )
