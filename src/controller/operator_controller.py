import secrets
from datetime import datetime, timedelta

from flask import Blueprint, abort, g, jsonify, request
from mysql.connector import IntegrityError
from werkzeug.security import generate_password_hash

from src.aplicacion.services.telemetry_service import TelemetryService
from src.config import Config
from src.monitoring import alerts_for, reading_quality
from src.security import authenticated, digest, text


def create_operator_blueprint(store, repository, ai_service):
    blueprint = Blueprint("operator", __name__)

    @blueprint.before_request
    @authenticated("operator")
    def authorize():
        return None

    def household(household_id):
        result = store.query(
            "SELECT h.*,u.full_name,u.email,u.active FROM households h JOIN users u ON u.id=h.user_id WHERE h.id=%s",
            (household_id,), one=True,
        )
        if not result:
            abort(404, description="Hogar no encontrado")
        return result

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description="Se requiere un objeto JSON")
        return data

    def current(household_id):
        service = TelemetryService(repository.for_household(household_id), ai_service)
        latest = service.getLatestTelemetry()
        return {"latest": latest, "quality": reading_quality(latest, Config.TELEMETRY_STALE_SECONDS),
                "alerts": alerts_for(latest, Config.MAX_LOAD_W)}

    def period_start():
        period = request.args.get("period", "today")
        if period not in {"today", "7d", "30d"}:
            abort(400, description="Periodo no valido")
        now = datetime.now()
        return now.replace(hour=0, minute=0, second=0, microsecond=0) if period == "today" else now - timedelta(days={"7d": 7, "30d": 30}[period])

    @blueprint.get("/households")
    def list_households():
        homes = store.query(
            "SELECT h.*,u.full_name,u.email,u.active FROM households h JOIN users u ON u.id=h.user_id ORDER BY h.id DESC"
        )
        for home in homes:
            home.update(current(home["id"]))
        return jsonify({"data": homes, "refreshIntervalSeconds": 10})

    @blueprint.post("/households")
    def create_household():
        return jsonify(store.create_user(payload())), 201

    @blueprint.get("/households/<int:household_id>")
    def get_household(household_id):
        home = household(household_id)
        home.update(current(household_id))
        home["devices"] = store.query(
            "SELECT device_id,name,active,created_at FROM devices WHERE household_id=%s ORDER BY device_id", (household_id,)
        )
        return jsonify(home)

    @blueprint.patch("/households/<int:household_id>")
    def update_household(household_id):
        home = household(household_id)
        data = payload()
        full_name = text(data, "fullName")
        name = text(data, "householdName")
        address = text(data, "address", 255, False)
        notes = text(data, "notes", 3000, False)
        active = data.get("active", True)
        if not isinstance(active, bool):
            abort(400, description="Estado no valido")
        password = data.get("password", "")
        if not isinstance(password, str) or (password and not 10 <= len(password) <= 128):
            abort(400, description="La contrasena debe tener entre 10 y 128 caracteres")
        with store.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute("UPDATE users SET full_name=%s,active=%s WHERE id=%s", (full_name, active, home["user_id"]))
                cursor.execute("UPDATE households SET name=%s,address=%s,notes=%s WHERE id=%s", (name, address, notes, household_id))
                if password:
                    cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s", (generate_password_hash(password), home["user_id"]))
                if password or not active:
                    cursor.execute("DELETE FROM auth_sessions WHERE user_id=%s", (home["user_id"],))
            finally:
                cursor.close()
        return jsonify({"message": "Perfil actualizado"})

    @blueprint.post("/households/<int:household_id>/devices")
    def add_device(household_id):
        household(household_id)
        return jsonify(store.register_device(household_id, payload())), 201

    @blueprint.patch("/households/<int:household_id>/devices/<path:device_id>")
    def update_device(household_id, device_id):
        household(household_id)
        device = store.query("SELECT device_id FROM devices WHERE household_id=%s AND device_id=%s", (household_id, device_id), one=True)
        if not device:
            abort(404, description="Dispositivo no encontrado")
        data = payload()
        if not isinstance(data.get("active"), bool):
            abort(400, description="Estado no valido")
        store.query("UPDATE devices SET active=%s WHERE household_id=%s AND device_id=%s", (data["active"], household_id, device_id), write=True)
        response = {"message": "Dispositivo actualizado"}
        if data.get("rotateKey") is True:
            key = secrets.token_urlsafe(32)
            store.query("UPDATE devices SET key_hash=%s WHERE household_id=%s AND device_id=%s", (digest(key), household_id, device_id), write=True)
            response["deviceKey"] = key
        return jsonify(response)

    @blueprint.get("/households/<int:household_id>/history")
    def history(household_id):
        household(household_id)
        start = period_start()
        bucket = "TIMESTAMP(DATE(created_at), MAKETIME(HOUR(created_at),0,0))" if request.args.get("period", "today") == "today" else "DATE(created_at)"
        data = store.query(
            f"SELECT {bucket} AS timestamp,AVG(battery_level) AS batteryLevel,AVG(availability_index) AS availabilityIndex,"
            "AVG(load_power_w) AS loadPowerW,AVG(solar_power_w) AS solarPowerW,COUNT(*) AS samples "
            "FROM telemetry WHERE household_id=%s AND created_at>=%s "
            "AND battery_level BETWEEN 0 AND 100 AND availability_index BETWEEN 0 AND 100 AND voltage>0 "
            "AND load_power_w>=0 AND solar_power_w>=0 AND estimated_autonomy_hours>=0 "
            "AND operational_state<>'SENSOR_FAILURE' AND alert_level<>'ERROR' "
            f"GROUP BY {bucket} ORDER BY timestamp", (household_id, start),
        )
        readings = store.query(
            "SELECT id,device_id AS deviceId,battery_level AS batteryLevel,voltage,current_a AS currentA,"
            "load_power_w AS loadPowerW,solar_power_w AS solarPowerW,estimated_autonomy_hours AS estimatedAutonomyHours,"
            "availability_index AS availabilityIndex,operational_state AS operationalState,alert_level AS alertLevel,"
            "created_at AS createdAt FROM telemetry WHERE household_id=%s AND created_at>=%s ORDER BY created_at DESC,id DESC LIMIT 100",
            (household_id, start),
        )
        for reading in readings:
            reading["createdAt"] = reading["createdAt"].isoformat()
            reading["quality"] = reading_quality(reading, Config.TELEMETRY_STALE_SECONDS)
        return jsonify({"trend": data, "readings": readings, "readingsLimit": 100})

    @blueprint.get("/households/<int:household_id>/incidents")
    def incidents(household_id):
        household(household_id)
        params = [household_id, period_start()]
        clauses = ["household_id=%s", "created_at>=%s"]
        for field in ("type", "status"):
            value = request.args.get(field, "")
            if value:
                clauses.append(f"{field}=%s")
                params.append(value)
        direction = "ASC" if request.args.get("sort") == "oldest" else "DESC"
        before = request.args.get("cursor", type=int)
        if before:
            clauses.append("id>%s" if direction == "ASC" else "id<%s")
            params.append(before)
        results = store.query("SELECT * FROM incidents WHERE " + " AND ".join(clauses) + f" ORDER BY id {direction} LIMIT 101", tuple(params))
        return jsonify({"data": results[:100], "nextCursor": results[99]["id"] if len(results) > 100 else None})

    @blueprint.get("/incidents/<int:incident_id>")
    def incident_detail(incident_id):
        incident = store.query("SELECT * FROM incidents WHERE id=%s", (incident_id,), one=True)
        if not incident:
            abort(404, description="Incidencia no encontrada")
        incident["events"] = store.query(
            "SELECT e.*,u.full_name FROM incident_events e JOIN users u ON u.id=e.user_id WHERE incident_id=%s ORDER BY e.id", (incident_id,)
        )
        incident["reading"] = store.query("SELECT * FROM telemetry WHERE id=%s AND household_id=%s", (incident["telemetry_id"], incident["household_id"]), one=True)
        return jsonify(incident)

    @blueprint.post("/incidents/<int:incident_id>/events")
    def record_event(incident_id):
        data = payload()
        status = data.get("status")
        if status not in {"open", "acknowledged", "resolved"}:
            abort(400, description="Estado no valido")
        note = text(data, "note", 3000)
        with store.database.connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute("SELECT id FROM incidents WHERE id=%s FOR UPDATE", (incident_id,))
                if not cursor.fetchone():
                    abort(404, description="Incidencia no encontrada")
                cursor.execute("UPDATE incidents SET status=%s WHERE id=%s", (status, incident_id))
                cursor.execute("INSERT INTO incident_events (incident_id,user_id,status,note) VALUES (%s,%s,%s,%s)", (incident_id, g.user["id"], status, note))
            finally:
                cursor.close()
        return jsonify({"message": "Seguimiento registrado"}), 201

    return blueprint