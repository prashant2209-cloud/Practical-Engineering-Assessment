"""
Core notification service implementation.
Provides channel dispatching, deduplication, retry handling for transient errors,
and in-memory status tracking.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Dict, Optional, Tuple


class Channel(str, Enum):
    EMAIL = 'EMAIL'
    SMS = 'SMS'
    PUSH = 'PUSH'


class Status(str, Enum):
    PENDING = 'PENDING'
    SENT = 'SENT'
    FAILED = 'FAILED'


class TemporarySendError(Exception):
    """Raised when a downstream provider fails temporarily (e.g. rate limit, network timeout)."""
    pass


@dataclass(frozen=True)
class Notification:
    notificationId: str
    userId: str
    channel: Channel
    message: str


class Sender(ABC):
    """Abstract base class for channel-specific senders."""

    @abstractmethod
    def send(self, notification: Notification) -> None:
        pass


class EmailSender(Sender):
    def send(self, notification: Notification) -> None:
        print(f"EMAIL to {notification.userId}: {notification.message}")


class SMSSender(Sender):
    def send(self, notification: Notification) -> None:
        print(f"SMS to {notification.userId}: {notification.message}")


class PushSender(Sender):
    def send(self, notification: Notification) -> None:
        print(f"PUSH to {notification.userId}: {notification.message}")


class NotificationService:
    """
    Orchestrates notification dispatching across configured channels.
    Guarantees at-most-once delivery per notification payload/id and
    handles transient retries safely under concurrent conditions.
    """

    def __init__(self, senders: Optional[Dict[Channel, Sender]] = None, max_attempts: int = 3):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        self.senders = senders if senders is not None else {
            Channel.EMAIL: EmailSender(),
            Channel.SMS: SMSSender(),
            Channel.PUSH: PushSender(),
        }
        self.max_attempts = max_attempts

        # ID -> delivery record dictionary
        self._records: Dict[str, dict] = {}
        # (userId, channel, message) -> original notification ID for deduplication
        self._values: Dict[Tuple[str, Channel, str], str] = {}
        self._lock = RLock()

    def send(self, notification: Notification) -> dict:
        if not isinstance(notification, Notification):
            raise TypeError("Expected an instance of Notification")

        if not notification.notificationId or not notification.userId or not notification.message:
            raise ValueError("notificationId, userId, and message must not be empty")

        try:
            channel = Channel(notification.channel)
        except (ValueError, KeyError) as exc:
            raise ValueError(f"Unsupported notification channel: {notification.channel}") from exc

        payload_key = (notification.userId, channel, notification.message)

        with self._lock:
            # Check for exact ID replay
            if notification.notificationId in self._records:
                existing = self._records[notification.notificationId]
                if existing['key'] != payload_key:
                    raise ValueError("notificationId already belongs to different values")
                return self.getStatus(notification.notificationId)

            # Check for duplicate payload under a different ID
            if payload_key in self._values:
                original_id = self._values[payload_key]
                result = self.getStatus(original_id)
                return {**result, 'duplicateOf': original_id}

            if channel not in self.senders:
                raise ValueError(f"No sender configured for channel: {channel}")

            # Reserve record and payload key before attempting delivery
            record = {
                'key': payload_key,
                'status': Status.PENDING,
                'attempts': 0,
                'error': None,
            }
            self._records[notification.notificationId] = record
            self._values[payload_key] = notification.notificationId

            # Bounded retry loop for transient failures
            for attempt in range(1, self.max_attempts + 1):
                record['attempts'] = attempt
                try:
                    self.senders[channel].send(notification)
                    record['status'] = Status.SENT
                    record['error'] = None
                    break
                except TemporarySendError as exc:
                    record['error'] = str(exc)
                    if attempt == self.max_attempts:
                        record['status'] = Status.FAILED
                except Exception as exc:
                    # Permanent failure: abort immediately without retrying
                    record['error'] = str(exc)
                    record['status'] = Status.FAILED
                    break

            return self.getStatus(notification.notificationId)

    def getStatus(self, notificationId: str) -> dict:
        with self._lock:
            record = self._records.get(notificationId)
            if record is None:
                return {'notificationId': notificationId, 'status': 'NOT_FOUND'}

            return {
                'notificationId': notificationId,
                'status': record['status'].value,
                'attempts': record['attempts'],
                'error': record['error'],
            }

    # Pythonic snake_case alias
    get_status = getStatus
