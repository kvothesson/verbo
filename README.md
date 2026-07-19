# VERBO

> *"En el principio fue el Verbo. Al final, también."*

**Un coding agent en tu terminal, a costo cero.** Solo necesitás una compu con
Python y una API key gratuita. Sin suscripciones, sin tarjeta de crédito, sin
hardware especial. Pensado para que cualquier persona — estudiante, dev que
recién arranca, o cualquiera con curiosidad — tenga el poder de un agente de
código sin pagar un peso.

## ¿Por qué existe?

Los agentes comerciales (Claude Code, Codex, Cursor) son excelentes pero
cuestan plata, y sus prompts gigantes (~55.000 tokens por request) no entran
en los límites de los tiers gratuitos. VERBO invierte la ecuación: un prompt
de sistema de ~1.000 tokens y 4 herramientas esenciales, diseñado desde cero
para que los tiers gratis alcancen.

Verificado funcionando con el **tier gratis de Groq** (gpt-oss-120b): crea
archivos, ejecuta código, encuentra bugs, los arregla con ediciones mínimas
y verifica su propio trabajo.

## Instalación (2 minutos)

```
pip install openai
```

Eso es todo. `verbo.py` es un solo archivo, sin más dependencias.

## Conseguí tu key gratis (elegí una)

| Proveedor | Key gratis en | Ideal para |
|---|---|---|
| **Groq** | https://console.groq.com/keys | Velocidad absurda (hardware LPU) |
| **Cerebras** | https://cloud.cerebras.ai | 1M tokens/día gratis del mismo gpt-oss-120b, sin tarjeta |
| **Gemini** | https://aistudio.google.com/apikey | Flash/Flash-Lite gratis con límites diarios chicos (desde 2026 los Pro son solo pagos, y habilitar billing elimina el tier gratis del proyecto) |
| **OpenRouter** | https://openrouter.ai/settings/keys | Variedad de modelos `:free` |
| **Ollama** | https://ollama.com — sin key | 100% local y privado, sin internet |

Guardá la key como variable de entorno o en un archivo `.env` junto al script:

```
GROQ_API_KEY=gsk_...
```

## Uso

```bash
# Una tarea puntual
python verbo.py -p "creá un script que descargue el clima de Buenos Aires"

# Modo interactivo (conversación con contexto)
python verbo.py

# Elegir modelo/proveedor (formato: proveedor/modelo)
python verbo.py -m groq/llama-3.3-70b-versatile -p "..."
python verbo.py -m gemini/gemini-2.5-flash -p "..."
python verbo.py -m openrouter/openai/gpt-oss-20b:free -p "..."
python verbo.py -m ollama/qwen2.5-coder:7b -p "..."

# Sin confirmación antes de cada comando (más fluido, más riesgo)
python verbo.py --auto -p "..."
```

VERBO trabaja sobre **la carpeta donde estás parado**, y las keys las lee de
`~/.verbo.env` desde cualquier lado. Para invocarlo como `verbo` en cualquier
carpeta, creá un lanzador en algún directorio de tu PATH:

```powershell
# Windows: crea verbo.cmd en los Scripts de Python (ya está en el PATH)
"@echo off`npython `"C:\ruta\a\verbo.py`" %*" |
  Out-File "$(Split-Path (Get-Command python).Source)\Scripts\verbo.cmd" -Encoding ascii
```

```bash
# Linux/Mac: alias en tu shell
echo 'alias verbo="python /ruta/a/verbo.py"' >> ~/.bashrc
```

## Qué puede hacer

- **leer** archivos · **escribir** archivos · **editar** (reemplazo quirúrgico) · **ejecutar** comandos
- Loop agéntico: intenta, ve el error, corrige, verifica — hasta 20 iteraciones por pedido
- Manejo de rate limits: cada 429 enfría solo ese modelo por el tiempo exacto
  que informa el error y sigue con el resto de la cadena; cuando el cupo del
  modelo más capaz se renueva, recupera la prioridad automáticamente (los
  límites de Groq son por modelo: la cadena multiplica el presupuesto gratis)
- Auto-corrección: si el modelo alucina una herramienta inexistente, se lo señala y sigue
- Compactación de contexto: descarta resultados viejos para no explotar los límites

## Evals

El repo incluye una mini-suite estilo SWE-bench en [`evals/`](evals/): 12 tareas
con verificación automática — 6 agénticas (arreglar bugs, refactors
multi-archivo, bugs enterrados en codebases, TDD, tests rojos con detector de
trampa) y 6 de [BigCodeBench-Hard](https://github.com/bigcode-project/bigcodebench),
el benchmark 2024 donde los mejores modelos rondan 30-40% de pass rate.
Soporta corridas repetidas (`-r 3`) para medir varianza y `--puro` para
comparar modelos aislados sin fallbacks.

La suite se poda con datos: HumanEval completo (2021) fue retirado tras
verificar que la cadena lo pasaba 11/11 — incluso sus 6 problemas con peor
pass rate histórico. Medir lo que nunca falla es gastar tokens en cero
información. Resultados de referencia (2026-07-19): cadena default **14/14**
en la nube; benchmark aislado: **cerebras/gpt-oss-120b 27/28 (96%)**.

```bash
cd evals && python correr_evals.py    # corrélo vos mismo, o compará modelos con -m
```

## Qué NO es

No es Claude Code. No tiene sub-agentes, ni permisos finos, ni MCP, ni memoria
persistente. Es el 20% de las funciones que resuelve el 80% de las tareas
chicas y medianas — y es tuyo, legible, y modificable: son ~300 líneas de
Python que podés leer entero en 10 minutos.

## Seguridad

Por defecto VERBO **pide confirmación antes de ejecutar cada comando**.
El flag `--auto` desactiva eso: usalo solo en directorios donde no haya nada
que te duela perder. El agente tiene el mismo poder que vos en la terminal.

## Filosofía

El frío computa, el calor recuerda. Los modelos corren en datacenters lejanos,
pero el agente — el loop, las herramientas, el criterio de qué ejecutar — vive
en tu máquina y te pertenece. Cambiar de proveedor es cambiar un string:
ningún modelo es tu dueño.

---
*Parte del Universo Austral · Creado con la idea de que el poder de los
coding agents no debería depender del poder adquisitivo.*
