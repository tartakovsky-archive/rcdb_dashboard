from django.shortcuts import get_object_or_404
from ninja import NinjaAPI

from . import models, schemas

api = NinjaAPI()


@api.get("/bot/{id}", response=schemas.Bot)
def get_bot_config(request, id: int):
    return get_object_or_404(models.Bot, pk=id)
