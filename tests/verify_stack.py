import argparse
import http.cookiejar
import json
import os
import secrets
import time
import urllib.error
import urllib.request
import uuid

from kafka import KafkaProducer

from app import app
from src.config import Config


def request(opener, path, payload=None, headers=None, expected=(200,)):
    encoded = json.dumps(payload).encode() if payload is not None else None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    message = urllib.request.Request("http://127.0.0.1:8080" + path, data=encoded, headers=request_headers)
    try:
        response = opener.open(message, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status in expected, (path, response.status)
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-unready", action="store_true")
    arguments = parser.parse_args()
    if Config.MYSQL_HOST != "mysql" or os.getenv("ENERGY_VERIFY_ALLOW") != "temporary-stack":
        raise RuntimeError("Solo ejecutar en compose.verify.yml, nunca sobre una BD real")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    if arguments.expect_unready:
        assert request(opener, "/api/ready", expected=(503,)) == {"status": "unavailable"}
        print("OK: Gunicorn devuelve 503 antes de inicializar el esquema.")
        return
    assert request(opener, "/api/ready")["status"] == "ok"
    store = app.extensions["identity"]
    suffix = uuid.uuid4().hex[:10]
    password = secrets.token_urlsafe(24)
    owner = store.create_user({"fullName": "Prueba Docker", "email": suffix + "@owner.test", "password": password, "householdName": "Hogar Docker"})
    other = store.create_user({"fullName": "Otro hogar", "email": suffix + "@other.test", "password": password, "householdName": "Otro Docker"})
    store.create_user({"fullName": "Operador Docker", "email": suffix + "@operator.test", "password": password}, role="operator")
    device_id = "docker-" + suffix
    device = store.register_device(owner["householdId"], {"deviceId": device_id, "name": "Sensor Docker"})
    payload = {"deviceId": device_id, "batteryLevel": 25, "voltage": 12.4, "currentA": 2, "loadPowerW": 50, "solarPowerW": 10, "netPowerW": 40, "availableEnergyWh": 90, "householdId": other["householdId"]}
    token = request(opener, "/api/auth/login", {"email": suffix + "@owner.test", "password": password, "profile": "client"})["token"]
    owner_headers = {"Authorization": "Bearer " + token}
    request(opener, "/api/telemetry", payload, expected=(401,))
    direct = request(opener, "/api/telemetry", payload, {"X-Device-Key": device["deviceKey"]})["data"]
    assert 0 <= direct["estimatedAutonomyHours"] <= 99.99
    latest = request(opener, "/api/telemetry/latest", headers=owner_headers)["data"]
    assert latest["id"] == direct["id"]
    other_token = request(opener, "/api/auth/login", {"email": suffix + "@other.test", "password": password, "profile": "client"})["token"]
    assert request(opener, "/api/telemetry/latest", headers={"Authorization": "Bearer " + other_token})["data"] is None
    operator = request(opener, "/api/auth/login", {"email": suffix + "@operator.test", "password": password, "profile": "operator"})
    assert "token" not in operator
    assert request(opener, f"/api/operator/households/{owner['householdId']}/history?period=7d")["readings"]
    producer = KafkaProducer(bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS)
    try:
        producer.send(Config.KAFKA_TELEMETRY_TOPIC, key=device_id.encode(), value=b"not-json").get(timeout=15)
    finally:
        producer.close()
    request(opener, "/api/telemetry/broker", {**payload, "sequenceNumber": 987654}, {"X-Device-Key": device["deviceKey"]}, expected=(200, 202))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        latest = request(opener, "/api/telemetry/latest", headers=owner_headers)["data"]
        if latest["id"] != direct["id"]:
            break
    else:
        raise AssertionError("El consumidor no persistio el mensaje Kafka en 20 segundos")
    rows = store.query("SELECT household_id FROM telemetry WHERE device_id=%s", (device_id,))
    assert len(rows) == 2
    assert all(row["household_id"] == owner["householdId"] for row in rows)
    print("OK: HTTP/Gunicorn, login, cookie de operador, aislamiento por hogar, IA y Kafka->MySQL.")
    print("OK: Kafka rechazo JSON invalido y proceso el mensaje valido posterior.")


if __name__ == "__main__":
    main()