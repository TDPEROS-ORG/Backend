from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

AUTONOMY_CAP_HOURS = 99.99
EPS = 1e-9

BASE_INPUT_COLUMNS: List[str] = [
    "batteryLevel",
    "voltage",
    "currentA",
    "loadPowerW",
    "solarPowerW",
    "netPowerW",
    "availableEnergyWh",
]

ENGINEERED_COLUMNS: List[str] = [
    "physicalAutonomyHours",
    "loadToEnergyRatio",
    "netToLoadRatio",
    "batteryVoltageIndex",
    "lowBatteryFlag",
    "criticalBatteryFlag",
    "isSolarActive",
]

FEATURE_COLUMNS: List[str] = BASE_INPUT_COLUMNS + ENGINEERED_COLUMNS

DEFAULT_THRESHOLDS: Dict[str, float] = {
    "critical_battery_pct": 15.0,
    "low_battery_pct": 30.0,
    "low_autonomy_hours": 2.0,
    "availability_autonomy_reference_hours": 12.0,
    "max_runtime_autonomy_hours": 99.99,
    "min_net_power_w": 0.001,
    "min_load_power_w": 0.001,
}


class AiAutonomyService:
    """Servicio de IA para enriquecer telemetria energetica.

    El modelo usa una estimacion fisica base:
        autonomia = energia disponible / potencia neta de consumo

    y una regresion lineal multivariable regularizada para corregir el residual.
    Despues aplica reglas de decision para estado operativo, alerta y recomendacion.
    """

    def __init__(self, model_path: str, include_diagnostics: bool = False):
        self.model_path = Path(model_path)
        self.include_diagnostics = include_diagnostics
        self.artifact: Optional[Dict[str, Any]] = None
        self.thresholds: Dict[str, Any] = dict(DEFAULT_THRESHOLDS)
        self.load_model()

    def load_model(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(f"No existe el modelo de IA: {self.model_path}")
        artifact = joblib.load(self.model_path)
        if not isinstance(artifact, dict) or "model" not in artifact:
            raise ValueError("El modelo .pkl no tiene el formato esperado")
        self.artifact = artifact
        self.thresholds = {**DEFAULT_THRESHOLDS, **artifact.get("thresholds", {})}

    def health(self) -> Dict[str, Any]:
        return {
            "status": "ok" if self.artifact is not None else "not_loaded",
            "modelPath": str(self.model_path),
            "modelExists": self.model_path.exists(),
            "modelType": "PHYSICAL_FORMULA_PLUS_LINEAR_RIDGE_RESIDUAL",
            "featureColumns": self.artifact.get("feature_columns", FEATURE_COLUMNS) if self.artifact else FEATURE_COLUMNS,
            "thresholds": self.thresholds,
        }

    def enrich(self, payload: Dict[str, Any], include_diagnostics: Optional[bool] = None) -> Dict[str, Any]:
        if self.artifact is None:
            self.load_model()

        record = self.normalize_record(payload)
        estimated, diagnostics = self.predict_autonomy(record)
        state, alert = self.classify_state(record, estimated)
        availability = self.availability_index(record, estimated)

        output = dict(payload)
        for key in BASE_INPUT_COLUMNS:
            output[key] = round(float(record[key]), 2)

        output.setdefault("energyStorageType", record.get("energyStorageType", "LiFePO4_4S"))
        output.setdefault(
            "communicationMode",
            record.get("communicationMode", "LOCAL_BLUETOOTH_WIFI_DIRECT_SIMULATED"),
        )
        output["estimatedAutonomyHours"] = estimated
        output["availabilityIndex"] = availability
        output["operationalState"] = state
        output["alertLevel"] = alert
        output["recommendation"] = self.recommendation(state, record, estimated)

        if not output.get("loadProfile") or not output.get("activeLoads"):
            profile, loads = self.infer_load_profile(record)
            output["loadProfile"] = output.get("loadProfile") or profile
            output["activeLoads"] = output.get("activeLoads") or loads

        if include_diagnostics if include_diagnostics is not None else self.include_diagnostics:
            output["modelDiagnostics"] = diagnostics

        return output

    @staticmethod
    def as_float(data: Dict[str, Any], key: str, default: float = 0.0) -> float:
        value = data.get(key, default)
        try:
            if value is None or value == "":
                return default
            number = float(value)
            if not np.isfinite(number):
                return default
            return number
        except (TypeError, ValueError):
            return default

    @staticmethod
    def clip(value: float, low: float, high: float) -> float:
        return float(np.clip(float(value), low, high))

    def normalize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(record)
        out["batteryLevel"] = self.clip(self.as_float(out, "batteryLevel"), 0.0, 100.0)
        out["voltage"] = max(self.as_float(out, "voltage"), 0.0)
        out["currentA"] = max(self.as_float(out, "currentA"), 0.0)
        out["loadPowerW"] = max(self.as_float(out, "loadPowerW"), 0.0)
        out["solarPowerW"] = max(self.as_float(out, "solarPowerW"), 0.0)
        out["availableEnergyWh"] = max(self.as_float(out, "availableEnergyWh"), 0.0)

        if "netPowerW" not in out or out.get("netPowerW") in (None, ""):
            out["netPowerW"] = out["loadPowerW"] - out["solarPowerW"]
        else:
            out["netPowerW"] = self.as_float(out, "netPowerW")

        out.setdefault("energyStorageType", "LiFePO4_4S")
        out.setdefault("communicationMode", "LOCAL_BLUETOOTH_WIFI_DIRECT_SIMULATED")
        return out

    def add_features(self, record: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(record)
        max_hours = float(self.thresholds.get("max_runtime_autonomy_hours", AUTONOMY_CAP_HOURS))

        battery = self.clip(self.as_float(out, "batteryLevel"), 0, 100)
        voltage = max(self.as_float(out, "voltage"), 0)
        load = max(self.as_float(out, "loadPowerW"), 0)
        solar = max(self.as_float(out, "solarPowerW"), 0)
        net = self.as_float(out, "netPowerW")
        energy = max(self.as_float(out, "availableEnergyWh"), 0)

        if net > EPS:
            physical = energy / max(net, EPS)
        else:
            physical = max_hours

        out["physicalAutonomyHours"] = self.clip(physical, 0.0, max_hours)
        out["loadToEnergyRatio"] = self.clip(load / max(energy, EPS), 0.0, 1000.0) if energy > EPS else 0.0
        out["netToLoadRatio"] = self.clip(net / max(load, EPS), -1000.0, 1000.0) if load > EPS else 0.0
        out["batteryVoltageIndex"] = (battery / 100.0) * voltage
        out["lowBatteryFlag"] = 1.0 if battery <= self.thresholds.get("low_battery_pct", 30.0) else 0.0
        out["criticalBatteryFlag"] = 1.0 if battery <= self.thresholds.get("critical_battery_pct", 15.0) else 0.0
        out["isSolarActive"] = 1.0 if solar > EPS else 0.0
        return out

    def predict_autonomy(self, record: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        if self.artifact is None:
            raise RuntimeError("Modelo de IA no cargado")

        max_hours = float(self.thresholds.get("max_runtime_autonomy_hours", AUTONOMY_CAP_HOURS))
        min_net = float(self.thresholds.get("min_net_power_w", 0.001))
        residual_clip = float(self.artifact.get("residualClipHours", 0.25))

        data = self.add_features(record)
        net = self.as_float(data, "netPowerW")
        energy = max(self.as_float(data, "availableEnergyWh"), 0.0)

        # Regla adicional de consistencia fisica:
        # si no hay descarga neta real, se usa autonomia maxima controlada.
        if net <= min_net:
            return max_hours, {
                "predictionMethod": "RULE_NET_POWER_NON_POSITIVE",
                "physicalAutonomyHours": max_hours,
                "modelResidualHours": None,
            }
        if energy <= 0:
            return 0.0, {
                "predictionMethod": "RULE_NO_AVAILABLE_ENERGY",
                "physicalAutonomyHours": 0.0,
                "modelResidualHours": None,
            }

        physical = self.clip(energy / max(net, EPS), 0.0, max_hours)
        model = self.artifact["model"]
        feature_columns = self.artifact.get("feature_columns") or self.artifact.get("featureColumns") or FEATURE_COLUMNS
        X = pd.DataFrame([{col: self.as_float(data, col) for col in feature_columns}], columns=feature_columns)
        residual = float(model.predict(X)[0])
        if not np.isfinite(residual):
            residual = 0.0
        residual = self.clip(residual, -residual_clip, residual_clip)
        final = self.clip(physical + residual, 0.0, max_hours)

        return round(final, 2), {
            "predictionMethod": "PHYSICAL_FORMULA_PLUS_IA_RESIDUAL",
            "physicalAutonomyHours": round(physical, 6),
            "modelResidualHours": round(residual, 6),
            "residualClipHours": residual_clip,
        }

    def classify_state(self, record: Dict[str, Any], estimated_autonomy: float) -> Tuple[str, str]:
        battery = self.as_float(record, "batteryLevel")
        load = self.as_float(record, "loadPowerW")
        solar = self.as_float(record, "solarPowerW")
        net = self.as_float(record, "netPowerW")

        if battery <= self.thresholds.get("critical_battery_pct", 15.0):
            return "CRITICAL_BATTERY", "HIGH"
        if battery <= self.thresholds.get("low_battery_pct", 30.0):
            return "LOW_BATTERY", "MEDIUM"
        if net > 0 and estimated_autonomy <= self.thresholds.get("low_autonomy_hours", 2.0):
            return "LOW_AUTONOMY", "MEDIUM"
        if solar > 0 and net < 0:
            return "CHARGING", "LOW"
        if abs(load) <= 0.05 and abs(solar) <= 0.05:
            return "STANDBY", "LOW"
        return "NORMAL_OPERATION", "NONE"

    def availability_index(self, record: Dict[str, Any], estimated_autonomy: float) -> float:
        battery = self.clip(self.as_float(record, "batteryLevel"), 0, 100)
        net = self.as_float(record, "netPowerW")
        solar = self.as_float(record, "solarPowerW")
        ref = float(self.thresholds.get("availability_autonomy_reference_hours", 12.0))

        if net > 0:
            autonomy_score = self.clip((estimated_autonomy / ref) * 100.0, 0, 100)
        elif solar > 0 and net < 0:
            autonomy_score = 100.0
        else:
            autonomy_score = battery
        return round(self.clip((0.70 * battery) + (0.30 * autonomy_score), 0.0, 100.0), 2)

    def recommendation(self, state: str, record: Dict[str, Any], estimated_autonomy: float) -> str:
        battery = self.as_float(record, "batteryLevel")
        if state == "CRITICAL_BATTERY":
            return f"Bateria critica ({battery:.0f}%). Apague equipos no esenciales y mantenga solo iluminacion basica hasta recuperar energia."
        if state == "LOW_BATTERY":
            return f"Bateria baja ({battery:.0f}%). Reduzca equipos no esenciales y evite conectar nuevas cargas."
        if state == "LOW_AUTONOMY":
            minutes = max(1, int(round(estimated_autonomy * 60)))
            return f"Autonomia reducida: aproximadamente {minutes} minutos. Disminuya el consumo o espere mayor aporte solar."
        if state == "CHARGING":
            return "El aporte solar supera el consumo actual. Mantenga bajo el consumo para recuperar bateria mas rapido."
        if state == "STANDBY":
            return "No se detecta consumo ni carga relevante. El sistema esta en espera."
        return f"Condicion energetica estable. Con el consumo actual, la autonomia estimada es de {estimated_autonomy:.2f} horas."

    def infer_load_profile(self, record: Dict[str, Any]) -> Tuple[str, List[str]]:
        load = self.as_float(record, "loadPowerW")
        if load <= 0.05:
            return "NO_ACTIVE_LOAD", []
        if load <= 25:
            return "LIGHTING_ONLY", ["LED_LIGHTS"]
        if load <= 80:
            return "BASIC_APPLIANCES", ["LED_LIGHTS", "PHONE_CHARGER", "RADIO"]
        if load <= 150:
            return "HIGH_CONSUMPTION", ["LED_LIGHTS", "RADIO", "SMALL_APPLIANCE"]
        return "OVERLOAD_RISK", ["MULTIPLE_LOADS"]
