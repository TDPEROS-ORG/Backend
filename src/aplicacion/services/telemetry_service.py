from datetime import datetime, timedelta
from statistics import mean
from typing import Dict, List, Optional

from src.aplicacion.services.ai_autonomy_service import AiAutonomyService

from src.aplicacion.dtos.telemetry_request import TelemetryRequest
from src.dominio.entities.telemetry import Telemetry
from src.dominio.exceptions import ValidationException
from src.dominio.repositories.telemetry_repository import TelemetryRepository


class TelemetryService:
    ALLOWED_ALERT_LEVELS = {"NONE", "LOW", "MEDIUM", "HIGH", "ERROR"}

    ALLOWED_OPERATIONAL_STATES = {
        "NORMAL_OPERATION",
        "LOW_BATTERY",
        "CRITICAL_BATTERY",
        "LOW_AUTONOMY",
        "CHARGING",
        "STANDBY",
        # Estados antiguos mantenidos por compatibilidad con datos previos.
        "WARNING_BATTERY",
        "HIGH_BASIC_HOME_DEMAND",
        "SENSOR_FAILURE",
    }

    PERIOD_CONFIG = {
        "today": {
            "label": "Hoy",
            "days": 1,
            "description": "Vista diaria: muestra la disponibilidad estimada para el dia actual y el ultimo punto actualizado.",
            "time_label": "Ultimo registro",
        },
        "7d": {
            "label": "7 dias",
            "days": 7,
            "description": "Vista semanal: compara los ultimos 7 dias y ayuda a detectar variaciones de consumo recurrentes.",
            "time_label": "Promedio semanal",
        },
        "30d": {
            "label": "30 dias",
            "days": 30,
            "description": "Vista mensual: resume los ultimos 30 dias para evaluar estabilidad, autonomia y aporte de cada fuente.",
            "time_label": "Promedio mensual",
        },
    }

    def __init__(self, telemetry_repository: TelemetryRepository, ai_service: Optional[AiAutonomyService] = None):
        self.telemetry_repository = telemetry_repository
        self.ai_service = ai_service

    def saveTelemetry(self, request: TelemetryRequest) -> Telemetry:
        if self.ai_service is not None:
            enriched_payload = self.ai_service.enrich(request.to_payload())
            request = TelemetryRequest.from_dict(enriched_payload)

        self._validate_request(request)
        telemetry = request.to_entity(created_at=datetime.now())
        return self.telemetry_repository.save(telemetry)

    def enrichTelemetry(self, payload: Dict, include_diagnostics: bool = False) -> Dict:
        if self.ai_service is None:
            raise ValidationException("AI service is not configured")
        return self.ai_service.enrich(payload, include_diagnostics=include_diagnostics)

    def getAiHealth(self) -> Dict:
        if self.ai_service is None:
            return {"status": "not_configured"}
        return self.ai_service.health()

    def getTelemetryList(self, limit: int = 50) -> List[Dict]:
        records = self.telemetry_repository.find_recent(limit=limit)
        return [self._telemetry_to_dict(record) for record in records]

    def getLatestTelemetry(self) -> Optional[Dict]:
        latest = self.telemetry_repository.find_latest()
        if latest is None:
            return None
        return self._telemetry_to_dict(latest)

    def getSummary(self) -> Dict:
        latest = self.telemetry_repository.find_latest()

        if latest is None:
            return {
                "online": False,
                "availability": 0,
                "batteryLevel": 0,
                "estimatedAutonomy": "Sin datos",
                "lastUpdate": "Sin registros",
                "statusLabel": "Sin datos",
                "operationalState": None,
                "alertLevel": None,
                "messageTitle": "Aun no hay telemetria registrada.",
                "messageText": "Ejecuta el simulador o envia datos al endpoint POST /api/telemetry.",
                "sourceMessage": "Esperando datos desde el sistema IoT virtual.",
            }

        from src.config import Config
        from src.monitoring import reading_quality

        quality = reading_quality(self._telemetry_to_dict(latest), Config.TELEMETRY_STALE_SECONDS)
        availability = self._round_percentage(
            latest.availability_index
            if latest.availability_index is not None
            else latest.battery_level
        )
        battery_level = self._round_percentage(latest.battery_level)

        return {
            "online": quality["state"] == "live",
            "quality": quality,
            "availability": availability if quality["valid"] else 0,
            "batteryLevel": battery_level if quality["valid"] else 0,
            "estimatedAutonomy": self._format_hours(latest.estimated_autonomy_hours) if quality["valid"] else "Sin datos",
            "lastUpdate": latest.created_at.strftime("%d/%m/%Y %H:%M:%S") if latest.created_at else "Sin fecha",
            "statusLabel": self._status_label(latest) if quality["state"] == "live" else "Desactualizado" if quality["state"] == "stale" else "Lectura invalida",
            "operationalState": latest.operational_state,
            "alertLevel": latest.alert_level,
            "messageTitle": self._summary_title(latest) if quality["state"] == "live" else "No hay una lectura actual y confiable.",
            "messageText": self._summary_text(latest) if quality["state"] == "live" else "Revisa la fecha de la lectura y la conexion del dispositivo antes de tomar decisiones.",
            "sourceMessage": "Datos actualizados desde Apache Kafka, procesados con IA y almacenados en MySQL.",
        }

    def getDetail(self, period: str = "today") -> Dict:
        normalized_period = self._normalize_period(period)
        config = self.PERIOD_CONFIG[normalized_period]
        start_date = datetime.now() - timedelta(days=config["days"])
        if normalized_period == "today":
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        records = self.telemetry_repository.find_since(start_date=start_date, limit=1000)

        if not records:
            return self._empty_detail_response(config)

        latest = records[-1]
        availability_values = [
            self._availability_value(record)
            for record in records
            if self._availability_value(record) is not None
        ]
        battery_values = [
            record.battery_level for record in records if record.battery_level is not None
        ]
        autonomy_values = [
            record.estimated_autonomy_hours
            for record in records
            if record.estimated_autonomy_hours is not None
        ]

        value = self._round_percentage(mean(availability_values)) if availability_values else 0
        battery = self._round_percentage(mean(battery_values)) if battery_values else 0
        autonomy = self._format_hours(mean(autonomy_values)) if autonomy_values else "Sin datos"

        if normalized_period == "today":
            value = self._round_percentage(self._availability_value(latest))
            battery = self._round_percentage(latest.battery_level)
            autonomy = self._format_hours(latest.estimated_autonomy_hours)

        return {
            "period": config["label"],
            "value": value,
            "battery": battery,
            "autonomy": autonomy,
            "time": self._format_time(latest.created_at) if normalized_period == "today" else config["time_label"],
            "description": config["description"],
            "systemStatus": self._status_label(latest),
            "sources": self._calculate_sources(records),
            "chartPoints": self._build_chart_points(records),
        }

    def getRecommendations(self) -> Dict:
        latest = self.telemetry_repository.find_latest()

        if latest is None:
            return {
                "title": "Aun no hay datos para evaluar recomendaciones.",
                "text": "Cuando ingresen registros de telemetria, se mostraran consejos para el hogar.",
                "recommendations": self._base_recommendations(),
                "tip": "Ejecuta el simulador para alimentar la tabla telemetry.",
            }

        if latest.operational_state == "SENSOR_FAILURE" or latest.alert_level == "ERROR":
            return {
                "title": "Revisa el sensor o la fuente de datos.",
                "text": "La telemetria indica una posible falla de sensor. Evita tomar decisiones operativas hasta recuperar lecturas confiables.",
                "recommendations": [
                    {
                        "icon": "battery",
                        "color": "blue",
                        "title": "Verifica la lectura del sistema",
                        "text": "Confirma que el modulo IoT virtual este enviando voltaje y bateria coherentes.",
                        "details": [
                            "Reinicia el simulador si los datos quedaron congelados.",
                            "Valida que voltage sea mayor a 0 cuando el estado no sea SENSOR_FAILURE.",
                        ],
                    },
                    *self._base_recommendations(),
                ],
                "tip": "Una lectura de sensor inconsistente puede afectar el calculo de disponibilidad.",
            }

        if (latest.battery_level or 0) < 30 or latest.alert_level == "HIGH" or latest.operational_state == "LOW_AUTONOMY":
            return {
                "title": "Disponibilidad limitada: prioriza consumos esenciales.",
                "text": "El sistema registra bateria baja o alerta alta. Conviene reducir demanda no critica.",
                "recommendations": [
                    {
                        "icon": "plug",
                        "color": "green",
                        "title": "Usa solo dispositivos esenciales",
                        "text": "Prioriza iluminacion, comunicacion, refrigeracion y ventilacion basica.",
                        "details": [
                            "Evita televisores, herramientas electricas o equipos secundarios.",
                            "Desconecta cargadores y equipos en espera mientras la bateria se recupera.",
                        ],
                    },
                    {
                        "icon": "clock",
                        "color": "yellow",
                        "title": "Mueve cargas altas a horas solares",
                        "text": "Usa equipos de alto consumo cuando exista mayor aporte solar.",
                        "details": [
                            "Programa lavadora, bomba de agua o herramientas entre media manana y tarde.",
                            "No enciendas varias cargas altas al mismo tiempo.",
                        ],
                    },
                    {
                        "icon": "battery",
                        "color": "blue",
                        "title": "Protege la bateria",
                        "text": "Evita descargas profundas y conserva energia para usos criticos.",
                        "details": [
                            "Reduce iluminacion no esencial.",
                            "Monitorea la autonomia estimada en la pantalla de detalle.",
                        ],
                    },
                ],
                "tip": "Cuando la bateria baja, pequenas reducciones de consumo prolongan la autonomia disponible.",
            }

        return {
            "title": "Buen trabajo: tu sistema mantiene energia disponible.",
            "text": "Sigue estos consejos para conservar autonomia y estabilidad en el hogar.",
            "recommendations": self._base_recommendations(),
            "tip": "Pequenas acciones diarias ayudan a mantener la energia disponible para tu hogar.",
        }


    def getMobileDashboard(self) -> Dict:
        """Endpoint agregado para la app movil.

        Devuelve un estado ya interpretado para no obligar al frontend a mostrar
        valores tecnicos crudos como autonomy=99.99h cuando no hay descarga neta.
        """
        records = self.telemetry_repository.find_recent(limit=2)
        latest = records[0] if records else None
        previous = records[1] if len(records) > 1 else None

        if latest is None:
            return {
                "online": False,
                "refreshIntervalSeconds": 10,
                "lastUpdate": "Sin registros",
                "lastUpdatedAt": None,
                "latest": None,
                "summary": self.getSummary(),
                "autonomy": {
                    "display": "Sin datos",
                    "valueHours": None,
                    "isCapped": False,
                    "explanation": "Ejecuta el simulador para recibir telemetria.",
                },
                "energyFlow": {
                    "loadPowerW": 0,
                    "solarPowerW": 0,
                    "netPowerW": 0,
                    "currentA": 0,
                    "balanceLabel": "Sin datos",
                    "balanceText": "Esperando mediciones del sistema IoT virtual.",
                    "balanceDirection": "unknown",
                },
                "change": {
                    "hasPrevious": False,
                    "severity": "none",
                    "title": "Sin cambios detectados",
                    "text": "Aun no hay registros suficientes para comparar.",
                },
            }

        latest_dict = self._telemetry_to_dict(latest)
        energy_flow = self._energy_flow(latest)
        autonomy_info = self._autonomy_info(latest)
        change_info = self._change_info(latest, previous)
        summary = self.getSummary()

        # Campos redundantes pero utiles para consumir rapido desde mobile.
        summary["energyFlow"] = energy_flow
        summary["autonomyInfo"] = autonomy_info
        summary["change"] = change_info

        return {
            "online": True,
            "refreshIntervalSeconds": 10,
            "lastUpdate": self._format_time(latest.created_at),
            "lastUpdatedAt": latest.created_at.isoformat() if latest.created_at else None,
            "latest": latest_dict,
            "summary": summary,
            "autonomy": autonomy_info,
            "energyFlow": energy_flow,
            "change": change_info,
        }

    def _energy_flow(self, telemetry: Telemetry) -> Dict:
        load = round(float(telemetry.load_power_w or 0), 2)
        solar = round(float(telemetry.solar_power_w or 0), 2)
        net = round(float(telemetry.net_power_w or (load - solar)), 2)
        current = round(float(telemetry.current_a or 0), 2)

        if net > 0.05:
            return {
                "loadPowerW": load,
                "solarPowerW": solar,
                "netPowerW": net,
                "currentA": current,
                "balanceLabel": "Bateria entregando energia",
                "balanceText": f"El hogar consume {load:.2f} W y el aporte solar es {solar:.2f} W. La bateria cubre {net:.2f} W netos.",
                "balanceDirection": "discharging",
            }
        if solar > 0.05 and net < -0.05:
            return {
                "loadPowerW": load,
                "solarPowerW": solar,
                "netPowerW": net,
                "currentA": current,
                "balanceLabel": "Recuperando energia",
                "balanceText": f"No hay descarga neta: el aporte solar ({solar:.2f} W) supera el consumo actual ({load:.2f} W).",
                "balanceDirection": "recovering",
            }
        if load <= 0.05 and solar <= 0.05:
            return {
                "loadPowerW": load,
                "solarPowerW": solar,
                "netPowerW": net,
                "currentA": current,
                "balanceLabel": "Sistema en espera",
                "balanceText": "No se detecta consumo ni aporte solar relevante en este momento.",
                "balanceDirection": "standby",
            }
        return {
            "loadPowerW": load,
            "solarPowerW": solar,
            "netPowerW": net,
            "currentA": current,
            "balanceLabel": "Balance equilibrado",
            "balanceText": "El consumo y el aporte solar estan casi equilibrados.",
            "balanceDirection": "balanced",
        }

    def _autonomy_info(self, telemetry: Telemetry) -> Dict:
        hours = telemetry.estimated_autonomy_hours
        net = float(telemetry.net_power_w or 0)
        solar = float(telemetry.solar_power_w or 0)
        load = float(telemetry.load_power_w or 0)
        capped = hours is not None and float(hours) >= 99.0 and net <= 0.05

        if capped and solar > 0.05:
            return {
                "display": "Sin descarga neta",
                "valueHours": round(float(hours), 2),
                "isCapped": True,
                "explanation": "La bateria no se esta descargando porque el aporte solar cubre el consumo actual.",
            }
        if capped and load <= 0.05:
            return {
                "display": "En espera",
                "valueHours": round(float(hours), 2),
                "isCapped": True,
                "explanation": "No hay consumo activo; por eso no se calcula agotamiento real de bateria.",
            }
        return {
            "display": self._format_hours(hours),
            "valueHours": round(float(hours), 2) if hours is not None else None,
            "isCapped": False,
            "explanation": "Autonomia estimada segun energia disponible y consumo neto actual.",
        }

    def _change_info(self, latest: Telemetry, previous: Optional[Telemetry]) -> Dict:
        if previous is None:
            return {
                "hasPrevious": False,
                "severity": "none",
                "title": "Primer registro disponible",
                "text": "Cuando lleguen nuevos datos, la app explicara si la autonomia cambia por consumo, carga solar o bateria.",
            }

        battery_delta = round(float(latest.battery_level or 0) - float(previous.battery_level or 0), 2)
        load_delta = round(float(latest.load_power_w or 0) - float(previous.load_power_w or 0), 2)
        solar_delta = round(float(latest.solar_power_w or 0) - float(previous.solar_power_w or 0), 2)
        net_delta = round(float(latest.net_power_w or 0) - float(previous.net_power_w or 0), 2)
        autonomy_delta = self._safe_autonomy_delta(latest, previous)
        state_changed = latest.operational_state != previous.operational_state
        alert_changed = latest.alert_level != previous.alert_level

        severity = "none"
        title = "Estado estable"
        text = "No se detectaron cambios importantes en el consumo, carga solar o nivel de bateria."

        if alert_changed or latest.alert_level in {"HIGH", "ERROR"}:
            severity = "critical" if latest.alert_level in {"HIGH", "ERROR"} else "warning"
            title = "Cambio importante de alerta"
            text = f"La alerta cambio de {previous.alert_level or 'sin alerta'} a {latest.alert_level or 'sin alerta'}. Revisa bateria, consumo y autonomia."
        elif state_changed:
            severity = "warning"
            title = "Cambio de estado operativo"
            text = f"El estado paso de {previous.operational_state or 'sin estado'} a {latest.operational_state or 'sin estado'}."
        elif load_delta >= 5 and (autonomy_delta is None or autonomy_delta < -0.2):
            severity = "warning"
            title = "Subio el consumo actual"
            text = f"El consumo aumento {load_delta:.2f} W; por eso la autonomia puede disminuir."
        elif load_delta <= -5 and (autonomy_delta is None or autonomy_delta > 0.2):
            severity = "info"
            title = "Bajo el consumo actual"
            text = f"El consumo bajo {abs(load_delta):.2f} W; eso ayuda a extender la autonomia."
        elif solar_delta >= 5 or (latest.net_power_w or 0) < -0.05:
            severity = "info"
            title = "Aporte solar favorable"
            text = "El aporte solar esta cubriendo el consumo o ayudando a recuperar energia."
        elif battery_delta <= -5:
            severity = "warning"
            title = "Bajo el nivel de bateria"
            text = f"La bateria disminuyo {abs(battery_delta):.2f} puntos porcentuales respecto al registro anterior."

        return {
            "hasPrevious": True,
            "severity": severity,
            "title": title,
            "text": text,
            "batteryDelta": battery_delta,
            "loadPowerDeltaW": load_delta,
            "solarPowerDeltaW": solar_delta,
            "netPowerDeltaW": net_delta,
            "autonomyDeltaHours": autonomy_delta,
            "stateChanged": state_changed,
            "alertChanged": alert_changed,
        }

    def _safe_autonomy_delta(self, latest: Telemetry, previous: Telemetry) -> Optional[float]:
        latest_hours = latest.estimated_autonomy_hours
        previous_hours = previous.estimated_autonomy_hours
        if latest_hours is None or previous_hours is None:
            return None

        # Si alguno esta capeado por ausencia de descarga neta, la diferencia numerica
        # puede confundir; se devuelve None para que el texto use consumo/balance.
        latest_capped = float(latest_hours) >= 99.0 and float(latest.net_power_w or 0) <= 0.05
        previous_capped = float(previous_hours) >= 99.0 and float(previous.net_power_w or 0) <= 0.05
        if latest_capped or previous_capped:
            return None
        return round(float(latest_hours) - float(previous_hours), 2)

    def _validate_request(self, request: TelemetryRequest) -> None:
        required_fields = {
            "deviceId": request.device_id,
            "batteryLevel": request.battery_level,
            "voltage": request.voltage,
            "alertLevel": request.alert_level,
            "operationalState": request.operational_state,
        }

        missing_fields = [name for name, value in required_fields.items() if value is None]
        if missing_fields:
            raise ValidationException(
                "Missing required fields: " + ", ".join(missing_fields)
            )

        if request.battery_level < 0 or request.battery_level > 100:
            raise ValidationException("batteryLevel must be between 0 and 100")

        if request.availability_index is not None:
            if request.availability_index < 0 or request.availability_index > 100:
                raise ValidationException("availabilityIndex must be between 0 and 100")

        if request.alert_level not in self.ALLOWED_ALERT_LEVELS:
            allowed = ", ".join(sorted(self.ALLOWED_ALERT_LEVELS))
            raise ValidationException(f"alertLevel must be one of: {allowed}")

        if request.operational_state not in self.ALLOWED_OPERATIONAL_STATES:
            allowed = ", ".join(sorted(self.ALLOWED_OPERATIONAL_STATES))
            raise ValidationException(f"operationalState must be one of: {allowed}")

        if request.operational_state != "SENSOR_FAILURE" and request.voltage <= 0:
            raise ValidationException("voltage must be greater than 0 except SENSOR_FAILURE")

    def _telemetry_to_dict(self, telemetry: Telemetry) -> Dict:
        return {
            "id": telemetry.id,
            "sequenceNumber": telemetry.sequence_number,
            "deviceId": telemetry.device_id,
            "scenarioProfile": telemetry.scenario_profile,
            "energyStorageType": telemetry.energy_storage_type,
            "communicationMode": telemetry.communication_mode,
            "uptimeSeconds": telemetry.uptime_seconds,
            "daySegment": telemetry.day_segment,
            "batteryLevel": telemetry.battery_level,
            "voltage": telemetry.voltage,
            "currentA": telemetry.current_a,
            "loadPowerW": telemetry.load_power_w,
            "solarPowerW": telemetry.solar_power_w,
            "netPowerW": telemetry.net_power_w,
            "availableEnergyWh": telemetry.available_energy_wh,
            "estimatedAutonomyHours": telemetry.estimated_autonomy_hours,
            "availabilityIndex": telemetry.availability_index,
            "loadProfile": telemetry.load_profile,
            "activeLoads": self._parse_active_loads(telemetry.active_loads),
            "operationalState": telemetry.operational_state,
            "alertLevel": telemetry.alert_level,
            "recommendation": telemetry.recommendation,
            "createdAt": telemetry.created_at.astimezone().isoformat() if telemetry.created_at else None,
        }

    def _parse_active_loads(self, value: Optional[str]) -> List[str]:
        if not value:
            return []
        return [item.strip() for item in str(value).split(",") if item.strip()]

    def _empty_detail_response(self, config: Dict) -> Dict:
        return {
            "period": config["label"],
            "value": 0,
            "battery": 0,
            "autonomy": "Sin datos",
            "time": "Sin registros",
            "description": config["description"],
            "systemStatus": "Sin datos",
            "sources": {"solar": "0%", "batteries": "0%", "grid": "0%"},
            "chartPoints": [
                {"label": "00:00", "value": 0},
                {"label": "06:00", "value": 0},
                {"label": "12:00", "value": 0},
                {"label": "18:00", "value": 0},
                {"label": "24:00", "value": 0},
            ],
        }

    def _build_chart_points(self, records: List[Telemetry]) -> List[Dict]:
        if not records:
            return self._empty_detail_response(self.PERIOD_CONFIG["today"])["chartPoints"]

        bucket_count = 5
        if len(records) <= bucket_count:
            selected = records
        else:
            step = (len(records) - 1) / (bucket_count - 1)
            selected = [records[round(index * step)] for index in range(bucket_count)]

        points = []
        for record in selected:
            value = self._round_percentage(self._availability_value(record))
            label = self._format_time(record.created_at)
            points.append({"label": label, "value": value})

        while len(points) < bucket_count:
            points.append(points[-1])

        return points

    def _calculate_sources(self, records: List[Telemetry]) -> Dict[str, str]:
        solar_values = [record.solar_power_w or 0 for record in records]
        load_values = [record.load_power_w or 0 for record in records]

        avg_solar = mean(solar_values) if solar_values else 0
        avg_load = mean(load_values) if load_values else 0
        total = max(avg_solar + avg_load, 1)

        solar_pct = round((avg_solar / total) * 100)
        batteries_pct = max(0, min(100, 100 - solar_pct))
        grid_pct = 0

        return {
            "solar": f"{solar_pct}%",
            "batteries": f"{batteries_pct}%",
            "grid": f"{grid_pct}%",
        }

    def _normalize_period(self, period: str) -> str:
        if not period:
            return "today"

        value = period.strip().lower()
        aliases = {
            "hoy": "today",
            "today": "today",
            "7": "7d",
            "7d": "7d",
            "7dias": "7d",
            "7 dias": "7d",
            "7 días": "7d",
            "30": "30d",
            "30d": "30d",
            "30dias": "30d",
            "30 dias": "30d",
            "30 días": "30d",
        }

        if value not in aliases:
            raise ValidationException("period must be one of: today, 7d, 30d")

        return aliases[value]

    def _availability_value(self, telemetry: Telemetry) -> Optional[float]:
        if telemetry.availability_index is not None:
            return telemetry.availability_index
        return telemetry.battery_level

    def _round_percentage(self, value: Optional[float]) -> int:
        if value is None:
            return 0
        return max(0, min(100, round(float(value))))

    def _format_hours(self, hours: Optional[float]) -> str:
        if hours is None:
            return "Sin datos"

        total_minutes = max(0, round(float(hours) * 60))
        hour_part = total_minutes // 60
        minute_part = total_minutes % 60
        return f"{hour_part} h {minute_part:02d} min"

    def _format_time(self, value: Optional[datetime]) -> str:
        if value is None:
            return "Sin fecha"
        return value.strftime("%H:%M")

    def _status_label(self, telemetry: Telemetry) -> str:
        if telemetry.operational_state == "SENSOR_FAILURE" or telemetry.alert_level == "ERROR":
            return "Error"
        if telemetry.operational_state in {"CRITICAL_BATTERY", "LOW_AUTONOMY"}:
            return "Critico"
        if telemetry.operational_state in {"LOW_BATTERY", "WARNING_BATTERY", "HIGH_BASIC_HOME_DEMAND"}:
            return "Atencion"
        if telemetry.operational_state in {"CHARGING", "STANDBY"}:
            return "Estable"
        return "Bueno"

    def _summary_title(self, telemetry: Telemetry) -> str:
        status = self._status_label(telemetry)
        if status == "Error":
            return "Hay una posible falla en la lectura del sistema."
        if status == "Critico":
            return "Tu sistema tiene disponibilidad energetica critica."
        if status == "Atencion":
            return "Tu sistema requiere atencion de consumo."
        return "Tu sistema tiene buena disponibilidad de energia."

    def _summary_text(self, telemetry: Telemetry) -> str:
        status = self._status_label(telemetry)
        if telemetry.recommendation:
            return telemetry.recommendation
        if status == "Error":
            return "Revisa el sensor o la conexion del modulo IoT virtual."
        if status == "Critico":
            return "Reduce cargas no esenciales y conserva energia para usos prioritarios."
        if status == "Atencion":
            return "Evita consumos altos y monitorea la autonomia estimada."
        return "Puedes usar tus dispositivos con normalidad."

    def _base_recommendations(self) -> List[Dict]:
        return [
            {
                "icon": "plug",
                "color": "green",
                "title": "Usa dispositivos esenciales",
                "text": "Prioriza iluminacion, refrigerador, carga de dispositivos y ventilacion.",
                "details": [
                    "Mantén conectados solo los equipos necesarios para seguridad, comunicacion y conservacion de alimentos.",
                    "Apaga televisores, consolas, hornos electricos o equipos secundarios mientras la autonomia sea limitada.",
                ],
            },
            {
                "icon": "clock",
                "color": "yellow",
                "title": "Evita consumos altos en horas pico",
                "text": "Usa equipos de alto consumo entre 10:00 AM y 4:00 PM si es posible.",
                "details": [
                    "Programa lavadora, plancha, bomba de agua o herramientas cuando exista mayor aporte solar.",
                    "Evita encender varios equipos de alto consumo al mismo tiempo para no acelerar la descarga.",
                ],
            },
            {
                "icon": "battery",
                "color": "blue",
                "title": "Cuida el nivel de bateria",
                "text": "Si baja de 30%, enfocate en lo indispensable.",
                "details": [
                    "Reduce iluminacion no esencial y desconecta cargadores o equipos en espera.",
                    "Si el sistema marca bateria baja, conserva energia para refrigeracion, comunicacion y ventilacion basica.",
                ],
            },
        ]
