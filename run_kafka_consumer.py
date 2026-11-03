from src.aplicacion.services.ai_autonomy_service import AiAutonomyService
from src.aplicacion.services.telemetry_service import TelemetryService
from src.config import Config
from src.infraestructura.database.connection import Database
from src.infraestructura.messaging.kafka_consumer import TelemetryKafkaConsumer
from src.infraestructura.repositories.mysql_telemetry_repository import MySqlTelemetryRepository
from src.monitoring import TelemetryIngestion
from src.security import IdentityStore


def main() -> None:
    database = Database(Config)
    repository = MySqlTelemetryRepository(database)
    ai_service = AiAutonomyService(
        model_path=Config.AI_MODEL_PATH,
        include_diagnostics=Config.AI_INCLUDE_DIAGNOSTICS,
    )
    telemetry_service = TelemetryIngestion(IdentityStore(database), repository, ai_service, Config.MAX_LOAD_W)

    consumer = TelemetryKafkaConsumer(
        telemetry_service=telemetry_service,
        bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
        topic=Config.KAFKA_TELEMETRY_TOPIC,
        group_id=Config.KAFKA_CONSUMER_GROUP,
        auto_offset_reset=Config.KAFKA_AUTO_OFFSET_RESET,
        client_id=Config.KAFKA_CLIENT_ID,
    )
    consumer.run_forever()


if __name__ == "__main__":
    main()
