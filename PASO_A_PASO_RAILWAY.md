# GitHub, Railway y Expo: puesta en marcha

**REQUIERE CODIGO:** los tres repositorios incluyen codigo y configuracion de construccion.
**FUNCIONAL:** los pasos siguientes se realizan en tus cuentas de Railway y Expo. No se han creado servicios remotos, generado contrasenas de produccion ni contratado recursos desde esta entrega.

## 1. Que va en cada sitio

| Sitio | Contenido |
| --- | --- |
| GitHub Backend | API, IA entrenada, SQL, Docker y pruebas |
| GitHub Web | Consola de operadores, imagenes, nginx y Docker |
| GitHub Mobile | Codigo Expo, perfiles APK/AAB y comprobaciones |
| Railway MySQL | Tablas y datos de la aplicacion, con volumen persistente |
| Railway energia-api | Flask/Gunicorn y modelo IA en CPU |
| Railway energia-web | Web y proxy `/api` hacia la API |
| Expo/EAS y telefono | Construccion e instalacion del movil |

Empieza con MySQL + API + Web. El envio directo `POST /api/telemetry`, autenticado con la clave de un dispositivo registrado, no necesita Kafka. Si se usa `/api/telemetry/broker`, si se necesita el flujo Kafka del proyecto o si forma parte de la demostracion requerida, completa tambien la seccion 8. Sin broker, esa ruta no estara operativa.

GitHub no almacena la BD de produccion y GitHub Pages no ejecuta el proxy. No subas secretos, backups reales ni `.env` al repositorio. Los repositorios de esta organizacion son publicos.

## 2. Cuenta, proyecto y permisos

1. Entra en Railway con tu cuenta y revisa precios, credito y limites de uso. No hay un coste fijo garantizado por esta guia.
2. Crea un proyecto y el entorno de despliegue. Mantendras los tres servicios en el mismo proyecto y entorno para usar red privada y referencias de variables.
3. Conecta GitHub y autoriza la aplicacion Railway para la organizacion `TDPEROS-ORG`, al menos para `Backend` y `Web`. Si no aparecen, revisa la instalacion de la GitHub App y los permisos de la organizacion. Tener acceso al repositorio no instala automaticamente esa aplicacion.
4. Usa la rama `main`. Tras conectar cada servicio, activa autodeploy y **Wait for CI** cuando los workflows ya esten disponibles. Asi un push que falle CI no se desplegara automaticamente.

## 3. MySQL

1. Anade la plantilla oficial MySQL y conserva el nombre **MySQL**. Usa MySQL 8.4 para reproducir la validacion local.
2. Conserva su volumen en `/var/lib/mysql`. Sin volumen, perderias los datos al sustituir el contenedor.
3. Conserva las credenciales generadas en Railway y las variables `MYSQLHOST`, `MYSQLPORT`, `MYSQLUSER`, `MYSQLPASSWORD`, `MYSQLDATABASE`.
4. La base puede llamarse `railway`; no necesitas renombrarla a `energy_storage_iot`.
5. Manten MySQL privado. No hace falta TCP publico para la inicializacion recomendada por SSH. Configura backups y prueba su restauracion antes de cargar datos reales.

## 4. API Flask e IA

1. Anade un servicio desde `TDPEROS-ORG/Backend` y llamalo **energia-api**.
2. Usa la raiz del repositorio y su `Dockerfile`. No configures un servidor Flask de desarrollo. Comando de inicio: `gunicorn --config gunicorn.conf.py app:app`.
3. Pega el contenido de [.env.railway.example](.env.railway.example) en **Variables > Raw Editor**. Las referencias de MySQL son:

```dotenv
MYSQL_HOST=${{MySQL.MYSQLHOST}}
MYSQL_PORT=${{MySQL.MYSQLPORT}}
MYSQL_USER=${{MySQL.MYSQLUSER}}
MYSQL_PASSWORD=${{MySQL.MYSQLPASSWORD}}
MYSQL_DATABASE=${{MySQL.MYSQLDATABASE}}
```

4. Conserva `AI_MODEL_PATH=/app/models/modelo_autonomia_residual.pkl`, `FLASK_DEBUG=False`, `AUTH_COOKIE_SECURE=True` y `AUTH_COOKIE_SAMESITE=Strict`. No necesitas un servicio GPU ni un proveedor de IA.
5. Para el primer arranque deja **Pre-deploy** y **Healthcheck path** vacios: el esquema aun no existe y `/api/ready` devolvera 503. Despliega y espera a que Gunicorn arranque.
6. Genera un dominio HTTPS en **Settings > Networking**, con el puerto `PORT` del servicio. Gunicorn lee ese valor; no lo sustituyas por 5000. Guarda la URL como `https://TU-API.up.railway.app`.

## 5. Crear las tablas y el operador

### Opcion recomendada: inicializador por SSH

En tu PC, con Node.js instalado:

```powershell
npm.cmd install -g @railway/cli
railway login
railway link
railway ssh --service energia-api
```

Selecciona el proyecto y entorno correctos. Tambien puedes copiar el comando SSH exacto desde el menu del servicio en Railway. Introduce credenciales solo en tu navegador o terminal, nunca en el chat.

Dentro del contenedor remoto:

```sh
flask --app app init-db --confirm-empty
flask --app app check-backend
flask --app app create-operator --email TU-CORREO --name "TU NOMBRE"
exit
```

Sustituye correo y nombre. El ultimo comando solicita la contrasena oculta y su confirmacion; no existe un usuario/contrasena predeterminado. Crea el operador solo una vez. Los clientes se dan de alta despues desde la web de operadores.

`init-db` utiliza `MYSQL_DATABASE` y no borra tablas. En una BD vacia instala el esquema; en un esquema completo no cambia datos; si encuentra tablas parciales o ajenas se detiene. No es una migracion. Un fallo de DDL requiere revision, no reintentar ALTER a ciegas.

`railway run` ejecuta en tu PC con variables remotas y no te introduce en la red privada de Railway; por eso se usa **railway ssh**.

### Alternativa: importar el archivo SQL

El archivo listo para importar es [sql/railway_schema.sql](sql/railway_schema.sql). Contiene las ocho tablas, indices, restricciones y relaciones, sin datos ni nombre fijo de base.

1. Utiliza exclusivamente una base vacia. Si ya ejecutaste `init-db`, no importes este archivo ni los SQL numerados.
2. Si prefieres un cliente SQL como DBeaver, crea temporalmente un **TCP Proxy/Public Access** en el servicio MySQL. Usa el host/puerto publico y las credenciales mostradas por Railway, no el hostname privado. El trafico por TCP Proxy puede tener coste.
3. Conecta el cliente, selecciona la base indicada por `MYSQLDATABASE` y abre `railway_schema.sql` con codificacion UTF-8. Ejecuta el script completo una sola vez. No contiene `DROP`, `CREATE DATABASE`, `USE` ni usuarios presembrados.
4. Comprueba las tablas `users`, `households`, `devices`, `auth_sessions`, `auth_throttle`, `telemetry`, `incidents`, `incident_events`.
5. Cierra la conexion y elimina el acceso publico si no lo necesitas. Por SSH en **energia-api**, ejecuta `flask --app app check-backend` y crea el operador con el comando anterior.

El SQL de esta entrega es un esquema inicial, **no una copia de tu BD local**. Migrar datos existentes exige backup y restauracion revisados por separado.

### Activar los controles del despliegue

Con las tablas ya creadas, configura **energia-api**:

| Ajuste | Valor |
| --- | --- |
| Pre-deploy command | `flask --app app check-backend` |
| Healthcheck path | `/api/ready` |
| Healthcheck timeout | 120 segundos |
| Replicas iniciales | 1 |

Redespliega. En PowerShell:

```powershell
Invoke-RestMethod 'https://TU-API.up.railway.app/api/ready'
```

Resultado esperado: `status=ok`, `database=ok`, `ai=ok`. `/api/health` no sustituye esta comprobacion. El healthcheck de despliegue no reemplaza monitorizacion continua.

## 6. Web de operadores

1. Anade un servicio desde `TDPEROS-ORG/Web` y llamalo **energia-web**.
2. Usa el `Dockerfile` de la raiz. Deja el comando de inicio predeterminado de nginx.
3. Configura `API_UPSTREAM=https://TU-API.up.railway.app`, sustituyendo el dominio. **Sin `/api` y sin `/` al final**. La imagen lee `PORT`; si no lo defines, usa 8080.
4. Healthcheck: `/healthz`. Este verifica nginx; comprueba tambien `/api/ready` desde la web para verificar su conexion a la API.
5. Genera su dominio HTTPS y abre `https://TU-WEB.up.railway.app/operador`.
6. En las variables de **energia-api**, cambia `CORS_ORIGINS` por `https://TU-WEB.up.railway.app`, sin ruta ni barra final. Redespliega la API.
7. Entra con el operador que creaste por CLI. Crea un cliente, un hogar y registra su dispositivo. La clave del dispositivo se muestra al generarla: guardala fuera de GitHub.

El navegador usa `/api` en el mismo dominio de la web. nginx reenvia a la API manteniendo cookies y CSRF; por eso se conserva `SameSite=Strict`, `Secure=True` y no hay que habilitar cookies de terceros ni modificar el frontend para hacer peticiones a otro origen.

## 7. Movil: Expo/EAS, no Railway

Sigue el [README de Mobile](https://github.com/TDPEROS-ORG/Mobile#readme). Define `EXPO_PUBLIC_API_URL=https://TU-API.up.railway.app/api` con el dominio real. Es una URL publica incrustada al compilar; nunca pongas secretos en variables `EXPO_PUBLIC_*`.

Para instalar en Android, usa el perfil EAS **preview** que genera APK. Para Google Play, el perfil **production** genera AAB. Requiere entrar en tu cuenta Expo, vincular el proyecto y generar/configurar la firma de Android. No se ha ejecutado una compilacion remota, generado un APK firmado ni publicado en una tienda desde esta entrega. Revisa cuotas/costes de EAS antes de iniciar el build.

El usuario movil es el cliente creado desde la web, no el operador. Su autenticacion usa Bearer y SecureStore en Android, no la cookie de operadores. Al cambiar la URL, vuelve a compilar/recargar la app.

## 8. Kafka y consumidor, si los necesitas

1. Sigue la seccion 1 de [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md) para crear el broker privado **kafka** con `apache/kafka:4.0.2`, el volumen `/var/lib/kafka/data` y [kafka.railway.env.example](kafka.railway.env.example). Conserva el cluster ID entre despliegues. No expongas el broker a Internet.
2. Anade a **energia-api** las variables de [.env.kafka.railway.example](.env.kafka.railway.example), ademas de las variables base. El primer despliegue sin Kafka no debe referenciar un servicio inexistente.
3. Crea **energia-consumer** desde el mismo repo Backend y Dockerfile. Mismas variables base y Kafka, con `KAFKA_CLIENT_ID=energia-consumer`.
4. Start command: `python run_kafka_consumer.py`. Pre-deploy: `flask --app app check-backend`. Sin dominio ni healthcheck HTTP. Una replica y reinicio ante fallo; desactiva reposo/serverless del broker y consumidor.
5. Prueba `/api/telemetry/broker` con un dispositivo registrado y verifica la lectura persistida, no solo el HTTP de aceptacion.

Es un broker unico, sin HA. El procesamiento es al menos una vez: puede duplicar tras guardar y fallar el commit Kafka. El topic raw contiene claves de dispositivo; limita acceso, backups y retencion. Kafka puede consumir mas recursos que la API y el modelo.

## 9. Verificacion final en tu cuenta

- Actions en verde en Backend, Web y Mobile; activa Wait for CI en API y Web.
- `/api/ready` de API y Web devuelve estado preparado.
- La web carga imagen y recursos, permite login de operador y crear un cliente/hogar.
- El cliente inicia sesion en el movil contra HTTPS y solo ve su hogar.
- Una lectura de dispositivo registrado se guarda y actualiza la autonomia; prueba Kafka tambien si lo has desplegado.
- Reinicia/recrea un servicio y confirma que MySQL conserva datos por su volumen.
- Revisa presupuestos, backups/restauracion, logs y las advertencias de dependencias del README de Mobile antes de uso real.

Las pruebas locales no demuestran estos pasos remotos. No reutilices el stack temporal `compose.verify.yml` como una base de produccion.

## Referencias oficiales

- https://docs.railway.com/services
- https://docs.railway.com/guides/github-autodeploys
- https://docs.railway.com/guides/mysql
- https://docs.railway.com/guides/cli
- https://docs.expo.dev/build/eas-json/