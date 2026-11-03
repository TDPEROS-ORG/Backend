import hashlib
import re
from pathlib import Path

import mysql.connector

from src.infraestructura.database.connection import Database


SCHEMA_COLUMNS = {
    "users": "id,full_name,email,password_hash,role,active,created_at",
    "households": "id,user_id,name,address,notes,created_at",
    "devices": "device_id,household_id,name,key_hash,active,created_at",
    "auth_sessions": "token_hash,user_id,csrf_hash,expires_at",
    "auth_throttle": "bucket,attempts,expires_at",
    "telemetry": "id,household_id,sequence_number,device_id,scenario_profile,energy_storage_type,communication_mode,uptime_seconds,day_segment,battery_level,voltage,current_a,load_power_w,solar_power_w,net_power_w,available_energy_wh,estimated_autonomy_hours,availability_index,load_profile,active_loads,operational_state,alert_level,recommendation,created_at",
    "incidents": "id,household_id,telemetry_id,type,severity,title,recommendation,status,created_at",
    "incident_events": "id,incident_id,user_id,status,note,created_at",
}


def verify_backend(store, ai_service):
    if ai_service.health().get("status") != "ok":
        raise RuntimeError("El modelo de IA no esta preparado")
    for table, columns in SCHEMA_COLUMNS.items():
        store.query(f"SELECT {columns} FROM {table} LIMIT 0")
    return {"status": "ok", "database": "ok", "ai": "ok"}


def initialize_database(config, sql_directory):
    database_name = config.MYSQL_DATABASE
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database_name):
        raise ValueError("MYSQL_DATABASE debe tener entre 1 y 64 letras, numeros o guiones bajos")
    import sqlparse

    configuration = Database(config)._build_connection_config()
    configuration.pop("database")
    lock_name = "energy-init:" + hashlib.sha256(database_name.encode()).hexdigest()[:40]
    with mysql.connector.connect(**configuration) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s,0)", (lock_name,))
            if cursor.fetchone()[0] != 1:
                raise RuntimeError("Ya hay otra inicializacion en curso")
            try:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                connection.database = database_name
                cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (database_name,))
                tables = {row[0] for row in cursor.fetchall()}
                if tables and tables != set(SCHEMA_COLUMNS):
                    raise RuntimeError("Esquema parcial o ajeno: no se modifico. Revisa migraciones y backup")
                if not tables:
                    for filename in ("02_create_telemetry_table.sql", "04_users_households.sql"):
                        for statement in sqlparse.parse((Path(sql_directory) / filename).read_text(encoding="utf-8")):
                            first = statement.token_first(skip_cm=True)
                            if first is not None and first.normalized != "USE":
                                cursor.execute(str(statement))
                for table, columns in SCHEMA_COLUMNS.items():
                    cursor.execute(f"SELECT {columns} FROM {table} LIMIT 0")
                    cursor.fetchall()
                connection.commit()
                return not tables
            finally:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                cursor.fetchone()