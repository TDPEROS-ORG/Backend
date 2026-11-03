import unittest
from datetime import datetime
from unittest.mock import MagicMock

from src.dominio.entities.telemetry import Telemetry
from src.infraestructura.repositories.mysql_telemetry_repository import MySqlTelemetryRepository


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.database = MagicMock()
        self.cursor = self.database.connection.return_value.__enter__.return_value.cursor.return_value
        self.cursor.fetchone.return_value = None
        self.cursor.fetchall.return_value = []

    def test_unscoped_operations_fail_closed(self):
        repository = MySqlTelemetryRepository(self.database)
        for operation in (
            repository.find_latest,
            repository.find_recent,
            lambda: repository.find_since(datetime.now()),
            lambda: repository.save(Telemetry()),
        ):
            with self.assertRaises(ValueError):
                operation()
        self.cursor.execute.assert_not_called()

    def test_every_read_filters_by_household(self):
        repository = MySqlTelemetryRepository(self.database, household_id=7)
        repository.find_latest()
        repository.find_recent()
        repository.find_since(datetime.now())
        for call in self.cursor.execute.call_args_list:
            query, params = call.args
            self.assertIn("household_id = %(household_id)s", query)
            self.assertEqual(params["household_id"], 7)

    def test_write_uses_server_side_owner(self):
        repository = MySqlTelemetryRepository(self.database, household_id=7)
        repository.save(Telemetry(device_id="sensor-1"))
        query, params = self.cursor.execute.call_args_list[0].args
        self.assertIn("household_id", query)
        self.assertEqual(params["household_id"], 7)


if __name__ == "__main__":
    unittest.main()