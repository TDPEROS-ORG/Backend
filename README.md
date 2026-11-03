# Energia: API, IA y base de datos

API Flask/Gunicorn multiusuario con MySQL, modelo de autonomia en CPU y flujo Kafka opcional.

**REQUIERE CODIGO:** este repositorio contiene la implementacion y el empaquetado Docker.
**FUNCIONAL:** crear y configurar los servicios en Railway, dominios y copias de seguridad.

## Repositorios

| Repositorio | Contenido | Ejecucion |
| --- | --- | --- |
| [Backend](https://github.com/TDPEROS-ORG/Backend) | API, IA, SQL, consumidor y pruebas | Railway |
| [Web](https://github.com/TDPEROS-ORG/Web) | Consola de operadores y proxy nginx | Railway |
| [Mobile](https://github.com/TDPEROS-ORG/Mobile) | Aplicacion Expo/React Native | Telefono; compilacion con Expo/EAS |

GitHub almacena codigo y ejecuta CI. No ejecuta Flask ni aloja MySQL. GitHub Pages no sustituye al servicio Web: este necesita proxy para la autenticacion del mismo origen.

## Desplegar

Sigue [PASO_A_PASO_RAILWAY.md](PASO_A_PASO_RAILWAY.md). Es la guia principal de esta publicacion, con los tres repositorios.

El [SQL completo](sql/railway_schema.sql) crea las ocho tablas sobre una base **vacia seleccionada previamente**. No contiene usuarios, contrasenas, sesiones ni lecturas. Es una alternativa a `flask --app app init-db --confirm-empty`, no una migracion de una BD con datos. No combines su importacion con la ejecucion manual de los SQL numerados.

El Dockerfile incluye el modelo entrenado de confianza; no hace falta GPU, un servicio externo de IA ni el CSV de entrenamiento para inferencia. No cargues modelos pickle de terceros.

## Verificacion

En Docker Linux pasan 32 pruebas y una prueba integrada HTTP/Gunicorn, login, cookies, aislamiento por hogar, IA y Kafka->MySQL. El SQL completo tambien se importo y verifico contra el backend. El workflow de GitHub repite estas comprobaciones en un entorno temporal.

Para repetirlas localmente sigue la seccion 6 de [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md). Esa guia conserva los detalles tecnicos de Kafka. Las pruebas son solo para `compose.verify.yml`, nunca contra datos reales.

`GET /api/health` comprueba proceso/modelo. `GET /api/ready` comprueba tambien MySQL y el esquema y devuelve 503 si faltan.

## Seguridad y alcance

No se incluyen `.env`, claves de dispositivos, datos privados, entornos locales ni datasets. Configura los secretos exclusivamente en Railway. El usuario operador se crea por CLI con contrasena oculta.

Esta entrega no acredita un despliegue en Railway ni una prueba con dispositivos reales. Revisa presupuesto, backups/restauracion, HTTPS y monitorizacion antes de introducir datos reales.