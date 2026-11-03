USE energy_storage_iot;

CREATE TABLE IF NOT EXISTS telemetry (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sequence_number INT NULL,
    device_id VARCHAR(100) NOT NULL,
    scenario_profile VARCHAR(100) NULL,
    energy_storage_type VARCHAR(100) NULL,
    communication_mode VARCHAR(100) NULL,
    uptime_seconds BIGINT NULL,
    day_segment VARCHAR(50) NULL,
    battery_level DOUBLE NOT NULL,
    voltage DOUBLE NOT NULL,
    current_a DOUBLE NULL,
    load_power_w DOUBLE NULL,
    solar_power_w DOUBLE NULL,
    net_power_w DOUBLE NULL,
    available_energy_wh DOUBLE NULL,
    estimated_autonomy_hours DOUBLE NULL,
    availability_index DOUBLE NULL,
    load_profile VARCHAR(100) NULL,
    active_loads TEXT NULL,
    operational_state VARCHAR(50) NOT NULL,
    alert_level VARCHAR(20) NOT NULL,
    recommendation TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_battery_level_range
        CHECK (battery_level >= 0 AND battery_level <= 100),

    CONSTRAINT chk_availability_index_range
        CHECK (availability_index IS NULL OR (availability_index >= 0 AND availability_index <= 100)),

    CONSTRAINT chk_voltage_positive_except_sensor_failure
        CHECK (operational_state = 'SENSOR_FAILURE' OR voltage > 0),

    CONSTRAINT chk_alert_level_values
        CHECK (alert_level IN ('NONE', 'LOW', 'MEDIUM', 'HIGH', 'ERROR')),

    CONSTRAINT chk_operational_state_values
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
        )
);

CREATE INDEX idx_telemetry_created_at ON telemetry (created_at);
CREATE INDEX idx_telemetry_device_created ON telemetry (device_id, created_at);
