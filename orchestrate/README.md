# Agentes de Andes Travel en watsonx Orchestrate

Esta carpeta es la copia en archivos de los agentes de **Andes Travel** que viven en una
instancia de **watsonx Orchestrate** (us-south) compartida con otros proyectos. El flujo
es el mismo de siempre con código: `pull` trae lo que hay en la instancia, se cambian los
archivos, se revisa con `plan` y se aplica con `push`.

| Agente (archivo) | Nombre visible | Rol |
|---|---|---|
| `Untitled_Agent_1_5717pu` | `andes_supervisor` | Enruta cada solicitud al especialista |
| `Untitled_Agent_1_4902je` | `Profiling-agent` | Perfil del viajero |
| `Untitled_Agent_1_7981KD` | `recommendation_agent` | Recomendaciones (KB `knowledge_agent_2_4375oE`) |
| `Untitled_Agent_1_4480sA` | `quotation_agent` | Cotizaciones |
| `Untitled_Agent_1_2169Mf` | `reservations_agent` | Reservas |

## Alcance

La instancia tiene agentes de otros proyectos que **no** se versionan aquí. El alcance
está en [environment.yaml](environment.yaml) (`scope.agents`): se parte de
`andes_supervisor`, se siguen sus colaboradores y se trae solo lo que esos agentes usan.
Para versionar un agente nuevo de Andes Travel, agrégalo como colaborador del supervisor
o añádelo a `scope.agents`.

Los agentes apuntan a una configuración de voz (`voice_configuration`) de otro proyecto.
La referencia se conserva en sus YAML, pero la configuración en sí no se versiona
(`scope.voice_configs: false`).

## Qué hay aquí

| Carpeta | Contenido | Se exporta con |
|---|---|---|
| `agents/` | Un YAML por agente (instrucciones, LLM, tools, colaboradores, KB, voz) | `orchestrate agents export --agent-only` |
| `tools/openapi/` | Un OpenAPI de una sola operación por tool | reconstruido desde la spec del tool (ver abajo) |
| `tools/python/<tool>/` | Código, `requirements.txt` y `tool.meta.yaml` (función y connections) | `orchestrate tools export` |
| `toolkits/` | Servidores MCP | `orchestrate toolkits export` |
| `knowledge_bases/` | Configuración de cada knowledge base | `orchestrate knowledge-bases export` |
| `connections/` | Configuración de cada connection, **sin credenciales** | `orchestrate connections export` |
| `voice_configs/` | Configuraciones de voz usadas por agentes, sin API keys (desactivado) | `orchestrate voice-configs export` |
| `skills/<skill>/` | `SKILL.md` y `WXO.yaml` (tools que usa la skill) | `orchestrate skills export` |

Hoy los agentes de Andes solo usan una knowledge base; las carpetas de tools, toolkits,
connections y skills aparecen cuando algún agente en alcance empiece a usarlos.

**Lo que no está en el repo:**

- Credenciales de connections. Al crear una connection nueva hay que configurarla con
  `orchestrate connections set-credentials`.
- Documentos de las knowledge bases. La plataforma no los exporta; solo su configuración.
- Tools de tipo *agentic workflow*, que el export solo entrega desde Developer Edition.

## Preparación (una vez por persona)

1. Instalar el ADK en un Python soportado (3.11–3.13):

   ```bash
   uv tool install --python 3.12 ibm-watsonx-orchestrate
   ```

2. En watsonx Orchestrate: ícono de usuario → **Settings** → **API details** → *Generate API key*.
3. Registrar y activar el ambiente (pide el API key):

   ```bash
   orchestrate env add -n redeban-saas -u https://api.us-south.watson-orchestrate.cloud.ibm.com/instances/f3dc0bb6-10f6-4b2c-a4a9-12083e2f49a2 --type ibm_iam --activate
   ```

   Si el token vence: `orchestrate env activate redeban-saas`.

Los scripts usan el intérprete del ADK (`$(uv tool dir)/ibm-watsonx-orchestrate/bin/python`)
porque llaman a su librería. Se niegan a correr si el ambiente activo no es `redeban-saas`.

## Día a día

```bash
make wxo-pull                         # instancia -> archivos (sobrescribe orchestrate/)
git diff orchestrate/                 # qué cambió en la instancia (p. ej. desde la UI)
# ... editar YAMLs ...
make wxo-plan                         # archivos vs. instancia: local only / changed / remote only
make wxo-push                         # dry run: qué se aplicaría y en qué orden
make wxo-push APPLY=1                 # aplica
make wxo-push APPLY=1 ONLY=agents/Untitled_Agent_1_5717pu   # solo un recurso (prefijo kind/nombre)
```

Recomendación: antes de editar, `make wxo-pull` y commit. Así el diff de tu cambio
queda limpio y cualquier cambio hecho por compañeros desde la UI aparece primero.

### Cómo aplica `push`

- Compara los archivos con un pull fresco y solo sube lo **nuevo** o **cambiado**.
- Orden: connections → voice configs → toolkits → knowledge bases → tools → skills →
  agentes, con los colaboradores antes que el agente que los llama.
- Solo toca recursos en alcance; los agentes de otros proyectos no se leen ni se modifican.
- **Nunca borra** nada de la instancia; lo que existe allá (en alcance) y no aquí se
  reporta como `remote-only`.
- Connections, voice configs, toolkits y knowledge bases solo se **crean** si no existen;
  para sobrescribirlas hay que pasar `UPDATE_SAFE=1`, porque en la instancia guardan cosas
  que los archivos no tienen (credenciales, documentos, selección de tools MCP).
- Tools, skills y agentes se crean o actualizan por nombre.

### Tools OpenAPI

Los tools creados desde la UI no tienen un OpenAPI subido, y `orchestrate tools export`
los salta. `scripts/openapi_codec.py` reconstruye un OpenAPI de una operación a partir
de la spec del tool, y `push` lo vuelve a convertir con la misma función del ADK
(`create_openapi_json_tool`), forzando el nombre exacto. Se verificó ida y vuelta sin
diferencias sobre los 455 tools OpenAPI de la instancia. La connection va en la extensión
`x-ibm-orchestrate-app-id` de la operación y se resuelve por `app_id` en la instancia.

Para editar un tool: `summary` es el nombre visible, `description` es lo que lee el
agente para decidir cuándo usarlo, y `parameters` / `requestBody` / `responses` son el
esquema de entrada y salida.

## Calidad de los agentes (antes de cada push)

```bash
make test               # API y reglas (deterministas, también en CI)
make wxo-eval           # 10 historias golden con usuario simulado, 2 corridas, juez en Supabase
make test-adversarial   # 30 ataques (promptfoo) con umbral por categoría
make wxo-refine         # build/refine/report.md: qué falló, para proponer correcciones
make wxo-gate           # las tres primeras juntas: si falla, no hay push
```

- **Historias golden** (`tests/orchestrate/golden/`): casos de `orchestrate evaluations`.
  Un LLM hace de viajero siguiendo la `story` y se revisan los tool calls y la respuesta.
  Las fechas van como `{d+N}` (días desde hoy en Colombia), así no caducan. Las claves
  `x_db`, `x_seed` y `x_holdout` son nuestras: lo que debe quedar en Supabase, el perfil
  que el viajero ya tiene y si la historia está apartada del ciclo de refinamiento.
- **Juez determinista** (`scripts/golden.py judge`): total = tarifa × viajeros (+ seguro),
  duración = la del paquete, `idempotency_key = res-<quote_id>`, perfil solo con
  consentimiento y `persona_prompt` en español.
- **Adversarial** (`tests/adversarial/`): cada caso es una conversación nueva del
  supervisor en draft. Las categorías críticas exigen 100 %; el resto, ≥ 90 %.
- **Ciclo de refinamiento**: `make wxo-refine` junta los fallos; el crítico propone
  cambios de instrucciones, tools o insumos **dentro de** `orchestrate/scope.yaml`; lo
  demás va a `docs/backlog.md`. Una persona aprueba antes de `make wxo-push APPLY=1`. Los
  casos *holdout* solo muestran pasa/falla, para no ajustar las instrucciones a ellos.
- Todo escribe viajeros `test+…@andes.test` en Supabase. `make test-travelers-clean` los
  borra (golden y adversariales); nunca toca otros viajeros.
