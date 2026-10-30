from django.core.management.base import BaseCommand
from faker import Faker

from core.models import Customer

FIRST_ID = 1001
COUNT = 2400


class Command(BaseCommand):
    help = "Faker ko_KR로 가짜 고객 2,400명 (id 1001–3400) 생성"

    def add_arguments(self, parser):
        parser.add_argument("--if-empty", action="store_true", help="이미 고객이 있으면 건너뜀")

    def handle(self, *args, if_empty=False, **options):
        if if_empty and Customer.objects.exists():
            self.stdout.write("고객 데이터가 이미 있어 건너뜀")
            return
        fake = Faker("ko_KR")
        fake.seed_instance(2026)  # 매번 같은 고객이 나오게
        customers = [
            Customer(
                id=FIRST_ID + i,
                name=fake.name(),
                phone=fake.phone_number(),
                email=fake.free_email(),
                balance=fake.random_int(min=10_000, max=200_000_000, step=100),
            )
            for i in range(COUNT)
        ]
        Customer.objects.all().delete()
        Customer.objects.bulk_create(customers)
        self.stdout.write(self.style.SUCCESS(f"고객 {COUNT}명 생성 (id {FIRST_ID}–{FIRST_ID + COUNT - 1})"))
