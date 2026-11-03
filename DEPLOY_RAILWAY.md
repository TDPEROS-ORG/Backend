# Backend listo para Railway

> Para esta publicacion en TDPEROS-ORG usa primero [PASO_A_PASO_RAILWAY.md](PASO_A_PASO_RAILWAY.md). Esta guia conserva los detalles de Kafka de la entrega anterior. Ahora `.env.railway.example` contiene solo la API base; para Kafka anade tambien `.env.kafka.railway.example`. La Web y Mobile tienen repositorios separados.

Entrega: 25/10/2026. Solo backend. No contiene el movil ni la web.

**REQUIERE CODIGO:** cambios de produccion aplicados y probados en este paquete.
**FUNCIONAL:** falta crear/configurar los servicios en tu cuenta Railway y cargar este codigo. No se ha creado ningun servicio remoto ni contratado recursos.

## Que subir

Sube el CONTENIDO de la carpeta `backend-railway`, no el ZIP, al repositorio que conectes con Railway. El Dockerfile debe quedar en la raiz del servicio. Tambien puedes subir esta carpeta con `railway up`.

Incluye API Flask/Gunicorn, consumidor Kafka, SQL, modelo entrenado, dependencias fijadas y pruebas. No incluye `.env`, claves reales, dataset de entrenamiento, entornos Python ni frontends. La IA ejecuta el modelo incluido en CPU; no necesita GPU, Ollama ni una API de pago.

La URL `/operador` no sirve la web en esta entrega: el frontend se desplegara por separado. Usa `/api/ready` para comprobar el backend.

## 1. Crear MySQL y Kafka

1. En tu proyecto Railway, anade MySQL desde su plantilla oficial. Conserva el nombre **MySQL**, su volumen y sus variables. Activa backups antes de introducir datos reales. No publiques su puerto TCP si no lo necesitas.
2. Crea un servicio desde la imagen Docker **apache/kafka:4.0.2** y llamalo **kafka**. No le asignes dominio publico ni proxy TCP.
3. Conecta a Kafka un volumen montado en **/var/lib/kafka/data**.
4. En las variables de Kafka, usa el contenido de `kafka.railway.env.example` mediante Raw Editor. Revisa las referencias si cambias los nombres de servicios.
5. Conserva `CLUSTER_ID`, `KAFKA_NODE_ID`, ruta y volumen entre despliegues. Cambiar el cluster ID con datos existentes impide arrancar el broker.
6. Desactiva el reposo/serverless de Kafka y del consumidor. Configura reinicio ante fallo. Empieza con una replica por servicio.

`RAILWAY_RUN_UID=0` es SOLO para Kafka: Railway monta los volumenes como root. La API y el consumidor mantienen el usuario no administrador del Dockerfile. Esta configuracion es un broker unico privado, sin alta disponibilidad ni autenticacion Kafka adicional; no lo expongas a Internet.

## 2. Crear la API

1. Crea **energia-api** desde el repositorio con esta entrega. Confirma que usa el Dockerfile, no Flask development server.
2. En variables, pega `.env.railway.example` en Raw Editor. Railway resuelve las referencias `${{...}}`; no son contrasenas que debas escribir en el repositorio.
3. Cambia `CORS_ORIGINS` por el origen HTTPS EXACTO de la web de operadores, sin `/` final. Varios origenes se separan con coma. No uses `*`.
4. Comando de inicio: `gunicorn --config gunicorn.conf.py app:app`. Puerto: el `PORT` que Railway proporciona; no hay un 5000 fijo.
5. Para la primera instalacion, deja el healthcheck y el pre-deploy SIN configurar hasta inicializar MySQL. El proceso puede arrancar con BD vacia, pero `/api/ready` devuelve 503 hasta que exista el esquema.
6. Despliega y espera a que el proceso arranque. Solo **energia-api** necesita dominio HTTPS publico.

Configura web y API preferentemente bajo el mismo sitio, por ejemplo `operador.tudominio.com` y `api.tudominio.com`. Con esa disposicion usa `AUTH_COOKIE_SAMESITE=Strict` y `AUTH_COOKIE_SECURE=True`.

Si usas sitios distintos, cambia a `AUTH_COOKIE_SAMESITE=None`, conserva Secure y habilita `credentials: include` en la web. Algunos navegadores bloquean cookies de terceros aun asi: preferir mismo sitio o proxy del mismo origen. El movil nativo utiliza Bearer, no la cookie de operador. Estas integraciones frontend quedan fuera de esta entrega.

## 3. Inicializar sin sobrescribir datos

Instala Railway CLI en tu PC si no lo tienes:

```powershell
npm.cmd install -g @railway/cli
railway login
railway link
railway ssh --service energia-api
```

Elige tu proyecto y entorno al vincular. Introduce credenciales solo en Railway o en tu terminal, nunca en el chat. Dentro de la shell remota ejecuta:

```sh
flask --app app init-db --confirm-empty
flask --app app check-backend
flask --app app create-operator --email tu-correo@tudominio.com --name "Tu nombre"
```

El ultimo comando pide la contrasena dos veces sin guardarla en texto plano. No pases `--password` en la linea de comandos. Crea el operador solo una vez; email debe ser unico. Cierra la shell con `exit`.

`init-db` usa `MYSQL_DATABASE` real, incluso si la plantilla la llama `railway`. Solo instala en una BD vacia/nueva. Repetirlo sobre el esquema completo no cambia datos. Si hay tablas parciales, antiguas o ajenas se detiene; NO elimina tablas ni migra datos existentes. MySQL hace commits implicitos de DDL: un fallo a mitad de instalacion requiere revisar el esquema, no repetir ALTER a ciegas. No ejecutes manualmente los SQL numerados sobre una BD con datos.

Con el esquema preparado, configura en **energia-api**:

| Ajuste | Valor |
|---|---|
| Start command | `gunicorn --config gunicorn.conf.py app:app` |
| Pre-deploy | `flask --app app check-backend` |
| Healthcheck path | `/api/ready` |
| Healthcheck timeout | `120` segundos |
| Replicas iniciales | `1` |

Redespliega y comprueba desde PowerShell:

```powershell
Invoke-RestMethod 'https://TU-API.up.railway.app/api/ready'
```

Resultado esperado: `status=ok`, `database=ok`, `ai=ok`. `/api/health` solo comprueba proceso/modelo y no sustituye la comprobacion de BD. El healthcheck de Railway sirve al despliegue, no reemplaza monitorizacion continua.

## 4. Crear el consumidor

1. Crea **energia-consumer** desde el mismo repositorio y Dockerfile.
2. Usa las mismas variables privadas de la API y cambia `KAFKA_CLIENT_ID` a `energia-consumer`.
3. Start command: **python run_kafka_consumer.py**.
4. Pre-deploy: **flask --app app check-backend**.
5. Sin dominio, sin puertos publicos y sin healthcheck HTTP. Desactiva reposo/serverless y habilita reinicio ante fallo.
6. Despliega cuando MySQL y Kafka esten disponibles. Comprueba ausencia de errores de conexion y prueba una lectura real de un dispositivo registrado.

El broker permite creacion automatica del topic, como en la prueba local. Para crearlo de forma explicita, abre `railway ssh --service kafka` y ejecuta:

```sh
/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic rural-energy.telemetry.raw --partitions 1 --replication-factor 1
```

Los mensajes validos se confirman tras persistirlos. Los invalidos se rechazan con tipo de error y offset, sin volcar deviceKey. Si falla BD, el proceso falla SIN confirmar y el reinicio reintenta. La entrega es **al menos una vez**: si BD guarda pero falla el commit Kafka puede haber duplicados. No es exactly-once, no hay DLQ y los invalidos se descartan intencionadamente. El topic raw contiene credenciales de dispositivo: restringe acceso a broker, volumen y backups; aplica retencion acorde a tus necesidades.

## 5. Subida sin GitHub

Tambien puedes usar el CLI desde esta carpeta. Primero crea/configura los servicios vacios en el dashboard, vincula el proyecto y ejecuta, uno por uno:

```powershell
railway up --service energia-api
railway up --service energia-consumer
```

Los ajustes de inicio y variables son distintos por servicio aunque compartan imagen. `.gitignore` y `.dockerignore` excluyen secretos; revisa siempre el contenido antes de subir.

Los ajustes anteriores se aplican en el dashboard. No se incluye infraestructura declarativa: el repositorio o ZIP no crean servicios remotos por si solos.

## 6. Repetir la validacion local

Requisitos: Docker Desktop con contenedores Linux y Docker Compose. Este stack es desechable: MySQL usa tmpfs y Kafka un volumen de prueba. Nunca lo conectes a datos reales.

Desde esta carpeta, en PowerShell:

```powershell
$env:VALIDATION_DB_PASSWORD = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
docker compose -f compose.verify.yml up -d --build --wait --wait-timeout 240
docker compose -f compose.verify.yml exec -T -e ENERGY_VERIFY_ALLOW=temporary-stack api python -m tests.verify_stack --expect-unready
docker compose -f compose.verify.yml exec -T api flask --app app init-db --confirm-empty
docker compose -f compose.verify.yml exec -T api flask --app app check-backend
docker compose -f compose.verify.yml exec -T -e CORS_ORIGINS=http://localhost:8082 api python -m unittest discover -s tests -p 'test_*.py' -v
docker compose -f compose.verify.yml exec -T -e ENERGY_VERIFY_ALLOW=temporary-stack api python -m tests.verify_stack
docker compose -f compose.verify.yml down -v
Remove-Item Env:VALIDATION_DB_PASSWORD
```

La primera prueba espera una BD sin inicializar; omite `--expect-unready` si ya inicializaste esta misma sesion. La suite crea y elimina solo bases `energy_auth_test_*`. El smoke test crea usuarios y lecturas ficticios exclusivamente en este stack, genera sus claves en memoria y no las imprime. El ultimo comando Docker elimina SOLO el stack y su volumen de prueba. El puerto HTTP local es aleatorio en 127.0.0.1; puedes verlo con `docker compose -f compose.verify.yml port api 8080`.

## 7. Cierre y limites

- 32 pruebas pasan en Windows y 32 en Linux. Tambien pasan HTTP/Gunicorn, IA real, aislamiento, Kafka y persistencia tras recrear broker. Detalle en `VALIDACION_BACKEND.md`.
- El modelo incluido no se ha reentrenado. No necesitas subir el CSV para inferencia.
- No se ha desplegado en tu cuenta: quedan pendientes validacion HTTPS, dominios, acceso privado, presupuesto, backups/restauracion y prueba con dispositivo real en Railway.
- Este paquete no contiene tus datos actuales. Si deben viajar a Railway, hace falta un backup/restauracion separado y una migracion revisada, no este bootstrap.
- Un solo broker y MySQL individual no constituyen un servicio HA. Vigila RAM, disco, retencion, sesiones y logs. Kafka puede requerir mas memoria que API/IA.

Referencias consultadas:

- https://docs.railway.com/guides/dockerfiles
- https://docs.railway.com/guides/private-networking
- https://docs.railway.com/guides/variables
- https://docs.railway.com/guides/volumes
- https://docs.railway.com/guides/healthchecks
- https://docs.railway.com/guides/pre-deploy-command
- https://docs.railway.com/guides/cli
- https://docs.railway.com/guides/config-as-code