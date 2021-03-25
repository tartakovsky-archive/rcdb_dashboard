import os

import jwt
from ninja import NinjaAPI
from ninja.errors import HttpError
from ninja.openapi import views as oa_views
from ninja.security import HttpBearer, django_auth
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.contrib.auth import models as auth_models

from . import models, schemas

os.environ['NINJA_SKIP_REGISTRY'] = '1'


class AuthBearer(HttpBearer):
    def authenticate(self, request, token):
        if self.validate_payload(self.decode_token(token)):
            return token

    @staticmethod
    def validate_payload(payload: dict) -> bool:
        return (
            auth_models.User
            .objects
            .filter(
                id=(payload or {}).get('id'),
                is_active=True
            )
            .exists()
        )

    @staticmethod
    def encode_token(user: auth_models.User) -> str:
        return jwt.encode({'id': user.id}, settings.SECRET_KEY, algorithm='HS256')

    @staticmethod
    def decode_token(token: str) -> dict:
        return jwt.decode(token, settings.SECRET_KEY, algorithms='HS256')


api = NinjaAPI(auth=django_auth, csrf=True, docs_url=None, openapi_url=None)


@api.get('/bot/{id}', auth=AuthBearer(), response=schemas.Bot, description='Returns bot config by id')
def get_bot_config(request, id: int):
    return get_object_or_404(models.Bot, pk=id)


@api.get('/auth-token', response=schemas.CredentialData, description='Returns auth token for API')
def get_auth_token(request):
    if not request.user.is_anonymous and request.user.is_active:
        return schemas.CredentialData(
            access_token=AuthBearer.encode_token(request.user)
        )
    raise HttpError(401, 'Bad request')


@api.get('', tags=['Documentation'])
def get_protected_docs(request):
    return oa_views.swagger_cdn(
        request,
        {
            "api": api,
            "openapi_json_url": '/api/openapi.json',
        }
    )


@api.get('/openapi.json', tags=['Documentation'])
def get_protected_openapi(request):
    return oa_views.openapi_json(request, api)
