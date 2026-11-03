USE energy_storage_iot;

-- Ejecuta este script si ya tenias la tabla telemetry creada con las reglas antiguas.
-- MySQL 8 permite DROP CHECK por nombre. Si tu version no tiene CHECK, estos DROP pueden fallar sin afectar el funcionamiento.

ALTER TABLE telemetry DROP CHECK chk_alert_level_values;
ALTER TABLE telemetry DROP CHECK chk_operational_state_values;

ALTER TABLE telemetry
    ADD CONSTRAINT chk_alert_level_values
        CHECK (alert_level IN ('NONE', 'LOW', 'MEDIUM', 'HIGH', 'ERROR'));

ALTER TABLE telemetry
    ADD CONSTRAINT chk_operational_state_values
        CHECK (
            operational_state IN (
                'NORMAL_OPERATION',
                'LOW_BATTERY',
                'CRITICAL_BATTERY',
                'LOW_AUTONOMY',
                'CHARGING',
                'STANDBY',
                'WARNING_BATTERY',
                'HIGH_BASIC_HOME_DEMAND',
                'SENSOR_FAILURE'
            )
        );
