from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Dict, Optional

from src.dominio.entities.telemetry import Telemetry
from src.dominio.exceptions import ValidationException


@dataclass(frozen=True)
class TelemetryRequest:
    sequence_number: Optional[int] = None
    device_id: Optional[str] = None
    scenario_profile: Optional[str] = None
    energy_storage_type: Optional[str] = None
    communication_mode: Optional[str] = None
    uptime_seconds: Optional[int] = None
    day_segment: Optional[str] = None
    battery_level: Optional[float] = None
    voltage: Optional[float] = None
    current_a: Optional[float] = None
    load_power_w: Optional[float] = None
    solar_power_w: Optional[float] = None
    net_power_w: Optional[float] = None
    available_energy_wh: Optional[float] = None
    estimated_autonomy_hours: Optional[float] = None
    availability_index: Optional[float] = None
    load_profile: Optional[str] = None
    active_loads: Optional[str] = None
    operational_state: Optional[str] = None
    alert_level: Optional[str] = None
    recommendation: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TelemetryRequest":
        if not isinstance(payload, dict):
            raise ValidationException("Request body must be a JSON object")

        return cls(
            sequence_number=_to_int(payload.get("sequenceNumber"), "sequenceNumber"),
            device_id=_to_str(payload.get("deviceId")),
            scenario_profile=_to_str(payload.get("scenarioProfile")),
            energy_storage_type=_to_str(payload.get("energyStorageType")),
            communication_mode=_to_str(payload.get("communicationMode")),
            uptime_seconds=_to_int(payload.get("uptimeSeconds"), "uptimeSeconds"),
            day_segment=_to_str(payload.get("daySegment")),
            battery_level=_to_float(payload.get("batteryLevel"), "batteryLevel"),
            voltage=_to_float(payload.get("voltage"), "voltage"),
            current_a=_to_float(payload.get("currentA"), "currentA"),
            load_power_w=_to_float(payload.get("loadPowerW"), "loadPowerW"),
            solar_power_w=_to_float(payload.get("solarPowerW"), "solarPowerW"),
            net_power_w=_to_float(payload.get("netPowerW"), "netPowerW"),
            available_energy_wh=_to_float(
                payload.get("availableEnergyWh"),
                "availableEnergyWh",
            ),
            estimated_autonomy_hours=_to_float(
                payload.get("estimatedAutonomyHours"),
                "estimatedAutonomyHours",
            ),
            availability_index=_to_float(
                payload.get("availabilityIndex"),
                "availabilityIndex",
            ),
            load_profile=_to_str(payload.get("loadProfile")),
            active_loads=_to_str(payload.get("activeLoads")),
            operational_state=_to_str(payload.get("operationalState")),
            alert_level=_to_str(payload.get("alertLevel")),
            recommendation=_to_str(payload.get("recommendation")),
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "sequenceNumber": self.sequence_number,
            "deviceId": self.device_id,
            "scenarioProfile": self.scenario_profile,
            "energyStorageType": self.energy_storage_type,
            "communicationMode": self.communication_mode,
            "uptimeSeconds": self.uptime_seconds,
            "daySegment": self.day_segment,
            "batteryLevel": self.battery_level,
            "voltage": self.voltage,
            "currentA": self.current_a,
            "loadPowerW": self.load_power_w,
            "solarPowerW": self.solar_power_w,
            "netPowerW": self.net_power_w,
            "availableEnergyWh": self.available_energy_wh,
            "estimatedAutonomyHours": self.estimated_autonomy_hours,
            "availabilityIndex": self.availability_index,
            "loadProfile": self.load_profile,
            "activeLoads": self.active_loads,
            "operationalState": self.operational_state,
            "alertLevel": self.alert_level,
            "recommendation": self.recommendation,
        }

    def to_entity(self, created_at: datetime) -> Telemetry:
        return Telemetry(
            sequence_number=self.sequence_number,
            device_id=self.device_id,
            scenario_profile=self.scenario_profile,
            energy_storage_type=self.energy_storage_type,
            communication_mode=self.communication_mode,
            uptime_seconds=self.uptime_seconds,
            day_segment=self.day_segment,
            battery_level=self.battery_level,
            voltage=self.voltage,
            current_a=self.current_a,
            load_power_w=self.load_power_w,
            solar_power_w=self.solar_power_w,
            net_power_w=self.net_power_w,
            available_energy_wh=self.available_energy_wh,
            estimated_autonomy_hours=self.estimated_autonomy_hours,
            availability_index=self.availability_index,
            load_profile=self.load_profile,
            active_loads=self.active_loads,
            operational_state=self.operational_state,
            alert_level=self.alert_level,
            recommendation=self.recommendation,
            created_at=created_at,
        )


def _to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        text = ",".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value).strip()
    return text if text else None


def _to_int(value: Any, field_name: str) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValidationException(f"{field_name} must be an integer") from error


def _to_float(value: Any, field_name: str) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
        if isinstance(value, bool) or not math.isfinite(parsed):
            raise ValueError("Non-finite number")
        return parsed
    except (TypeError, ValueError) as error:
        raise ValidationException(f"{field_name} must be numeric") from error
