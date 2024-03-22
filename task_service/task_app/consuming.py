import json

from confluent_kafka import Consumer, Message
from django.db.models import TextChoices

from task_app.tasks import create_user


class Topics(TextChoices):
    USER_STREAM = 'user-stream'


EVENT_HANDLERS = {
    Topics.USER_STREAM: {
        'created': create_user,
    }
}


class KafkaConsumer:

    def __init__(self):
        self.consumer = Consumer({'bootstrap.servers': 'kafka:29092', 'group.id': 'task-tracker'})
        self.consumer.subscribe(Topics.values)

    def consume(self):
        try:
            while True:
                try:
                    msg: Message = self.consumer.poll(1)
                    if msg is None: continue
                    if msg.error():
                        # TODO requeue msg back to topic?
                        print(msg.error().code())
                    print(msg.topic(), msg.key(), msg.value())
                    topic, key, event = msg.topic(), msg.key().decode('utf-8'), json.loads(msg.value())
                    print(topic, key, event)
                    handler = EVENT_HANDLERS[topic][key]
                    print(handler)
                    handler.delay(event)
                except Exception as e:
                    print(str(e))
        finally:
            self.consumer.close()