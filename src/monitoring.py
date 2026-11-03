import math
from datetime import datetime

from src.aplicacion.dtos.telemetry_request import TelemetryRequest
from src.aplicacion.services.telemetry_service import TelemetryService
from src.dominio.exceptions import ValidationException


def reading_quality(reading, stale_seconds=120):
    if not reading:
        return {"state": "empty", "valid": False, "ageSeconds": None, "staleAfterSeconds": stale_seconds}
    fields = ("batteryLevel", "voltage", "loadPowerW", "solarPowerW", "estimatedAutonomyHours", "availabilityIndex")
    valid = all(isinstance(reading.get(field), (int, float)) and
                math.isfinite(reading[field]) for field in fields)
    valid = valid and 0 <= reading["batteryLevel"] <= 100 and reading["voltage"] > 0
    valid = valid and 0 <= reading["availabilityIndex"] <= 100
    valid = valid and all(reading[field] >= 0 for field in ("loadPowerW", "solarPowerW", "estimatedAutonomyHours"))
    valid = valid and reading.get("operationalState") != "SENSOR_FAILURE" and reading.get("alertLevel") != "ERROR"
    try:
        created = datetime.fromisoformat(reading["createdAt"])
        now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
        age = (now - created).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = None
    if age is None or age < -60:
        valid = False
    return {"state": "invalid" if not valid else "stale" if age > stale_seconds else "live",
            "valid": valid, "ageSeconds": max(0, round(age)) if age is not None else None,
            "staleAfterSeconds": stale_seconds}


def alerts_for(reading, max_load_w=1000):
    quality = reading_quality(reading)
    if not reading:
        return []
    if not quality["valid"]:
        return [{"type": "invalid_reading", "severity": "high", "title": "Lectura no valida o incompleta",
                 "recommendation": "Revisa los sensores y la comunicacion antes de tomar decisiones."}]
    alerts = []
    battery = reading["batteryLevel"]
    if battery <= 15:
        alerts.append({"type": "critical_battery", "severity": "high", "title": "Bateria critica",
                       "recommendation": "Desconecta cargas no esenciales y conserva energia para lo indispensable."})
    elif battery < 30:
        alerts.append({"type": "low_battery", "severity": "medium", "title": "Bateria baja",
                       "recommendation": "Reduce el consumo y programa equipos cuando haya aporte solar."})
    if reading["loadPowerW"] > max_load_w or reading.get("operationalState") == "HIGH_BASIC_HOME_DEMAND":
        alerts.append({"type": "overconsumption", "severity": "high", "title": "Sobreconsumo",
                       "recommendation": f"Evita cargas simultaneas. El umbral configurado es {max_load_w:g} W."})
    if reading["estimatedAutonomyHours"] < 2 and reading["loadPowerW"] > reading["solarPowerW"]:
        alerts.append({"type": "low_autonomy", "severity": "medium", "title": "Autonomia reducida",
                       "recommendation": "Prioriza refrigeracion, iluminacion y comunicaciones; reduce otras cargas."})
    if not alerts and reading.get("alertLevel") in {"LOW", "MEDIUM", "HIGH"}:
        alerts.append({"type": "ai_alert", "severity": {"LOW": "low", "MEDIUM": "medium", "HIGH": "high"}[reading["alertLevel"]],
                       "title": "Alerta del analisis energetico", "recommendation": reading.get("recommendation") or "Revisa el sistema."})
    return alerts


class TelemetryIngestion:
    def __init__(self, identity, repository, ai_service, max_load_w=1000):
        self.identity = identity
        self.repository = repository
        self.ai_service = ai_service
        self.max_load_w = max_load_w

    def save_payload(self, payload, device_key=None):
        household_id = self.identity.authenticate_device(payload, device_key)
        telemetry_request = TelemetryRequest.from_dict(payload)
        required = (telemetry_request.battery_level, telemetry_request.voltage, telemetry_request.current_a,
                    telemetry_request.load_power_w, telemetry_request.solar_power_w, telemetry_request.available_energy_wh)
        if any(value is None or value < 0 for value in required):
            raise ValidationException("La lectura debe incluir bateria, voltaje, corriente, consumo, solar y energia no negativos")
        if telemetry_request.battery_level > 100 or telemetry_request.voltage <= 0:
            raise ValidationException("La bateria debe estar entre 0 y 100 y el voltaje debe ser positivo")
        service = TelemetryService(self.repository.for_household(household_id), self.ai_service)
        saved = service.saveTelemetry(telemetry_request)
        return saved