FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=UTC
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
ENV AUTH_COOKIE_SECURE=True
WORKDIR /app
COPY requirements.txt requirements.railway.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip check
RUN useradd --create-home --uid 10001 energy
COPY app.py run_kafka_consumer.py gunicorn.conf.py ./
COPY src ./src
COPY models ./models
COPY sql ./sql
COPY tests/*.py ./tests/
RUN python -W error -c "from src.aplicacion.services.ai_autonomy_service import AiAutonomyService; model = AiAutonomyService('/app/models/modelo_autonomia_residual.pkl'); assert model.health()['status'] == 'ok'"
USER energy
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]