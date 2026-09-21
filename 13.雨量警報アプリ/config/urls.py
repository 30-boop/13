from django.urls import path

from alert import views

urlpatterns = [
    path("", views.index, name="index"),
]
