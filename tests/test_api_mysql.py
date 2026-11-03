import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import mysql.connector

from app import create_app
from src.config import Config
from src.deployment import initialize_database
from src.infraestructura.database.connection import Database
from src.monitoring import reading_quality


class TestAI:
    def enrich(self, payload, **kwargs):
        return {**payload, "estimatedAutonomyHours": 1.2, "availabilityIndex": 25,
                "operationalState": "LOW_BATTERY", "alertLevel": "MEDIUM",
                "recommendation": "Reduce cargas no esenciales."}

    def health(self):
        return {"status": "ok"}


class ApiMySqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_name = "energy_auth_test_" + uuid.uuid4().hex[:10]
        config = Database(Config)._build_connection_config()
        config.pop("database")
        try:
            cls.server = mysql.connector.connect(**config)
        except mysql.connector.Error as error:
            raise unittest.SkipTest(f"MySQL local no disponible: {type(error).__name__}")
        cursor = cls.server.cursor()
        cursor.execute(f"CREATE DATABASE {cls.database_name} CHARACTER SET utf8mb4")
        cls.test_config = type("TestConfig", (Config,), {"MYSQL_DATABASE": cls.database_name})
        cls.database = Database(cls.test_config)
        root = Path(__file__).resolve().parents[1]
        try:
            with cls.database.connection() as connection:
                sql_cursor = connection.cursor()
                for filename in ("02_create_telemetry_table.sql", "04_users_households.sql"):
                    for statement in (root / "sql" / filename).read_text(encoding="utf-8").split(";"):
                        if statement.strip() and not statement.strip().upper().startswith("USE "):
                            sql_cursor.execute(statement)
                sql_cursor.close()
        except Exception:
            cursor.execute(f"DROP DATABASE {cls.database_name}")
            cls.server.close()
            raise
        cursor.close()
        cls.app = create_app(database=cls.database, ai_service=TestAI())
        cls.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        cursor = cls.server.cursor()
        cursor.execute(f"DROP DATABASE {cls.database_name}")
        cursor.close()
        cls.server.close()

    def setUp(self):
        self.store = self.app.extensions["identity"]
        for table in ("incident_events", "incidents", "telemetry", "auth_sessions", "auth_throttle", "devices", "households", "users"):
            self.store.query(f"DELETE FROM {table}", write=True)
        self.client = self.app.test_client()
        self.owner = self.store.create_user({"fullName": "Cliente Uno", "email": "uno@example.test", "password": "Prueba-segura-2026", "householdName": "Hogar Uno"})
        self.other = self.store.create_user({"fullName": "Cliente Dos", "email": "dos@example.test", "password": "Prueba-segura-2026", "householdName": "Hogar Dos"})
        self.store.create_user({"fullName": "Operador", "email": "operador@example.test", "password": "Prueba-segura-2026"}, role="operator")
        self.device = self.store.register_device(self.owner["householdId"], {"deviceId": "sensor-uno", "name": "Sistema Uno"})
        self.payload = {"deviceId": "sensor-uno", "batteryLevel": 25, "voltage": 12.4, "currentA": 2,
                        "loadPowerW": 50, "solarPowerW": 10, "netPowerW": 40, "availableEnergyWh": 90}

    def login(self, email="uno@example.test", profile="client"):
        response = self.client.post("/api/auth/login", json={"email": email, "password": "Prueba-segura-2026", "profile": profile})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def publish(self):
        response = self.client.post("/api/telemetry", json=self.payload, headers={"X-Device-Key": self.device["deviceKey"]})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json["data"]

    def test_login_and_logout_revoke_session(self):
        login = self.login()
        headers = {"Authorization": "Bearer " + login["token"]}
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/telemetry/summary", headers=headers).status_code, 401)

    def test_clients_cannot_see_other_telemetry_or_operator_api(self):
        self.publish()
        login = self.login("dos@example.test")
        headers = {"Authorization": "Bearer " + login["token"]}
        for path in ("/api/telemetry", "/api/telemetry/latest", "/api/telemetry/summary", "/api/telemetry/detail", "/api/telemetry/dashboard", "/api/telemetry/recommendations"):
            response = self.client.get(path + "?householdId=" + str(self.owner["householdId"]), headers=headers)
            self.assertEqual(response.status_code, 200, (path, response.json))
            if path == "/api/telemetry/latest":
                self.assertIsNone(response.json["data"])
            if path == "/api/telemetry/summary":
                self.assertFalse(response.json["online"])
        self.assertEqual(self.client.get("/api/operator/households", headers=headers).status_code, 403)
        owner = self.login()
        response = self.client.get("/api/telemetry/latest", headers={"Authorization": "Bearer " + owner["token"]})
        self.assertEqual(response.json["data"]["deviceId"], "sensor-uno")

    def test_unauthenticated_and_device_key_rejected(self):
        self.assertEqual(self.client.get("/api/telemetry/summary").status_code, 401)
        self.assertEqual(self.client.post("/api/telemetry", json=self.payload).status_code, 401)
        self.assertEqual(self.client.post("/api/telemetry", json=self.payload, headers={"X-Device-Key": "incorrecta"}).status_code, 401)
        bad = {**self.payload, "batteryLevel": float("nan")}
        self.assertEqual(self.client.post("/api/telemetry", json=bad, headers={"X-Device-Key": self.device["deviceKey"]}).status_code, 400)

    def test_operator_csrf_history_and_incident_trace(self):
        self.publish()
        login = self.login("operador@example.test", "operator")
        self.assertNotIn("token", login)
        response = self.client.get("/api/operator/households")
        self.assertEqual(response.status_code, 200, response.json)
        response = self.client.get(f"/api/operator/households/{self.owner['householdId']}/history?period=7d")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(len(response.json["readings"]), 1)
        response = self.client.get(f"/api/operator/households/{self.owner['householdId']}/incidents?period=7d&type=low_battery")
        self.assertEqual(response.status_code, 200, response.json)
        incident_id = response.json["data"][0]["id"]
        event = {"status": "acknowledged", "note": "Contacto con el hogar realizado"}
        path = f"/api/operator/incidents/{incident_id}/events"
        self.assertEqual(self.client.post(path, json=event).status_code, 403)
        self.assertEqual(self.client.post(path, json=event, headers={"X-CSRF-Token": login["csrfToken"]}).status_code, 201)
        trace = self.client.get(f"/api/operator/incidents/{incident_id}").json
        self.assertEqual(len(trace["events"]), 1)
        self.assertEqual(trace["events"][0]["note"], event["note"])

    def test_role_cannot_be_chosen_by_client(self):
        response = self.client.post("/api/auth/login", json={"email": "uno@example.test", "password": "Prueba-segura-2026", "profile": "operator"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post("/api/auth/register", json={"role": "operator"}).status_code, 404)

    def test_profile_disable_revokes_access_and_ingestion(self):
        owner_login = self.login()
        operator_login = self.login("operador@example.test", "operator")
        response = self.client.patch(f"/api/operator/households/{self.owner['householdId']}", json={"fullName": "Cliente Uno", "householdName": "Hogar Uno", "active": False}, headers={"X-CSRF-Token": operator_login["csrfToken"]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": "Bearer " + owner_login["token"]}).status_code, 401)
        self.assertEqual(self.client.post("/api/telemetry", json=self.payload, headers={"X-Device-Key": self.device["deviceKey"]}).status_code, 401)

    def test_old_data_is_stale_and_invalid_data_never_valid(self):
        self.assertEqual(reading_quality(None)["state"], "empty")
        self.assertFalse(reading_quality({"batteryLevel": 10})["valid"])
        self.publish()
        self.store.query("UPDATE telemetry SET created_at=DATE_SUB(NOW(),INTERVAL 1 DAY)", write=True)
        self.login("operador@example.test", "operator")
        response = self.client.get(f"/api/operator/households/{self.owner['householdId']}")
        self.assertEqual(response.json["quality"]["state"], "stale")

    def test_incomplete_and_out_of_range_readings_are_rejected_before_ai(self):
        for payload in ({"deviceId": "sensor-uno", "voltage": 12}, {**self.payload, "batteryLevel": 101}, {**self.payload, "loadPowerW": -1}):
            response = self.client.post("/api/telemetry", json=payload, headers={"X-Device-Key": self.device["deviceKey"]})
            self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(self.store.query("SELECT COUNT(*) AS total FROM telemetry", one=True)["total"], 0)

    def test_operator_can_create_client_but_cannot_escalate_role(self):
        login = self.login("operador@example.test", "operator")
        response = self.client.post("/api/operator/households", json={"fullName": "Nuevo", "email": "nuevo@example.test", "password": "Prueba-segura-2026", "householdName": "Nuevo hogar", "role": "operator"}, headers={"X-CSRF-Token": login["csrfToken"]})
        self.assertEqual(response.status_code, 201, response.json)
        new_user = self.store.query("SELECT role,password_hash FROM users WHERE email=%s", ("nuevo@example.test",), one=True)
        self.assertEqual(new_user["role"], "client")
        self.assertNotEqual(new_user["password_hash"], "Prueba-segura-2026")

    def test_key_rotation_invalidates_old_device_key(self):
        login = self.login("operador@example.test", "operator")
        response = self.client.patch(f"/api/operator/households/{self.owner['householdId']}/devices/sensor-uno", json={"active": True, "rotateKey": True}, headers={"X-CSRF-Token": login["csrfToken"]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.client.post("/api/telemetry", json=self.payload, headers={"X-Device-Key": self.device["deviceKey"]}).status_code, 401)
        self.device["deviceKey"] = response.json["deviceKey"]
        self.publish()

    def test_existing_readings_are_only_claimed_explicitly(self):
        self.store.query("INSERT INTO telemetry (device_id,battery_level,voltage,operational_state,alert_level) VALUES ('legacy-device',50,12,'NORMAL_OPERATION','NONE')", write=True)
        self.store.register_device(self.other["householdId"], {"deviceId": "legacy-device", "name": "Fuente antigua", "claimLegacy": True})
        row = self.store.query("SELECT household_id FROM telemetry WHERE device_id='legacy-device'", one=True)
        self.assertEqual(row["household_id"], self.other["householdId"])

    def test_local_ai_model_still_predicts(self):
        from src.aplicacion.services.ai_autonomy_service import AiAutonomyService
        from src.monitoring import TelemetryIngestion
        from src.infraestructura.repositories.mysql_telemetry_repository import MySqlTelemetryRepository

        ai = AiAutonomyService(Config.AI_MODEL_PATH)
        ingestion = TelemetryIngestion(self.store, MySqlTelemetryRepository(self.database), ai)
        saved = ingestion.save_payload(self.payload, self.device["deviceKey"])
        self.assertIsNotNone(saved.id)
        self.assertGreaterEqual(saved.estimated_autonomy_hours, 0)
        self.assertEqual(saved.device_id, "sensor-uno")

    def test_expired_session_requires_login(self):
        login = self.login()
        self.store.query("UPDATE auth_sessions SET expires_at=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 1 HOUR)", write=True)
        response = self.client.get("/api/telemetry/summary", headers={"Authorization": "Bearer " + login["token"]})
        self.assertEqual(response.status_code, 401)

    def test_client_supplied_owner_is_ignored(self):
        self.payload.update({"householdId": self.other["householdId"], "userId": self.other["id"]})
        reading = self.publish()
        stored = self.store.query("SELECT household_id FROM telemetry WHERE id=%s", (reading["id"],), one=True)
        self.assertEqual(stored["household_id"], self.owner["householdId"])

    def test_cors_allows_expo_but_not_arbitrary_origin(self):
        response = self.client.options("/api/auth/login", headers={"Origin": "http://localhost:8082", "Access-Control-Request-Method": "POST"})
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "http://localhost:8082")
        self.assertEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")
        response = self.client.options("/api/auth/login", headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)

    def test_readiness_checks_database_without_leaking_errors(self):
        self.assertEqual(self.client.get("/api/ready").status_code, 200)
        with patch.object(self.store, "query", side_effect=ConnectionError("private connection details")):
            response = self.client.get("/api/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {"status": "unavailable"})

    def test_readiness_rejects_unloaded_model(self):
        with patch.object(self.app.extensions["ai"], "health", return_value={"status": "not_loaded"}):
            self.assertEqual(self.client.get("/api/ready").status_code, 503)

    def test_operator_cookie_supports_secure_cross_site_configuration(self):
        with patch.dict(self.app.config, AUTH_COOKIE_SECURE=True, AUTH_COOKIE_SAMESITE="None"):
            response = self.client.post("/api/auth/login", json={"email": "operador@example.test", "password": "Prueba-segura-2026", "profile": "operator"})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["Set-Cookie"]
        for attribute in ("Secure", "HttpOnly", "SameSite=None", "Path=/api"):
            self.assertIn(attribute, cookie)

    def test_insecure_cross_site_configuration_fails_at_startup(self):
        with patch.object(Config, "AUTH_COOKIE_SAMESITE", "None"), patch.object(Config, "AUTH_COOKIE_SECURE", False):
            with self.assertRaises(ValueError):
                create_app(database=self.database, ai_service=TestAI())

    def test_database_initialization_is_safe_to_repeat(self):
        database_name = "energy_auth_test_" + uuid.uuid4().hex[:10]
        configuration = type("BootstrapConfig", (Config,), {"MYSQL_DATABASE": database_name})
        try:
            self.assertTrue(initialize_database(configuration, Path(__file__).resolve().parents[1] / "sql"))
            self.assertFalse(initialize_database(configuration, Path(__file__).resolve().parents[1] / "sql"))
        finally:
            cursor = self.server.cursor()
            cursor.execute(f"DROP DATABASE IF EXISTS {database_name}")
            cursor.close()

    def test_database_initialization_refuses_partial_schema(self):
        database_name = "energy_auth_test_" + uuid.uuid4().hex[:10]
        configuration = type("BootstrapConfig", (Config,), {"MYSQL_DATABASE": database_name})
        cursor = self.server.cursor()
        try:
            cursor.execute(f"CREATE DATABASE {database_name}")
            cursor.execute(f"CREATE TABLE {database_name}.marker (id INT)")
            with self.assertRaisesRegex(RuntimeError, "parcial"):
                initialize_database(configuration, Path(__file__).resolve().parents[1] / "sql")
            cursor.execute(f"SELECT COUNT(*) FROM {database_name}.marker")
            self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            cursor.execute(f"DROP DATABASE IF EXISTS {database_name}")
            cursor.close()


if __name__ == "__main__":
    unittest.main()