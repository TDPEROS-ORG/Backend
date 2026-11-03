from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Telemetry:
    id: Optional[int] = None
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
    created_at: Optional[datetime] = None
