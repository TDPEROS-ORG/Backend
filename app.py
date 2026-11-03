from pathlib import Path
from datetime import date, datetime

import click
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from src.aplicacion.services.ai_autonomy_service import AiAutonomyService
from src.aplicacion.services.telemetry_service import TelemetryService
from src.config import Config
from src.controller.telemetry_controller import create_telemetry_blueprint
from src.deployment import initialize_database, verify_backend
from src.dominio.exceptions import ValidationException
from src.infraestructura.database.connection import Database
from src.infraestructura.repositories.mysql_telemetry_repository import MySqlTelemetryRepository
from src.controller.operator_controller import create_operator_blueprint
from src.monitoring import TelemetryIngestion
from src.security import IdentityStore, create_auth_blueprint


def create_app(database=None, ai_service=None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if app.config["AUTH_COOKIE_SAMESITE"] not in {"Strict", "Lax", "None"}:
        raise ValueError("AUTH_COOKIE_SAMESITE debe ser Strict, Lax o None")
    if app.config["AUTH_COOKIE_SAMESITE"] == "None" and not app.config["AUTH_COOKIE_SECURE"]:
        raise ValueError("SameSite=None requiere AUTH_COOKIE_SECURE=True")
    if not Config.CORS_ORIGINS or any("*" in origin for origin in Config.CORS_ORIGINS):
        raise ValueError("CORS_ORIGINS requiere origenes explicitos, sin comodines")
    default_json = app.json.default

    def json_value(value):
        if isinstance(value, datetime):
            return value.astimezone().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return default_json(value)

    app.json.default = json_value
    CORS(app, resources={r"/api/*": {"origins": Config.CORS_ORIGINS}}, supports_credentials=True)

    database = database or Database(Config)
    telemetry_repository = MySqlTelemetryRepository(database)
    ai_service = ai_service or AiAutonomyService(
        model_path=Config.AI_MODEL_PATH,
        include_diagnostics=Config.AI_INCLUDE_DIAGNOSTICS,
    )
    telemetry_service = TelemetryService(telemetry_repository, ai_service=ai_service)
    identity = IdentityStore(database)
    app.extensions["identity"] = identity
    app.extensions["ai"] = ai_service
    ingestion = TelemetryIngestion(identity, telemetry_repository, ai_service, Config.MAX_LOAD_W)
    app.register_blueprint(create_auth_blueprint(identity), url_prefix="/api/auth")
    app.register_blueprint(create_operator_blueprint(identity, telemetry_repository, ai_service), url_prefix="/api/operator")

    app.register_blueprint(
        create_telemetry_blueprint(telemetry_service, ingestion),
        url_prefix="/api",
    )

    @app.get("/api/ready")
    def readiness():
        try:
            return jsonify(verify_backend(identity, ai_service))
        except Exception as error:
            app.logger.warning("Backend readiness failed (%s)", type(error).__name__)
            return jsonify({"status": "unavailable"}), 503

    @app.cli.command("check-backend")
    def check_backend():
        verify_backend(identity, ai_service)
        click.echo("MySQL, esquema y modelo preparados.")

    @app.cli.command("init-db")
    @click.option("--confirm-empty", is_flag=True, help="Autoriza inicializar una base nueva o vacia.")
    def init_db(confirm_empty):
        if not confirm_empty:
            raise click.UsageError("Requiere --confirm-empty. No usar para migrar una base con datos.")
        try:
            created = initialize_database(database.config, Path(__file__).parent / "sql")
        except Exception as error:
            raise click.ClickException(str(error)) from error
        click.echo("Esquema creado." if created else "Esquema ya preparado; sin cambios.")

    web_root = Path(__file__).parent / "operator-web"

    @app.get("/")
    @app.get("/operador")
    @app.get("/operador/")
    def operator_web():
        return send_from_directory(web_root, "index.html")

    @app.get("/operador/assets/<path:filename>")
    def operator_assets(filename):
        return send_from_directory(web_root / "dist", filename)

    @app.after_request
    def secure_response(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if response.content_type.startswith("application/json"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.cli.command("create-operator")
    @click.option("--email", prompt="Correo del operador")
    @click.option("--name", prompt="Nombre completo")
    @click.password_option(confirmation_prompt=True)
    def create_operator(email, name, password):
        identity.create_user({"email": email, "fullName": name, "password": password}, role="operator")
        click.echo("Operador creado. Accede a /operador con estas credenciales.")

    @app.errorhandler(ValidationException)
    def handle_validation_error(error: ValidationException):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        return jsonify({"error": error.description}), error.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception("Unexpected backend error: %s", error)
        return jsonify({"error": "No se pudo completar la operacion. Intentalo de nuevo."}), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=Config.FLASK_HOST,
        port=Config.FLASK_PORT,
        debug=Config.FLASK_DEBUG,
    )
