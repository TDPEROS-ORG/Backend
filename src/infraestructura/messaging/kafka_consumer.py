from __future__ import annotations

import json
from typing import Any, Dict

from kafka import KafkaConsumer
from kafka.structs import OffsetAndMetadata, TopicPartition
from werkzeug.exceptions import BadRequest, Forbidden, Unauthorized

from src.dominio.exceptions import ValidationException
from src.monitoring import TelemetryIngestion


class TelemetryKafkaConsumer:
    def __init__(
        self,
        telemetry_service: TelemetryIngestion,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        auto_offset_reset: str = "latest",
        client_id: str = "backend-flask-ia-consumer",
    ):
        self.telemetry_service = telemetry_service
        self.topic = topic
        self.consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers.split(","),
            group_id=group_id,
            client_id=client_id,
            auto_offset_reset=auto_offset_reset,
            enable_auto_commit=False,
        )

    @staticmethod
    def _deserialize_json(value: bytes) -> Dict[str, Any]:
        if value is None:
            raise ValidationException("Mensaje vacio")
        return json.loads(value.decode("utf-8"))

    def _commit(self, message):
        self.consumer.commit({
            TopicPartition(message.topic, message.partition): OffsetAndMetadata(message.offset + 1, "", -1),
        })

    def run_forever(self) -> None:
        print(f"Consumidor Kafka iniciado | topic={self.topic}")
        print("Presiona CTRL+C para detener.\n")
        try:
            for message in self.consumer:
                try:
                    payload = self._deserialize_json(message.value)
                    saved = self.telemetry_service.save_payload(payload)
                except (ValidationException, UnicodeDecodeError, json.JSONDecodeError, BadRequest, Unauthorized, Forbidden) as error:
                    print(
                        f"RECHAZADO | topic={message.topic} partition={message.partition} "
                        f"offset={message.offset} tipo={type(error).__name__}", flush=True,
                    )
                    self._commit(message)
                except Exception as error:
                    print(
                        f"REINTENTAR | topic={message.topic} partition={message.partition} "
                        f"offset={message.offset} tipo={type(error).__name__}", flush=True,
                    )
                    raise
                else:
                    self._commit(message)
                    print(
                        "OK | "
                        f"topic={message.topic} partition={message.partition} offset={message.offset} | "
                        f"seq={saved.sequence_number} device={saved.device_id} "
                        f"battery={saved.battery_level}% autonomy={saved.estimated_autonomy_hours}h "
                        f"state={saved.operational_state} alert={saved.alert_level}"
                    )
        except KeyboardInterrupt:
            print("\nConsumidor Kafka detenido por el usuario.")
        finally:
            self.consumer.close(autocommit=False)
