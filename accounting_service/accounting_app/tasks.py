from datetime import timedelta, date

import attrs
from celery import shared_task
from django.db import transaction

from accounting_app.models import User, Task, Account, BillingCycle, Transaction
from accounting_app.serializers import SerializerNames, SERIALIZERS
from accounting_app.streaming import EventStreaming
from accounting_service.celery import app


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 5})
@transaction.atomic
def create_user(_, event):
    event_version = event['event_version']
    user_model = SERIALIZERS[event_version][SerializerNames.USER](**event['data'])
    user = User.objects.create(**attrs.asdict(user_model))
    if user.is_worker:
        BillingCycle.new(user=user, start=date.today(), end=date.today())
        account = Account.objects.create(user=user)
        account_serializer = SERIALIZERS[event_version][SerializerNames.ACCOUNT]
        event_streaming = EventStreaming(event_version)
        event_streaming.account_created(account_serializer.from_object(account))


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 5})
@transaction.atomic
def handle_created_task(_, event):
    event_version = event['event_version']

    event_streaming = EventStreaming(event_version)
    task_serializer = SERIALIZERS[event_version][SerializerNames.TASK]
    task_model = task_serializer(**event['data'])
    task = Task.create(task_model)

    transaction_serializer = SERIALIZERS[event_version][SerializerNames.TRANSACTION]
    transaction_model = transaction_serializer(
        account_id=task.user.account.public_id,
        billing_cycle_id=task.user.billing_cycle.public_id,
        type=Transaction.TypeChoices.WITHDRAW,
        credit=task.assigned_price,
        purpose=f'Withdraw for a assigned task #{task.public_id}',
    )
    task.user.account.create_transaction(transaction_model)

    event_streaming.transaction_created(transaction_model)
    event_streaming.task_updated(task_serializer.from_object(task))

    account_serializer = SERIALIZERS[event_version][SerializerNames.ACCOUNT]
    event_streaming.account_updated(account_serializer.from_object(task.user.account))


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 5})
@transaction.atomic
def handle_assigned_task(_, event):
    event_version = event['event_version']

    task_serializer = SERIALIZERS[event_version][SerializerNames.TASK]
    task_model = task_serializer(**event['data'])
    task = Task.objects.get(public_id=task_model.public_id)

    task.user_id = task_model.user_id
    task.save(update_fields=['user'])

    transaction_serializer = SERIALIZERS[event_version][SerializerNames.TRANSACTION]
    transaction_model = transaction_serializer(
        account_id=task.user.account.public_id,
        billing_cycle_id=task.user.billing_cycle.public_id,
        type=Transaction.TypeChoices.WITHDRAW,
        credit=task.assigned_price,
        purpose=f'Withdraw for a assigned task #{task.public_id}',
    )
    task.user.account.create_transaction(transaction_model)

    event_streaming = EventStreaming(event_version)
    event_streaming.transaction_created(transaction_model)

    account_serializer = SERIALIZERS[event_version][SerializerNames.ACCOUNT]
    event_streaming.account_updated(account_serializer.from_object(task.user.account))


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 5})
@transaction.atomic
def handle_completed_task(_, event):
    event_version = event['event_version']

    task_serializer = SERIALIZERS[event_version][SerializerNames.TASK]
    task_model = task_serializer(**event['data'])
    task = Task.objects.get(public_id=task_model.public_id)

    transaction_serializer = SERIALIZERS[event_version][SerializerNames.TRANSACTION]
    transaction_model = transaction_serializer(
        account_id=task.user.account.public_id,
        billing_cycle_id=task.user.billing_cycle.public_id,
        type=Transaction.TypeChoices.DEPOSIT,
        debit=task.completed_price,
        purpose=f'Deposit for a completed task #{task.public_id}',
    )
    task.user.account.create_transaction(transaction_model)

    event_streaming = EventStreaming(event_version)
    event_streaming.transaction_created(transaction_model)

    account_serializer = SERIALIZERS[event_version][SerializerNames.ACCOUNT]
    event_streaming.account_updated(account_serializer.from_object(task.user.account))


@app.task
def close_billing_cycles(event_version: str):
    for user in User.workers():
        close_billing_cycle.delay(user.id, event_version)


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 5})
@transaction.atomic
def close_billing_cycle(_, user_id: int, event_version: str):
    send_report = False
    user = User.objects.get(id=user_id)
    account = user.account
    payment_amount = account.balance

    if account.balance > 0:
        send_report = True
        transaction_serializer = SERIALIZERS[event_version][SerializerNames.TRANSACTION]
        transaction_model = transaction_serializer(
            account_id=user.account.public_id,
            billing_cycle_id=user.billing_cycle.public_id,
            type=Transaction.TypeChoices.PAYMENT,
            credit=payment_amount,
            purpose='Payout for completed tasks',
        )
        account.create_transaction(transaction_model)
        event_streaming = EventStreaming(event_version)
        event_streaming.transaction_created(transaction_model)

    user.billing_cycle.close()
    next_cycle_date = user.billing_cycle.end_date + timedelta(days=1)
    BillingCycle.new(user=user, start=next_cycle_date, end=next_cycle_date)

    if send_report:
        send_payout_report.delay(user.email, payment_amount)


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 10})
def send_payout_report(_, email, amount):
    return {
        'from': 'accounting@popug.inc',
        'to': email,
        'subject': 'Payout for completed tasks',
        'message': amount,
    }
