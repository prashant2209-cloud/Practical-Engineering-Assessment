import threading
import unittest
from notification_service import (
    Channel,
    Notification,
    NotificationService,
    Sender,
    Status,
    TemporarySendError,
)


class FakeSender(Sender):
    """Test helper that records call count and simulates transient or permanent failures."""

    def __init__(self, failures: int = 0, permanent: bool = False):
        self.calls = 0
        self.failures = failures
        self.permanent = permanent

    def send(self, notification: Notification) -> None:
        self.calls += 1
        if self.permanent:
            raise RuntimeError("Invalid destination address")
        if self.calls <= self.failures:
            raise TemporarySendError("Provider temporarily unavailable")


class NotificationServiceTests(unittest.TestCase):
    def setUp(self):
        self.sender = FakeSender()
        self.service = NotificationService({Channel.EMAIL: self.sender})
        self.notification = Notification('n1', 'user1', Channel.EMAIL, 'Hello')

    def test_success_and_no_resend(self):
        """Verifies successful delivery and that sending the same ID again does not re-deliver."""
        self.assertEqual(self.service.send(self.notification)['status'], 'SENT')
        self.assertEqual(self.service.send(self.notification)['status'], 'SENT')
        self.assertEqual(self.sender.calls, 1)

    def test_duplicate_values(self):
        """Verifies duplicate payload with a different notification ID returns duplicateOf."""
        self.service.send(self.notification)
        result = self.service.send(Notification('n2', 'user1', Channel.EMAIL, 'Hello'))
        self.assertEqual(result['duplicateOf'], 'n1')
        self.assertEqual(self.sender.calls, 1)

    def test_retry_then_success(self):
        """Verifies transient errors are retried up to the limit and succeed."""
        sender = FakeSender(failures=2)
        service = NotificationService({Channel.EMAIL: sender})
        result = service.send(self.notification)
        self.assertEqual((result['status'], result['attempts']), ('SENT', 3))

    def test_retry_limit(self):
        """Verifies execution stops and marks FAILED once max retry attempts are exhausted."""
        sender = FakeSender(failures=10)
        service = NotificationService({Channel.EMAIL: sender})
        result = service.send(self.notification)
        self.assertEqual((result['status'], result['attempts']), ('FAILED', 3))
        # Subsequent send of failed record returns existing status without extra provider calls
        service.send(self.notification)
        self.assertEqual(sender.calls, 3)

    def test_permanent_failure_not_retried(self):
        """Verifies permanent/unexpected exceptions fail immediately without retrying."""
        sender = FakeSender(permanent=True)
        result = NotificationService({Channel.EMAIL: sender}).send(self.notification)
        self.assertEqual((result['status'], result['attempts']), ('FAILED', 1))

    def test_unknown_status(self):
        """Verifies querying an unrecognized notification ID returns NOT_FOUND."""
        self.assertEqual(self.service.getStatus('missing')['status'], 'NOT_FOUND')

    def test_id_conflict(self):
        """Verifies reusing an existing ID with differing payload raises ValueError."""
        self.service.send(self.notification)
        with self.assertRaises(ValueError):
            self.service.send(Notification('n1', 'user2', Channel.EMAIL, 'Other'))

    def test_input_validation(self):
        """Verifies invalid or empty inputs are rejected."""
        # Non-notification type
        with self.assertRaises(TypeError):
            self.service.send("not-a-notification")  # type: ignore

        # Empty fields
        with self.assertRaises(ValueError):
            self.service.send(Notification('', 'user1', Channel.EMAIL, 'Hello'))
        with self.assertRaises(ValueError):
            self.service.send(Notification('n1', '', Channel.EMAIL, 'Hello'))
        with self.assertRaises(ValueError):
            self.service.send(Notification('n1', 'user1', Channel.EMAIL, ''))

    def test_unsupported_channel(self):
        """Verifies sending with an unrecognized channel raises ValueError."""
        with self.assertRaises(ValueError):
            self.service.send(Notification('n1', 'user1', 'CARRIER_PIGEON', 'Hello'))  # type: ignore

    def test_missing_sender_configuration(self):
        """Verifies error when no sender is configured for a valid channel."""
        service = NotificationService({Channel.EMAIL: self.sender})
        sms_notif = Notification('n2', 'user1', Channel.SMS, 'Hello')
        with self.assertRaises(ValueError):
            service.send(sms_notif)

    def test_concurrency_duplicate_prevention(self):
        """Verifies concurrent delivery requests for the same notification execute exactly once."""
        results = []
        threads = []

        def worker():
            res = self.service.send(self.notification)
            results.append(res)

        for _ in range(10):
            t = threading.Thread(target=worker)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 10)
        # All threads should report SENT status
        for res in results:
            self.assertEqual(res['status'], 'SENT')
        # Underlying sender should only have been invoked once
        self.assertEqual(self.sender.calls, 1)

    def test_custom_max_attempts(self):
        """Verifies custom max_attempts configuration is respected."""
        sender = FakeSender(failures=5)
        service = NotificationService({Channel.EMAIL: sender}, max_attempts=2)
        res = service.send(self.notification)
        self.assertEqual(res['attempts'], 2)
        self.assertEqual(res['status'], 'FAILED')

    def test_invalid_max_attempts_init(self):
        """Verifies max_attempts < 1 raises ValueError on initialization."""
        with self.assertRaises(ValueError):
            NotificationService(max_attempts=0)


if __name__ == '__main__':
    unittest.main()
