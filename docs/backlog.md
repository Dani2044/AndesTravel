# Backlog fuera del alcance de la PoC

Sugerencias del ciclo de refinamiento (`make wxo-refine`) que no caben en
`orchestrate/scope.yaml`. Se revisan después de la demo.

| Fecha | Sugerencia | Por qué está fuera | Origen |
|---|---|---|---|
| 2026-11-10 | Fusionar perfilamiento en el supervisor como tool | Cambio de diseño; el supervisor está al límite de su presupuesto de instrucciones | Revisión de agentes |
| 2026-11-10 | Fusionar reservas dentro de cotización (el `quote_id` queda en un solo agente) | Cambio de diseño; g06 pasa 3/3 | Revisión de agentes |
| 2026-11-10 | Reemplazar la KB del catálogo por una tool determinista `list_packages` | La KB es parte de la historia L3 de la demo | Revisión de agentes |
| 2026-11-10 | Agente de postventa ("mis reservas"; cambios y cancelaciones van a un humano) | No estaba en el alcance de la semana | Revisión de agentes |
| 2026-11-10 | Guardia de afirmaciones falsas ("escalé", "guardé", "reservé" sin tool con ok=true) | Extiende `price_guard`; fase 2 | Revisión de agentes |
| 2026-11-10 | Guardia de entrada (`agent_pre_invoke`) y ligar el hilo del chat al `traveler_id` | Los ataques ya pasan 32/32; requiere más investigación | Revisión de agentes |
| 2026-11-13 | Identidad verificada (SSO o código por correo) en lugar de un correo escrito en el chat | Fuera del alcance de la PoC (Q4) | Landing con JWT |
| 2026-11-13 | Renovar el JWT del chat sin recargar la página | El cargador de IBM no lee la renovación desde la configuración | Landing con JWT |
| 2026-11-13 | Saludo del chat en español (`welcome_content` del supervisor) | Cosmético | Landing |
