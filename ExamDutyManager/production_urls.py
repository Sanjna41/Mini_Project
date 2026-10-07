from django.http import HttpResponse
from django.urls import path

from .urls import urlpatterns


def health(request):
    return HttpResponse('ok', content_type='text/plain')


urlpatterns = [path('health', health, name='health')] + urlpatterns
