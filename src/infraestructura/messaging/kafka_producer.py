from __future__ import annotations

import json
from typing import Any, Dict

from kafka import KafkaProducer


class KafkaTelemetryProducer:
    def __init__(self, bootstrap_servers: str, client_id: str = "telemetry-producer"):
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers.split(","),
            client_id=client_id,
            value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda value: str(value).encode("utf-8") if value is not None else None,
            retries=5,
            linger_ms=10,
            acks="all",
        )

    def publish(self, topic: str, payload: Dict[str, Any], key: str | None = None) -> Dict[str, Any]:
        future = self.producer.send(topic, value=payload, key=key)
        metadata = future.get(timeout=15)
        self.producer.flush(timeout=15)
        return {
            "topic": metadata.topic,
            "partition": metadata.partition,
            "offset": metadata.offset,
        }

    def close(self) -> None:
        self.producer.close(timeout=10)
