# SmartParking

SmartParking es un proyecto de estacionamiento inteligente que integra servicios de administración, control de acceso y monitoreo de ocupación.

## Componentes

- **API REST:** servicio Java con Spring Boot para las operaciones del sistema.
- **Aplicación web:** interfaz Nuxt para la administración del estacionamiento.
- **Consola del propietario:** aplicación JavaFX para configuración y acceso del propietario.
- **Monitoreo de ocupación:** componente de visión para observar los cajones del estacionamiento.
- **Control de acceso:** firmware ESP32 y puente RFID para comunicar lectores y servicios.
- **Persistencia e infraestructura:** PostgreSQL y archivos de ejecución con Podman.

El código está organizado principalmente en `apps/`, `services/`, `firmware/` e `infra/`.

## Equipo

Proyecto realizado en equipo. Compañero: **Henry Elias Aguilar Vazquez**.
