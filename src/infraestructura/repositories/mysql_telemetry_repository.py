from dataclasses import replace
from datetime import datetime
from typing import List, Optional

from src.dominio.entities.telemetry import Telemetry
from src.dominio.repositories.telemetry_repository import TelemetryRepository
from src.infraestructura.database.connection import Database


class MySqlTelemetryRepository(TelemetryRepository):
    SELECT_COLUMNS = """
        id,
        sequence_number,
        device_id,
        scenario_profile,
        energy_storage_type,
        communication_mode,
        uptime_seconds,
        day_segment,
        battery_level,
        voltage,
        current_a,
        load_power_w,
        solar_power_w,
        net_power_w,
        available_energy_wh,
        estimated_autonomy_hours,
        availability_index,
        load_profile,
        active_loads,
        operational_state,
        alert_level,
        recommendation,
        created_at
    """

    def __init__(self, database: Database, household_id: Optional[int] = None):
        self.database = database
        self.household_id = household_id

    def for_household(self, household_id: int):
        return MySqlTelemetryRepository(self.database, household_id)

    def _scope(self) -> dict:
        if not isinstance(self.household_id, int) or self.household_id < 1:
            raise ValueError("A household is required for every telemetry operation")
        return {"household_id": self.household_id}

    def save(self, telemetry: Telemetry) -> Telemetry:
        scope = self._scope()
        query = """
            INSERT INTO telemetry (
                household_id,
                sequence_number,
                device_id,
                scenario_profile,
                energy_storage_type,
                communication_mode,
                uptime_seconds,
                day_segment,
                battery_level,
                voltage,
                current_a,
                load_power_w,
                solar_power_w,
                net_power_w,
                available_energy_wh,
                estimated_autonomy_hours,
                availability_index,
                load_profile,
                active_loads,
                operational_state,
                alert_level,
                recommendation,
                created_at
            ) VALUES (
                %(household_id)s,
                %(sequence_number)s,
                %(device_id)s,
                %(scenario_profile)s,
                %(energy_storage_type)s,
                %(communication_mode)s,
                %(uptime_seconds)s,
                %(day_segment)s,
                %(battery_level)s,
                %(voltage)s,
                %(current_a)s,
                %(load_power_w)s,
                %(solar_power_w)s,
                %(net_power_w)s,
                %(available_energy_wh)s,
                %(estimated_autonomy_hours)s,
                %(availability_index)s,
                %(load_profile)s,
                %(active_loads)s,
                %(operational_state)s,
                %(alert_level)s,
                %(recommendation)s,
                %(created_at)s
            )
        """

        params = {
            **scope,
            "sequence_number": telemetry.sequence_number,
            "device_id": telemetry.device_id,
            "scenario_profile": telemetry.scenario_profile,
            "energy_storage_type": telemetry.energy_storage_type,
            "communication_mode": telemetry.communication_mode,
            "uptime_seconds": telemetry.uptime_seconds,
            "day_segment": telemetry.day_segment,
            "battery_level": telemetry.battery_level,
            "voltage": telemetry.voltage,
            "current_a": telemetry.current_a,
            "load_power_w": telemetry.load_power_w,
            "solar_power_w": telemetry.solar_power_w,
            "net_power_w": telemetry.net_power_w,
            "available_energy_wh": telemetry.available_energy_wh,
            "estimated_autonomy_hours": telemetry.estimated_autonomy_hours,
            "availability_index": telemetry.availability_index,
            "load_profile": telemetry.load_profile,
            "active_loads": telemetry.active_loads,
            "operational_state": telemetry.operational_state,
            "alert_level": telemetry.alert_level,
            "recommendation": telemetry.recommendation,
            "created_at": telemetry.created_at,
        }

        with self.database.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(query, params)
                inserted_id = cursor.lastrowid
                from src.aplicacion.services.telemetry_service import TelemetryService
                from src.monitoring import alerts_for
                from src.config import Config

                reading = TelemetryService(self)._telemetry_to_dict(telemetry)
                for alert in alerts_for(reading, Config.MAX_LOAD_W):
                    cursor.execute(
                        "INSERT INTO incidents (household_id,telemetry_id,type,severity,title,recommendation,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (self.household_id, inserted_id, alert["type"], alert["severity"],
                         alert["title"], alert["recommendation"], telemetry.created_at),
                    )
            finally:
                cursor.close()

        return replace(telemetry, id=inserted_id)

    def find_latest(self) -> Optional[Telemetry]:
        params = self._scope()
        query = f"""
            SELECT {self.SELECT_COLUMNS}
            FROM telemetry
            WHERE household_id = %(household_id)s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        """

        with self.database.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(query, params)
                row = cursor.fetchone()
            finally:
                cursor.close()

        return self._row_to_entity(row) if row else None

    def find_recent(self, limit: int = 50) -> List[Telemetry]:
        params = self._scope()
        safe_limit = self._sanitize_limit(limit, default=50, maximum=500)
        query = f"""
            SELECT {self.SELECT_COLUMNS}
            FROM telemetry
            WHERE household_id = %(household_id)s
            ORDER BY created_at DESC, id DESC
            LIMIT {safe_limit}
        """

        with self.database.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(query, params)
                rows = cursor.fetchall()
            finally:
                cursor.close()

        return [self._row_to_entity(row) for row in rows]

    def find_since(self, start_date: datetime, limit: int = 500) -> List[Telemetry]:
        params = {**self._scope(), "start_date": start_date}
        safe_limit = self._sanitize_limit(limit, default=500, maximum=2000)
        query = f"""
            SELECT {self.SELECT_COLUMNS}
            FROM telemetry
            WHERE household_id = %(household_id)s AND created_at >= %(start_date)s
            ORDER BY created_at ASC, id ASC
            LIMIT {safe_limit}
        """

        with self.database.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(query, params)
                rows = cursor.fetchall()
            finally:
                cursor.close()

        return [self._row_to_entity(row) for row in rows]

    @staticmethod
    def _sanitize_limit(limit: int, default: int, maximum: int) -> int:
        try:
            parsed_limit = int(limit)
        except (TypeError, ValueError):
            return default

        if parsed_limit < 1:
            return default

        return min(parsed_limit, maximum)

    @staticmethod
    def _row_to_entity(row: dict) -> Telemetry:
        return Telemetry(
            id=row.get("id"),
            sequence_number=row.get("sequence_number"),
            device_id=row.get("device_id"),
            scenario_profile=row.get("scenario_profile"),
            energy_storage_type=row.get("energy_storage_type"),
            communication_mode=row.get("communication_mode"),
            uptime_seconds=row.get("uptime_seconds"),
            day_segment=row.get("day_segment"),
            battery_level=row.get("battery_level"),
            voltage=row.get("voltage"),
            current_a=row.get("current_a"),
            load_power_w=row.get("load_power_w"),
            solar_power_w=row.get("solar_power_w"),
            net_power_w=row.get("net_power_w"),
            available_energy_wh=row.get("available_energy_wh"),
            estimated_autonomy_hours=row.get("estimated_autonomy_hours"),
            availability_index=row.get("availability_index"),
            load_profile=row.get("load_profile"),
            active_loads=row.get("active_loads"),
            operational_state=row.get("operational_state"),
            alert_level=row.get("alert_level"),
            recommendation=row.get("recommendation"),
            created_at=row.get("created_at"),
        )
