from django.db import models


class Customer(models.Model):
    """시드로 만드는 가짜 고객. 시연에서는 '실제 데이터' 역할."""

    id = models.IntegerField(primary_key=True)  # 1001–3400
    name = models.CharField(max_length=50)
    phone = models.CharField(max_length=20)
    email = models.CharField(max_length=100)
    balance = models.BigIntegerField()

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "phone": self.phone,
                "email": self.email, "balance": self.balance}
