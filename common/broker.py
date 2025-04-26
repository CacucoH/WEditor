import redis
import json
import threading
import time
import os # Import os
from typing import Callable, Optional, Dict, Any

Operation = Dict[str, Any] # From rga.py

class RedisBroker:
    def __init__(self,
                 host: Optional[str] = None,
                 port: Optional[int] = None,
                 db: int = 0):
        # Read from environment variables, fallback to defaults
        resolved_host = host or os.environ.get('REDIS_HOST', 'localhost')
        resolved_port = port or int(os.environ.get('REDIS_PORT', 6379)) # Ensure port is int

        try:
            self.redis_client = redis.Redis(host=resolved_host, port=resolved_port, db=db, decode_responses=True)
            self.redis_client.ping() # Check connection
            print(f"Connected to Redis at {resolved_host}:{resolved_port}")
        except redis.ConnectionError as e:
            print(f"Error connecting to Redis ({resolved_host}:{resolved_port}): {e}")
            print("Please ensure Redis server is running or environment variables (REDIS_HOST, REDIS_PORT) are set correctly.")
            self.redis_client = None
            return
        except ValueError:
             print(f"Error: Invalid REDIS_PORT environment variable value: {os.environ.get('REDIS_PORT')}. Must be an integer.")
             self.redis_client = None
             return

        self.pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)
        self.subscriber_thread = None
        self.is_running = False
        self._handlers: Dict[str, Callable[[Operation], None]] = {}

    def publish(self, channel: str, operation: Operation):
        if not self.redis_client:
            print("Error: Cannot publish, Redis client not connected.")
            return
        try:
            message = json.dumps(operation)
            self.redis_client.publish(channel, message)
            # print(f"Published to {channel}: {message[:100]}...") # Debug
        except redis.RedisError as e:
            print(f"Error publishing to Redis channel {channel}: {e}")
        except TypeError as e:
            print(f"Error serializing operation for publish: {e}. Operation: {operation}")

    def subscribe(self, channel: str, handler: Callable[[Operation], None]):
        if not self.redis_client:
            print("Error: Cannot subscribe, Redis client not connected.")
            return
        if channel in self._handlers:
            print(f"Warning: Handler already registered for channel {channel}. Replacing.")

        self._handlers[channel] = handler
        self.pubsub.subscribe(channel)
        print(f"Subscribed to Redis channel: {channel}")

        if self.subscriber_thread is None or not self.subscriber_thread.is_alive():
            self.is_running = True
            self.subscriber_thread = threading.Thread(target=self._listen, daemon=True)
            self.subscriber_thread.start()
            print("Started Redis listener thread.")

    def _listen(self):
        if not self.redis_client:
            print("Listener thread cannot start, Redis client not connected.")
            self.is_running = False
            return

        print("Redis listener thread waiting for messages...")
        while self.is_running:
            try:
                message = self.pubsub.get_message(timeout=1.0) # Timeout to allow checking self.is_running
                if message:
                    # print(f"Raw message received: {message}") # Debug
                    if message['type'] == 'message':
                        channel = message['channel']
                        data = message['data']
                        # print(f"Received on {channel}: {data[:100]}...") # Debug
                        if channel in self._handlers:
                            try:
                                operation = json.loads(data)
                                self._handlers[channel](operation)
                            except json.JSONDecodeError as e:
                                print(f"Error decoding JSON from channel {channel}: {e}. Data: {data}")
                            except Exception as e:
                                print(f"Error in handler for channel {channel}: {e}")
                        else:
                            print(f"Warning: Received message on unhandled channel {channel}")
                # Allow thread to exit gracefully if is_running is set to False
                # time.sleep(0.01) # Short sleep if no message to prevent busy-waiting cpu usage
            except redis.ConnectionError as e:
                print(f"Redis connection error in listener thread: {e}. Attempting to reconnect...")
                self.is_running = False # Stop listening loop
                # TODO: Implement reconnection logic
                time.sleep(5)
                break # Exit thread for now
            except Exception as e:
                print(f"Unexpected error in Redis listener thread: {e}")
                time.sleep(1) # Avoid rapid failure loops

        print("Redis listener thread stopped.")
        try:
            self.pubsub.unsubscribe()
            self.pubsub.close()
            print("Unsubscribed and closed Redis pubsub.")
        except Exception as e:
            print(f"Error closing pubsub: {e}")

    def stop(self):
        print("Stopping RedisBroker...")
        self.is_running = False
        if self.subscriber_thread and self.subscriber_thread.is_alive():
            self.subscriber_thread.join(timeout=2.0) # Wait for thread to finish
            if self.subscriber_thread.is_alive():
                print("Warning: Redis listener thread did not stop cleanly.")
        print("RedisBroker stopped.")

# Example usage (for testing)
if __name__ == '__main__':
    def simple_handler(operation):
        print(f"Handler received: {operation}")

    broker = RedisBroker()
    if broker.redis_client: # Only proceed if connection succeeded
        broker.subscribe("test_channel", simple_handler)

        print("Publishing test messages...")
        broker.publish("test_channel", {"type": "insert", "value": "Hello"})
        broker.publish("test_channel", {"type": "delete", "id": 123})
        broker.publish("other_channel", {"type": "update", "value": "Ignore Me"})

        print("Waiting for messages (5s)...")
        time.sleep(5)

        broker.stop()
        print("Broker finished.")
    else:
        print("Broker example failed due to Redis connection error.") 