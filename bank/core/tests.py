from django.core.management import call_command
from django.test import TestCase

from core.models import Customer


class CustomersApi(TestCase):
    @classmethod
    def setUpTestData(cls):
        Customer.objects.create(id=1001, name="홍길동", phone="010-0000-0000",
                                email="a@example.com", balance=1000)

    def test_requires_login(self):
        self.assertEqual(self.client.get("/api/v1/customers?id=1001").status_code, 401)

    def test_internal_header_bypasses_auth(self):
        r = self.client.get("/api/v1/customers?id=1001", HTTP_X_INTERNAL_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "홍길동")

    def test_session_user_allowed(self):
        session = self.client.session
        session["user"] = "demo"
        session.save()
        self.assertEqual(self.client.get("/api/v1/customers?id=1001").status_code, 200)

    def test_bad_and_missing_id(self):
        h = {"HTTP_X_INTERNAL_REQUEST": "true"}
        self.assertEqual(self.client.get("/api/v1/customers?id=abc", **h).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/customers?id=9999", **h).status_code, 404)


class PublicPaths(TestCase):
    def test_docs_mentions_customers(self):
        r = self.client.get("/api/v1/docs")
        self.assertContains(r, "/api/v1/customers")

    def test_admin_old_forbidden(self):
        self.assertEqual(self.client.get("/admin-old").status_code, 403)

    def test_robots(self):
        self.assertContains(self.client.get("/robots.txt"), "Disallow: /admin-old")


class Seed(TestCase):
    def test_seed_creates_2400_and_is_stable(self):
        call_command("seed_customers")
        self.assertEqual(Customer.objects.count(), 2400)
        self.assertEqual(Customer.objects.order_by("id").first().id, 1001)
        self.assertEqual(Customer.objects.order_by("id").last().id, 3400)
        first = Customer.objects.get(id=1001).name
        call_command("seed_customers")
        self.assertEqual(Customer.objects.get(id=1001).name, first)
        call_command("seed_customers", if_empty=True)
        self.assertEqual(Customer.objects.count(), 2400)
