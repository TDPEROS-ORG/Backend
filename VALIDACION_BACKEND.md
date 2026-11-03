# Validacion de la entrega backend

Fecha: 25/10/2026. Alcance: backend local; sin pruebas del movil/web ni despliegue remoto.

## Resultados ejecutados

| Comprobacion | Resultado |
|---|---|
| Regresion Windows, Python aislado + MySQL local temporal | 32/32 OK, 34.374 s |
| Regresion Linux, imagen Docker + MySQL 8.4 temporal | 32/32 OK, 8.750 s |
| Docker build con dependencias fijadas | OK |
| pip check dentro de la imagen | OK |
| Carga del modelo con warnings tratados como error | OK |
| Gunicorn HTTP, BD sin esquema | /api/ready = 503 |
| CLI init-db, primera ejecucion | Esquema creado |
| CLI init-db, segunda ejecucion | Sin cambios |
| Rechazo de esquema parcial y nombre inseguro | OK |
| CLI check-backend, MySQL + columnas de 8 tablas + modelo | OK |
| Login, cookie de operador y lectura de historico por HTTP real | OK |
| Bearer de cliente y aislamiento entre dos hogares | OK |
| POST sin deviceKey | 401 |
| IA real + persistencia por HTTP | OK |
| HTTP broker -> Kafka 4.0.2 -> consumidor -> MySQL | OK |
| JSON Kafka invalido seguido de mensaje valido | Rechazo y continuacion OK |
| Recrear broker con volumen manteniendo offsets | OK, rural-energy.telemetry.raw:0:2 antes y despues |
| Fallo BD y fallo commit Kafka simulados por unittest | Sin commit indebido |
| CORS permitido/ajeno, Secure + SameSite, CSRF, expiracion y rotacion de claves | OK |
| Diagnosticos de archivos Python modificados | Sin errores reportados |

La prueba HTTP completa se ejecuto primero desde stdin y despues mediante `python -m tests.verify_stack`, ya incluido en la imagen. MySQL y Kafka no tuvieron puertos publicados. Solo la API utilizo un puerto aleatorio restringido a 127.0.0.1.

## Modelo

Artefacto original: `models/modelo_autonomia_residual.pkl`, 3647 bytes. No se ha cambiado ni reentrenado.

En la investigacion previa, 64 predicciones en el entorno original y en el candidato fijado dieron el mismo resultado. SHA-256 del JSON comparado: `9b41da99ffea073457f90e1894137a64268c481435c9438d7785ab1d51c8a8cd`. El candidato uso scikit-learn 1.8.0, igual que la version declarada por el artefacto. Esto no acredita disponer del lock completo del entrenamiento original.

El Dockerfile repite la carga estricta del modelo en cada construccion. El dataset no es necesario para servir predicciones y se excluye del ZIP/imagen.

## Integridad y exclusiones

`package-backend.ps1` copia solo una lista permitida de archivos, valida texto UTF-8 sin NUL, crea `MANIFEST.sha256.json`, genera el ZIP y verifica los bytes de todas sus entradas contra el manifiesto. Genera tambien un SHA-256 externo del ZIP. Incluye el modelo original, no rutas absolutas de Windows.

Excluidos: `.env` privado, contrasenas reales, cuentas de prueba generadas, dataset, frontends, entornos Python, caches y el archivo ajeno `tests/}`. Las credenciales fijas de los unit tests son fixtures ficticios, no cuentas reales ni credenciales de despliegue.

## Lo que no se ha validado

No se han creado servicios en Railway ni ejecutado migraciones contra una BD real. No se ha verificado el navegador movil/web, cookies entre dominios publicos, HTTPS remoto, autenticacion Railway, reglas de red de tu proyecto, entrega de un dispositivo fisico, backups/restauracion ni una prueba de carga.

La contraprueba de caida de BD del consumidor usa mocks; el recorrido Kafka normal y el rechazo de JSON invalido si se ejecutaron con broker y BD reales. El consumidor es at-least-once, no exactly-once. No hay deduplicacion ni DLQ. Las imagenes base usan tags de versiones; las dependencias Python estan fijadas pero no es una certificacion de ausencia de vulnerabilidades ni una reconstruccion bit a bit.

**REQUIERE CODIGO:** los cambios descritos estan aplicados en el entregable. **FUNCIONAL:** crear/configurar infraestructura y cerrar las pruebas remotas indicadas en la guia.