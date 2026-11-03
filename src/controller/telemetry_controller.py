from flask import Blueprint, g, jsonify, request

from src.aplicacion.dtos.telemetry_request import TelemetryRequest
from src.aplicacion.services.telemetry_service import TelemetryService
from src.config import Config
from src.security import authenticated


def create_telemetry_blueprint(telemetry_service: TelemetryService, ingestion) -> Blueprint:
    telemetry_bp = Blueprint("telemetry", __name__)

    def scoped():
        return TelemetryService(telemetry_service.telemetry_repository.for_household(g.user["household_id"]),
                                telemetry_service.ai_service)

    @telemetry_bp.get("/health")
    def health():
        return jsonify({
            "status": "ok",
            "database": "mysql",
            "broker": "apache-kafka",
            "topic": Config.KAFKA_TELEMETRY_TOPIC,
            "ai": telemetry_service.getAiHealth(),
        })

    @telemetry_bp.get("/ai/health")
    @authenticated("operator")
    def ai_health():
        return jsonify(telemetry_service.getAiHealth())

    @telemetry_bp.post("/ai/predict")
    @authenticated("operator")
    def predict_only():
        payload = request.get_json(silent=True)
        include_diagnostics = request.args.get("diagnostics", default="false", type=str).lower() == "true"
        result = telemetry_service.enrichTelemetry(payload, include_diagnostics=include_diagnostics)
        return jsonify({"data": result})

    @telemetry_bp.post("/telemetry")
    def store_telemetry():
        # Endpoint directo: mantiene compatibilidad con el frontend o pruebas HTTP.
        # Si llegan datos crudos, el backend los enriquece con IA antes de guardar.
        payload = request.get_json(silent=True)
        saved = ingestion.save_payload(payload, request.headers.get("X-Device-Key"))
        return jsonify({
            "message": "Telemetry processed with AI and stored successfully",
            "data": telemetry_service._telemetry_to_dict(saved),
        })

    @telemetry_bp.post("/telemetry/broker")
    def publish_telemetry_to_broker():
        # Endpoint opcional: publica telemetria cruda en Kafka.
        # El guardado real ocurre cuando run_kafka_consumer.py consume el mensaje.
        payload = request.get_json(silent=True)
        ingestion.identity.authenticate_device(payload, request.headers.get("X-Device-Key"))
        telemetry_request = TelemetryRequest.from_dict(payload)
        from src.infraestructura.messaging.kafka_producer import KafkaTelemetryProducer

        producer = KafkaTelemetryProducer(
            bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
            client_id=f"{Config.KAFKA_CLIENT_ID}-http-producer",
        )
        try:
            metadata = producer.publish(
                topic=Config.KAFKA_TELEMETRY_TOPIC,
                payload={**telemetry_request.to_payload(), "deviceKey": request.headers.get("X-Device-Key") or payload.get("deviceKey")},
                key=telemetry_request.device_id,
            )
        finally:
            producer.close()
        return jsonify({
            "message": "Telemetry published to Apache Kafka",
            "broker": "apache-kafka",
            "metadata": metadata,
        })

    @telemetry_bp.get("/telemetry")
    @authenticated("client")
    def list_telemetry():
        limit = request.args.get("limit", default=50, type=int)
        return jsonify({"data": scoped().getTelemetryList(limit=limit)})

    @telemetry_bp.get("/telemetry/latest")
    @authenticated("client")
    def get_latest_telemetry():
        return jsonify({"data": scoped().getLatestTelemetry()})

    @telemetry_bp.get("/telemetry/summary")
    @authenticated("client")
    def get_summary():
        return jsonify(scoped().getSummary())

    @telemetry_bp.get("/telemetry/detail")
    @authenticated("client")
    def get_detail():
        period = request.args.get("period", default="today", type=str)
        return jsonify(scoped().getDetail(period=period))


    @telemetry_bp.get("/telemetry/dashboard")
    @authenticated("client")
    def get_mobile_dashboard():
        # Endpoint optimizado para la app movil: entrega el ultimo estado,
        # consumo actual, balance energetico y explicacion de cambios.
        return jsonify(scoped().getMobileDashboard())

    @telemetry_bp.get("/telemetry/recommendations")
    @authenticated("client")
    def get_recommendations():
        return jsonify(scoped().getRecommendations())

    return telemetry_bp
