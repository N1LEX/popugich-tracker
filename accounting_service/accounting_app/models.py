from datetime import date
from uuid import uuid4

from django.db import models
from django.db.models import QuerySet
from django.utils.functional import cached_property


class User(models.Model):
    class RoleChoices(models.TextChoices):
        ADMIN = 'admin', 'admin'
        MANAGER = 'manager', 'manager'
        TESTER = 'tester', 'tester'
        DEVELOPER = 'developer', 'developer'
        ACCOUNTANT = 'accountant', 'accountant'

    public_id = models.UUIDField()
    username = models.CharField(max_length=40)
    role = models.CharField(max_length=40)
    full_name = models.CharField(max_length=40, blank=True, null=True)
    email = models.CharField(max_length=40, null=True, blank=True)

    @property
    def is_manager(self) -> bool:
        return self.role in (self.RoleChoices.ADMIN, self.RoleChoices.MANAGER)

    @property
    def is_worker(self) -> bool:
        return self.role in (self.RoleChoices.TESTER, self.RoleChoices.DEVELOPER, self.RoleChoices.ACCOUNTANT)

    @staticmethod
    def workers() -> QuerySet:
        return User.objects.exclude(role__in=(User.RoleChoices.ADMIN, User.RoleChoices.MANAGER))

    @cached_property
    def billing_cycle(self) -> 'BillingCycle':
        return self.billing_cycles.filter(status=BillingCycle.StatusChoices.OPENED).last()

    def __str__(self):
        return self.username


class Task(models.Model):

    class StatusChoices(models.TextChoices):
        CREATED = 'created', 'created'
        ASSIGNED = 'assigned', 'assigned'
        COMPLETED = 'completed', 'completed'

    public_id = models.UUIDField()
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tasks')
    description = models.CharField(max_length=255)
    assigned_price = models.PositiveSmallIntegerField()
    completed_price = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=40)
    date = models.DateField()

    class Meta:
        ordering = ['-id']

    @classmethod
    def create(cls, task_model) -> 'Task':
        return cls.objects.create(
            public_id=task_model.public_id,
            user=User.objects.get(public_id=task_model.user_id),
            description=task_model.description,
            assigned_price=task_model.assigned_price,
            completed_price=task_model.completed_price,
            status=task_model.status,
            date=task_model.date,
        )


class BillingCycle(models.Model):
    class StatusChoices(models.TextChoices):
        OPENED = 'opened', 'opened'
        CLOSED = 'closed', 'closed'

    public_id = models.UUIDField(default=uuid4)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='billing_cycles')
    start_date = models.DateField(default=date.today)
    end_date = models.DateField(default=date.today)
    status = models.CharField(max_length=6, default=StatusChoices.OPENED)

    @classmethod
    def new(cls, user: User, start: date = None, end: date = None) -> 'BillingCycle':
        return cls.objects.create(user=user, start_date=start, end_date=end)

    def close(self):
        self.status = self.StatusChoices.CLOSED
        self.save()


class Account(models.Model):
    public_id = models.UUIDField(default=uuid4)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    balance = models.IntegerField(default=0)

    def create_transaction(self, transaction_model) -> 'Transaction':
        transaction = Transaction.objects.create(
            public_id=transaction_model.public_id,
            account=self,
            billing_cycle=self.user.billing_cycle,
            type=transaction_model.type,
            debit=transaction_model.debit,
            credit=transaction_model.credit,
            purpose=transaction_model.purpose,
            datetime=transaction_model.datetime,
        )
        if transaction.type in (transaction.TypeChoices.WITHDRAW, transaction.TypeChoices.PAYMENT):
            self.balance += -transaction.credit
        else:
            self.balance -= transaction.debit
        self.save()
        return transaction


class Transaction(models.Model):
    class TypeChoices(models.TextChoices):
        DEPOSIT = 'deposit', 'deposit'
        WITHDRAW = 'withdraw', 'withdraw'
        PAYMENT = 'payment', 'payment'

    public_id = models.UUIDField(default=uuid4, unique=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='transactions')
    billing_cycle = models.ForeignKey(BillingCycle, on_delete=models.PROTECT, related_name='transactions')
    type = models.CharField(max_length=8, choices=TypeChoices.choices)
    debit = models.PositiveIntegerField(default=0)
    credit = models.PositiveIntegerField(default=0)
    purpose = models.CharField(max_length=100)
    datetime = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
