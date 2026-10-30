from django.urls import path

from core import pages, views

urlpatterns = [
    path("", views.index, name="index"),
    path("health", views.health, name="health"),
    path("login", pages.login_view, name="login"),
    path("logout", pages.logout_view, name="logout"),
    path("account", pages.account, name="account"),
    path("support", pages.support, name="support"),
    path("api/v1/chat", pages.chat, name="chat"),
]
