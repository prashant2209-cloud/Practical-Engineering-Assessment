"""
Demonstration script for the Notification Service.
Runs a walkthrough of standard sending, deduplication, retries, and status retrieval.
"""
from notification_service import (
    Channel,
    Notification,
    NotificationService,
    Sender,
    TemporarySendError,
)


class FlakyPushSender(Sender):
    """Simulates a third-party gateway with transient network issues."""

    def __init__(self):
        self.attempts = 0

    def send(self, notification: Notification) -> None:
        self.attempts += 1
        if self.attempts < 2:
            print(f"  [Attempt {self.attempts}] Gateway timeout connecting to APNs...")
            raise TemporarySendError("APNs connection timeout")
        print(f"  [Attempt {self.attempts}] PUSH delivered to {notification.userId}: {notification.message}")


def main():
    print("=" * 65)
    print("Notification Service Demonstration")
    print("=" * 65)

    service = NotificationService()

    # 1. Dispatching notifications across channels
    print("\n--- 1. Standard Multi-Channel Dispatch ---")
    notifications = [
        Notification('n1', 'user1', Channel.EMAIL, 'Welcome to the platform!'),
        Notification('n2', 'user2', Channel.SMS, 'Your verification code is 123456'),
        Notification('n3', 'user3', Channel.PUSH, 'You have a new message'),
    ]

    for item in notifications:
        result = service.send(item)
        print(f"Result for {item.notificationId}: {result}")

    # 2. Idempotency: exact same notification object / ID
    print("\n--- 2. Idempotency (Same Notification ID) ---")
    print("Resending 'n1' (same ID and payload)...")
    resend_result = service.send(notifications[0])
    print(f"Result (delivered without resending): {resend_result}")

    # 3. Deduplication: different ID, identical payload
    print("\n--- 3. Deduplication (Different ID, Identical Payload) ---")
    duplicate_payload = Notification('n4', 'user1', Channel.EMAIL, 'Welcome to the platform!')
    print("Sending 'n4' with same payload as 'n1'...")
    dup_result = service.send(duplicate_payload)
    print(f"Result (detected duplicate): {dup_result}")

    # 4. Status queries
    print("\n--- 4. Status Queries ---")
    print(f"Status for 'n1': {service.getStatus('n1')}")
    print(f"Status for unknown 'n999': {service.getStatus('n999')}")

    # 5. Retry mechanism with transient failure
    print("\n--- 5. Transient Error Handling & Retries ---")
    print("Configuring service with a flaky push provider (fails once, then succeeds)...")
    retry_service = NotificationService({Channel.PUSH: FlakyPushSender()})
    retry_notification = Notification('n5', 'user4', Channel.PUSH, 'System alert')
    retry_result = retry_service.send(retry_notification)
    print(f"Final Result: {retry_result}")

    print("\n" + "=" * 65)
    print("All demonstrations completed successfully.")
    print("=" * 65)


if __name__ == '__main__':
    main()
