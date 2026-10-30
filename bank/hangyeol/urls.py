from django.urls import path

from core import api, views

urlpatterns = [
    path("", views.index, name="index"),
    path("health", views.health, name="health"),
    path("robots.txt", api.robots, name="robots"),
    path("admin-old", api.admin_old, name="admin_old"),
    path("api/v1/docs", api.docs, name="api_docs"),
    path("api/v1/customers", api.customers, name="customers"),
    path("api/v1/login", api.login, name="login"),
    path("api/v1/password-reset", api.password_reset, name="password_reset"),
    path("api/v1/chat", api.chat, name="chat"),
]
