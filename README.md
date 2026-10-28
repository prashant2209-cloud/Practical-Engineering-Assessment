# Notification Service

A clean, thread-safe notification dispatching service implemented in Python using the standard library. The service handles multi-channel delivery (Email, SMS, and Push notifications), provides idempotency across both notification IDs and duplicate payloads, and safely handles retries for transient downstream failures.

---

## Getting Started

The project has zero external dependencies and runs on Python 3.8+.

### Run the Demo
```bash
cd src
python3 main.py
```

### Run the Test Suite
```bash
cd src
python3 -m unittest -v test_notification_service.py
```

---

## API Overview

### Core Usage
```python
from notification_service import Notification, NotificationService, Channel

service = NotificationService()

# Dispatch a notification
notification = Notification(
    notificationId="notif-101",
    userId="user_42",
    channel=Channel.EMAIL,
    message="Your order #1082 has shipped!"
)
response = service.send(notification)
print(response)
# Output: {'notificationId': 'notif-101', 'status': 'SENT', 'attempts': 1, 'error': None}

# Check delivery status at any time
status = service.getStatus("notif-101")
print(status)
```

### Response Structure

| Field | Type | Description |
|---|---|---|
| `notificationId` | `str` | The unique identifier of the notification. |
| `status` | `str` | Current status: `SENT`, `FAILED`, or `NOT_FOUND`. |
| `attempts` | `int` | Number of delivery attempts made (1 to `max_attempts`). |
| `error` | `Optional[str]` | Error message from the last failed attempt, or `None` on success. |
| `duplicateOf` | `Optional[str]` | Included only when a duplicate payload is detected under a different ID. |

---

## Architecture & Implementation Notes

### 1. Pluggable Senders (Strategy Pattern)
Delivery providers (`EmailSender`, `SMSSender`, `PushSender`) inherit from an abstract `Sender` base class. This decouples the delivery mechanism from notification dispatching, deduplication, and retry logic. Swapping in real API clients (e.g., SendGrid, Twilio, Firebase Cloud Messaging) or mocking them for tests requires no changes to core service logic.

### 2. Dual-Layer Idempotency
To prevent users from being spammed by duplicate notifications, deduplication is enforced at two levels:
1. **Exact ID Replay:** If a request arrives with an existing `notificationId` and matching payload, the existing record is returned without re-dispatching. Reusing an existing ID with conflicting payload values raises a `ValueError`.
2. **Payload Deduplication:** If a new request arrives with a fresh `notificationId` but identical `(userId, channel, message)` payload, the service detects the duplicate, skips delivery, and returns the original status annotated with `'duplicateOf': original_id`.

### 3. Bounded Retries & Error Classification
Downstream communication is inherently prone to temporary hiccups. The service distinguishes between failure categories:
- **Transient Failures (`TemporarySendError`):** Network timeouts, gateway rate limits, or momentary outages trigger retry attempts up to `max_attempts` (defaults to 3 total attempts).
- **Permanent Failures (standard `Exception`):** Unrecoverable errors (e.g. invalid recipient, schema rejection, bad credentials) fail fast on the first attempt without wasting retry budget.

### 4. Thread Safety
A re-entrant lock (`RLock`) synchronizes access to the in-memory records and holds across the delivery attempt. This prevents race conditions where concurrent duplicate requests could both bypass the deduplication check before either has finished delivering.

### 5. Input Validation
Basic validation ensures `notificationId`, `userId`, and `message` are non-empty strings, channels match supported enum values, and a valid sender exists for the target channel.

---

## Production Considerations & Tradeoffs

In a real-world production deployment, several adaptations would be recommended:

1. **Distributed State & Storage:**
   The current implementation uses an in-memory dictionary, which is fast and self-contained for single-process evaluation. In a distributed multi-instance service, idempotency keys and delivery status should be stored in a shared datastore like Redis (using `SET key value NX EX ...`) or PostgreSQL (with unique constraint indexing on `(user_id, channel, message_hash)`).

2. **Asynchronous Processing & Message Queues:**
   Synchronous in-process retries block worker threads. In production, requests should be quickly acknowledged and pushed into a distributed message broker (e.g. AWS SQS, RabbitMQ, Kafka). Dedicated worker pools can then process deliveries and apply exponential backoff with jitter and Dead Letter Queues (DLQ).

3. **Provider Idempotency Keys:**
   If a network connection drops after an external provider (e.g. Twilio or SendGrid) accepts a request but before returning a response, our client might retry and cause duplicate delivery on the provider's end. Passing a deterministic idempotency key directly to provider APIs resolves this window of ambiguity.
