import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, abort, current_app, g, jsonify, request
from mysql.connector import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def text(payload, field, maximum=120, required=True):
    value = payload.get(field, "")
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        abort(400, description=f"Campo no valido: {field}")
    return value.strip()


def credentials(payload):
    email = text(payload, "email", 190).lower()
    password = payload.get("password")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        abort(400, description="Introduce un correo valido")
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        abort(400, description="La contrasena debe tener entre 10 y 128 caracteres")
    return email, password


class IdentityStore:
    def __init__(self, database):
        self.database = database
        self.dummy_hash = generate_password_hash(secrets.token_urlsafe(32))

    def query(self, sql, params=(), one=False, write=False):
        with self.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(sql, params)
                if write:
                    return cursor.lastrowid
                return cursor.fetchone() if one else cursor.fetchall()
            finally:
                cursor.close()

    def create_user(self, payload, role="client"):
        email, password = credentials(payload)
        name = text(payload, "fullName")
        household_name = text(payload, "householdName") if role == "client" else None
        address = text(payload, "address", 255, False)
        password_hash = generate_password_hash(password)
        try:
            with self.database.connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    cursor.execute(
                        "INSERT INTO users (full_name,email,password_hash,role) VALUES (%s,%s,%s,%s)",
                        (name, email, password_hash, role),
                    )
                    user_id = cursor.lastrowid
                    household_id = None
                    if role == "client":
                        cursor.execute(
                            "INSERT INTO households (user_id,name,address) VALUES (%s,%s,%s)",
                            (user_id, household_name, address),
                        )
                        household_id = cursor.lastrowid
                finally:
                    cursor.close()
        except IntegrityError:
            abort(409, description="El correo ya esta registrado")
        return {"id": user_id, "householdId": household_id}

    def authenticate_device(self, payload, key=None):
        if not isinstance(payload, dict):
            abort(400, description="Se requiere un objeto JSON")
        device_id = text(payload, "deviceId", 100)
        key = key or payload.get("deviceKey")
        if not isinstance(key, str) or len(key) > 256:
            abort(401, description="Falta la clave del dispositivo")
        device = self.query(
            "SELECT d.* FROM devices d JOIN households h ON h.id=d.household_id "
            "JOIN users u ON u.id=h.user_id WHERE d.device_id=%s AND d.active=1 AND u.active=1",
            (device_id,), one=True,
        )
        if not device or not hmac.compare_digest(device["key_hash"], digest(key)):
            abort(401, description="Dispositivo no autorizado")
        return device["household_id"]

    def register_device(self, household_id, payload):
        device_id = text(payload, "deviceId", 100)
        name = text(payload, "name")
        key = secrets.token_urlsafe(32)
        try:
            with self.database.connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    cursor.execute(
                        "INSERT INTO devices (device_id,household_id,name,key_hash) VALUES (%s,%s,%s,%s)",
                        (device_id, household_id, name, digest(key)),
                    )
                    if payload.get("claimLegacy") is True:
                        cursor.execute(
                            "UPDATE telemetry SET household_id=%s WHERE device_id=%s AND household_id IS NULL",
                            (household_id, device_id),
                        )
                finally:
                    cursor.close()
        except IntegrityError:
            abort(409, description="El dispositivo ya esta asignado; no se permite mover su historial")
        return {"deviceId": device_id, "deviceKey": key}


def authenticated(role=None):
    def decorate(callback):
        @wraps(callback)
        def wrapped(*args, **kwargs):
            store = current_app.extensions["identity"]
            authorization = request.headers.get("Authorization", "")
            bearer = authorization.startswith("Bearer ")
            token = authorization[7:] if bearer else request.cookies.get("energy_session", "")
            if not token or len(token) > 256:
                abort(401, description="Inicia sesion para continuar")
            user = store.query(
                "SELECT u.id,u.full_name,u.email,u.role,h.id AS household_id,s.csrf_hash "
                "FROM auth_sessions s JOIN users u ON u.id=s.user_id "
                "LEFT JOIN households h ON h.user_id=u.id "
                "WHERE s.token_hash=%s AND s.expires_at>%s AND u.active=1",
                (digest(token), datetime.now(timezone.utc).replace(tzinfo=None)), one=True,
            )
            if not user:
                abort(401, description="La sesion ha caducado")
            if role and user["role"] != role:
                abort(403, description="Tu perfil no tiene acceso")
            if not bearer and request.method not in {"GET", "HEAD", "OPTIONS"}:
                csrf = request.headers.get("X-CSRF-Token", "")
                if not hmac.compare_digest(user["csrf_hash"], digest(csrf)):
                    abort(403, description="Solicitud de sesion no valida")
            g.user = user
            g.session_hash = digest(token)
            return callback(*args, **kwargs)
        return wrapped
    return decorate


def public_user(user):
    return {"id": user["id"], "fullName": user["full_name"], "email": user["email"],
            "role": user["role"], "householdId": user.get("household_id")}


def create_auth_blueprint(store):
    blueprint = Blueprint("auth", __name__)

    @blueprint.post("/login")
    def login():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="Se requiere un objeto JSON")
        email = text(payload, "email", 190).lower()
        password = payload.get("password", "")
        if not isinstance(password, str) or len(password) > 128:
            abort(400, description="Credenciales no validas")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        buckets = [digest("ip:" + (request.remote_addr or "unknown")), digest("email:" + email)]
        for bucket in buckets:
            store.query(
                "INSERT INTO auth_throttle (bucket,attempts,expires_at) VALUES (%s,1,%s) "
                "ON DUPLICATE KEY UPDATE attempts=IF(expires_at<%s,1,attempts+1), "
                "expires_at=IF(expires_at<%s,VALUES(expires_at),expires_at)",
                (bucket, now + timedelta(minutes=15), now, now), write=True,
            )
            throttle = store.query("SELECT attempts FROM auth_throttle WHERE bucket=%s", (bucket,), one=True)
            if throttle["attempts"] > 20:
                abort(429, description="Demasiados intentos. Vuelve a intentarlo en 15 minutos")
        user = store.query(
            "SELECT u.*,h.id AS household_id FROM users u LEFT JOIN households h ON h.user_id=u.id WHERE email=%s",
            (email,), one=True,
        )
        valid = check_password_hash(user["password_hash"] if user else store.dummy_hash, password)
        if not valid or not user or not user["active"]:
            abort(401, description="Correo o contrasena incorrectos")
        expected_role = payload.get("profile")
        if expected_role not in {"client", "operator"} or user["role"] != expected_role:
            abort(403, description="La cuenta no tiene el perfil requerido")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        hours = current_app.config.get("AUTH_SESSION_HOURS", 8)
        store.query("DELETE FROM auth_sessions WHERE expires_at<=%s", (now,), write=True)
        store.query("DELETE FROM auth_throttle WHERE expires_at<=%s", (now,), write=True)
        store.query(
            "INSERT INTO auth_sessions (token_hash,user_id,csrf_hash,expires_at) VALUES (%s,%s,%s,%s)",
            (digest(token), user["id"], digest(csrf), now + timedelta(hours=hours)), write=True,
        )
        response_data = {"user": public_user(user), "csrfToken": csrf, "expiresIn": hours * 3600}
        if expected_role == "client":
            response_data["token"] = token
        response = jsonify(response_data)
        if expected_role == "operator":
            response.set_cookie("energy_session", token, max_age=hours * 3600,
                                httponly=True, samesite=current_app.config.get("AUTH_COOKIE_SAMESITE", "Strict"),
                                secure=current_app.config.get("AUTH_COOKIE_SECURE", False), path="/api")
        return response

    @blueprint.get("/me")
    @authenticated()
    def me():
        csrf = secrets.token_urlsafe(32)
        store.query("UPDATE auth_sessions SET csrf_hash=%s WHERE token_hash=%s", (digest(csrf), g.session_hash), write=True)
        return jsonify({"user": public_user(g.user), "csrfToken": csrf})

    @blueprint.post("/logout")
    @authenticated()
    def logout():
        store.query("DELETE FROM auth_sessions WHERE token_hash=%s", (g.session_hash,), write=True)
        response = jsonify({"message": "Sesion cerrada"})
        response.delete_cookie("energy_session", path="/api", httponly=True,
                       secure=current_app.config.get("AUTH_COOKIE_SECURE", False),
                       samesite=current_app.config.get("AUTH_COOKIE_SAMESITE", "Strict"))
        return response

    return blueprint