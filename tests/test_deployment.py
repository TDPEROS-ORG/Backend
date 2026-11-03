import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kafka.structs import OffsetAndMetadata, TopicPartition
from werkzeug.exceptions import Unauthorized

from src.infraestructura.messaging.kafka_consumer import TelemetryKafkaConsumer
from src.deployment import initialize_database


class KafkaDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.broker = MagicMock()
        self.ingestion = MagicMock()
        self.ingestion.save_payload.return_value = SimpleNamespace(
            sequence_number=1, device_id="sensor-test", battery_level=50,
            estimated_autonomy_hours=2.5, operational_state="NORMAL_OPERATION", alert_level="NONE",
        )
        with patch("src.infraestructura.messaging.kafka_consumer.KafkaConsumer", return_value=self.broker):
            self.worker = TelemetryKafkaConsumer(self.ingestion, "kafka:9092", "test", "test-group")
        self.message = SimpleNamespace(topic="test", partition=0, offset=7,
                                       value=b'{"deviceId":"sensor-test","deviceKey":"secret-device-key"}')

    def run_messages(self, messages):
        self.broker.__iter__.return_value = iter(messages)
        output = io.StringIO()
        with redirect_stdout(output):
            self.worker.run_forever()
        return output.getvalue()

    def test_success_commits_only_processed_partition_and_offset(self):
        output = self.run_messages([self.message])
        self.broker.commit.assert_called_once_with({TopicPartition("test", 0): OffsetAndMetadata(8, "", -1)})
        self.broker.close.assert_called_once_with(autocommit=False)
        self.assertNotIn("secret-device-key", output)

    def test_database_error_leaves_offset_uncommitted(self):
        self.ingestion.save_payload.side_effect = ConnectionError("database offline")
        with self.assertRaises(ConnectionError):
            self.run_messages([self.message])
        self.broker.commit.assert_not_called()
        self.broker.close.assert_called_once_with(autocommit=False)

    def test_commit_error_is_not_treated_as_invalid_message(self):
        self.broker.commit.side_effect = ConnectionError("broker offline")
        with self.assertRaises(ConnectionError):
            self.run_messages([self.message])
        self.assertEqual(self.broker.commit.call_count, 1)

    def test_invalid_json_is_rejected_without_stopping_next_message(self):
        invalid = SimpleNamespace(topic="test", partition=1, offset=3, value=b"{")
        output = self.run_messages([invalid, self.message])
        self.assertEqual(self.ingestion.save_payload.call_count, 1)
        self.assertEqual(self.broker.commit.call_count, 2)
        self.assertIn("RECHAZADO", output)
        self.assertNotIn("secret-device-key", output)

    def test_unauthorized_device_is_rejected_without_exposing_key(self):
        self.ingestion.save_payload.side_effect = Unauthorized("secret-device-key")
        output = self.run_messages([self.message])
        self.assertIn("RECHAZADO", output)
        self.assertNotIn("secret-device-key", output)
        self.broker.commit.assert_called_once()

    def test_invalid_utf8_is_rejected(self):
        self.message.value = b"\xff"
        self.run_messages([self.message])
        self.ingestion.save_payload.assert_not_called()
        self.broker.commit.assert_called_once()

    def test_empty_message_is_rejected(self):
        self.message.value = None
        self.run_messages([self.message])
        self.ingestion.save_payload.assert_not_called()
        self.broker.commit.assert_called_once()


class BootstrapConfigurationTests(unittest.TestCase):
    def test_invalid_database_name_is_rejected_before_connecting(self):
        with patch("src.deployment.mysql.connector.connect") as connect:
            with self.assertRaises(ValueError):
                initialize_database(SimpleNamespace(MYSQL_DATABASE="unsafe-name;DROP"), "sql")
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()