# Consumers — full example

Reference for rule 7 of `python-message-bus-outbox`. A consumer is an inbound entry point, the broker-side equivalent of a FastAPI route: one class per topic or queue, app-lifetime, one session and service per message.

```python
# app/consumers/order_consumer.py
import structlog
from aiokafka import AIOKafkaConsumer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repos.order import OrderRepo
from app.schemas.events import OrderPlacedEvent
from app.services.fulfillment import FulfillmentService


log = structlog.get_logger(__name__)


class OrderConsumer:
    def __init__(
        self,
        *,
        kafka: AIOKafkaConsumer,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._kafka = kafka
        self._session_factory = session_factory

    async def run(self) -> None:
        async for message in self._kafka:
            try:
                event = OrderPlacedEvent.model_validate_json(message.value)
                # One session + service per message — the consumer is app-lifetime,
                # the session is not.
                async with self._session_factory() as session:
                    fulfillment = FulfillmentService(orders=OrderRepo(session), session=session)
                    await fulfillment.on_order_placed(event)
            except Exception:
                log.exception("consumer.failed", topic=message.topic, offset=message.offset)
                # The consumer group's offset-commit policy decides redelivery.
                raise

    async def close(self) -> None:
        await self._kafka.stop()
```

```python
# app/consumers/order_consumer.py — lifecycle functions, same shape as init_X_client / cleanup_X_client
async def init_order_consumer(app: FastAPI, config: KafkaConfig) -> None:
    kafka = AIOKafkaConsumer(config.ORDERS_TOPIC, bootstrap_servers=config.BOOTSTRAP_SERVERS, group_id=config.GROUP_ID)
    await kafka.start()
    app.state.order_consumer = OrderConsumer(kafka=kafka, session_factory=app.state.db_session_factory)


async def cleanup_order_consumer(app: FastAPI) -> None:
    if hasattr(app.state, "order_consumer"):
        await app.state.order_consumer.close()
```

Lifecycle in `lifespan` — the same `AsyncExitStack` shape as every other resource (see `python-fastapi-sa-app-setup`), with the consumer task registered last so it is cancelled first:

```python
# app/setup.py
import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config: AppConfig = app.state.config
    async with AsyncExitStack() as stack:
        await init_db_pool(app, config.db)
        stack.push_async_callback(close_db_pool, app)

        await init_order_consumer(app, config.kafka)
        stack.push_async_callback(cleanup_order_consumer, app)

        consumer_task = asyncio.create_task(app.state.order_consumer.run())
        stack.push_async_callback(_cancel_and_wait, consumer_task)

        yield


async def _cancel_and_wait(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
```

On shutdown the stack unwinds in reverse: the consumer task is cancelled and awaited, then the Kafka consumer stops, then the DB pool closes. If `init_order_consumer` fails at startup, the DB pool registered before it still closes.
