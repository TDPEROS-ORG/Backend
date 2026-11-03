SET NAMES utf8mb4;

CREATE TABLE users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(190) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('client', 'operator') NOT NULL DEFAULT 'client',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE households (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    address VARCHAR(255) NOT NULL DEFAULT '',
    notes TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE devices (
    device_id VARCHAR(100) PRIMARY KEY,
    household_id BIGINT NOT NULL,
    name VARCHAR(120) NOT NULL,
    key_hash CHAR(64) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (household_id) REFERENCES households(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE auth_sessions (
    token_hash CHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    csrf_hash CHAR(64) NOT NULL,
    expires_at DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_sessions_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE auth_throttle (
    bucket CHAR(64) PRIMARY KEY,
    attempts INT NOT NULL DEFAULT 0,
    expires_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE telemetry (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    household_id BIGINT NULL,
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
    CONSTRAINT fk_telemetry_household FOREIGN KEY (household_id) REFERENCES households(id),
    CONSTRAINT chk_battery_level_range CHECK (battery_level >= 0 AND battery_level <= 100),
    CONSTRAINT chk_availability_index_range CHECK (availability_index IS NULL OR (availability_index >= 0 AND availability_index <= 100)),
    CONSTRAINT chk_voltage_positive_except_sensor_failure CHECK (operational_state = 'SENSOR_FAILURE' OR voltage > 0),
    CONSTRAINT chk_alert_level_values CHECK (alert_level IN ('NONE', 'LOW', 'MEDIUM', 'HIGH', 'ERROR')),
    CONSTRAINT chk_operational_state_values CHECK (operational_state IN (
        'NORMAL_OPERATION', 'LOW_BATTERY', 'CRITICAL_BATTERY', 'LOW_AUTONOMY',
        'CHARGING', 'STANDBY', 'WARNING_BATTERY', 'HIGH_BASIC_HOME_DEMAND', 'SENSOR_FAILURE'
    )),
    INDEX idx_telemetry_created_at (created_at),
    INDEX idx_telemetry_device_created (device_id, created_at),
    INDEX idx_telemetry_household_time (household_id, created_at, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE incidents (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    household_id BIGINT NOT NULL,
    telemetry_id BIGINT NOT NULL,
    type VARCHAR(40) NOT NULL,
    severity ENUM('low', 'medium', 'high') NOT NULL,
    title VARCHAR(160) NOT NULL,
    recommendation TEXT NOT NULL,
    status ENUM('open', 'acknowledged', 'resolved') NOT NULL DEFAULT 'open',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (household_id) REFERENCES households(id),
    FOREIGN KEY (telemetry_id) REFERENCES telemetry(id),
    UNIQUE KEY uq_incident_reading_type (telemetry_id, type),
    INDEX idx_incident_household_time (household_id, created_at, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE incident_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    incident_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    status ENUM('open', 'acknowledged', 'resolved') NOT NULL,
    note TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (incident_id) REFERENCES incidents(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;