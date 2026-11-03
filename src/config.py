import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    AUTH_SESSION_HOURS = int(os.getenv("AUTH_SESSION_HOURS", "8"))
    AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "False").lower() == "true"
    AUTH_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "Strict").capitalize()
    CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:8081,http://localhost:8082,http://127.0.0.1:8081,http://127.0.0.1:8082").split(",") if origin.strip()]
    TELEMETRY_STALE_SECONDS = int(os.getenv("TELEMETRY_STALE_SECONDS", "120"))
    MAX_LOAD_W = float(os.getenv("MAX_LOAD_W", "1000"))

    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "energy_storage_iot")

    AI_MODEL_PATH = os.getenv("AI_MODEL_PATH", str(BASE_DIR / "models" / "modelo_autonomia_residual.pkl"))
    AI_INCLUDE_DIAGNOSTICS = os.getenv("AI_INCLUDE_DIAGNOSTICS", "False").lower() == "true"

    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
    KAFKA_TELEMETRY_TOPIC = os.getenv("KAFKA_TELEMETRY_TOPIC", "rural-energy.telemetry.raw")
    KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "backend-flask-ia-consumer")
    KAFKA_AUTO_OFFSET_RESET = os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest")
    KAFKA_CLIENT_ID = os.getenv("KAFKA_CLIENT_ID", "backend-flask-ia")
