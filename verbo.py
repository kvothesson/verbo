#!/usr/bin/env python3
"""
VERBO — agente de código minimalista, multi-proveedor, a costo cero.

Pensado para que cualquiera pueda tener un coding agent en su terminal
usando solo tiers gratis (Groq, Gemini, OpenRouter) o modelos locales (Ollama).
El prompt de sistema pesa ~1k tokens para entrar en los límites de tokens/minuto
de los tiers gratuitos.

Uso:
    python verbo.py -p "creá un script que ..."          # una tarea y sale
    python verbo.py                                       # modo interactivo
    python verbo.py -m groq/llama-3.3-70b-versatile -p "..."
    python verbo.py -m gemini/gemini-2.5-flash -p "..."
    python verbo.py -m ollama/qwen2.5-coder:7b -p "..."

Keys: variables de entorno o un archivo .env en el directorio actual,
junto al script, o en ~/.verbo.env
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from openai import OpenAI, RateLimitError, BadRequestError
except ImportError:
    print("Falta el paquete 'openai'. Instalalo con: pip install openai")
    sys.exit(1)

PROVEEDORES = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "default": "openai/gpt-oss-120b",
        "key_url": "https://console.groq.com/keys",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "default": "openai/gpt-oss-20b:free",
        "key_url": "https://openrouter.ai/settings/keys",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "default": "gemini-2.5-flash",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "key_env": None,
        "default": "qwen2.5-coder:7b",
        "key_url": "https://ollama.com (gratis, local, sin key)",
    },
    "gateway": {
        "base_url": "http://localhost:4000/v1",
        "key_env": "LITELLM_MASTER_KEY",
        "default": "groq/openai/gpt-oss-120b",
        "key_url": "gateway LiteLLM local",
    },
}

ESTADISTICAS = {"llamadas": 0, "tokens": 0}

# Los límites de Groq son POR MODELO: agotar gpt-oss-120b no toca el
# presupuesto de llama ni el de qwen. Fallback = más presupuesto gratis.
FALLBACKS_DEFAULT = ("groq/llama-3.3-70b-versatile,groq/qwen/qwen3.6-27b,"
                     "groq/llama-3.1-8b-instant,groq/openai/gpt-oss-20b,"
                     "openrouter/openai/gpt-oss-20b:free")
CLIENTES = {}

MAX_SALIDA_HERRAMIENTA = 6000   # chars que se devuelven al modelo por herramienta
MAX_CONTEXTO_CHARS = 60000      # umbral para compactar historial
MAX_TURNOS = 20                 # iteraciones del loop agéntico por pedido

HERRAMIENTAS = [
    {"type": "function", "function": {
        "name": "leer",
        "description": "Lee un archivo de texto y devuelve su contenido con números de línea.",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string", "description": "Ruta del archivo, relativa o absoluta"}},
            "required": ["ruta"]}}},
    {"type": "function", "function": {
        "name": "escribir",
        "description": "Crea o sobreescribe un archivo con el contenido dado.",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"},
            "contenido": {"type": "string"}},
            "required": ["ruta", "contenido"]}}},
    {"type": "function", "function": {
        "name": "editar",
        "description": "Reemplaza un texto exacto (única ocurrencia) dentro de un archivo. Más barato que reescribirlo entero.",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"},
            "buscar": {"type": "string", "description": "Texto exacto a encontrar (debe aparecer una sola vez)"},
            "reemplazar": {"type": "string"}},
            "required": ["ruta", "buscar", "reemplazar"]}}},
    {"type": "function", "function": {
        "name": "ejecutar",
        "description": "Ejecuta un comando de shell en el directorio de trabajo y devuelve stdout+stderr y el código de salida.",
        "parameters": {"type": "object", "properties": {
            "comando": {"type": "string"}},
            "required": ["comando"]}}},
    {"type": "function", "function": {
        "name": "buscar",
        "description": "Busca texto literal en los archivos del directorio (recursivo) y devuelve coincidencias como archivo:línea. Útil para encontrar referencias antes de editar o renombrar.",
        "parameters": {"type": "object", "properties": {
            "texto": {"type": "string"},
            "extension": {"type": "string", "description": "Opcional: filtrar por extensión, ej '.py'"}},
            "required": ["texto"]}}},
]


def cargar_env():
    """Carga .env desde cwd, el directorio del script y ~/.verbo.env (sin pisar el entorno)."""
    candidatos = [Path.cwd() / ".env", Path(__file__).parent / ".env", Path.home() / ".verbo.env"]
    for archivo in candidatos:
        if archivo.is_file():
            for linea in archivo.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", linea)
                if m and m.group(1) not in os.environ:
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")


def prompt_sistema():
    return (
        "Sos VERBO, un agente de código que corre en la terminal del usuario. "
        f"Sistema operativo: {platform.system()} {platform.release()}. "
        f"Directorio de trabajo: {os.getcwd()}\n"
        "Tenés herramientas para leer, escribir, editar y buscar en archivos, y ejecutar comandos de shell. "
        "Usalas para completar la tarea de punta a punta: no describas lo que harías, hacelo.\n"
        "Reglas:\n"
        "1. Antes de modificar un archivo existente, leelo.\n"
        "2. Hacé el cambio mínimo necesario; preferí 'editar' sobre 'escribir' en archivos existentes.\n"
        "3. Si un comando falla, leé el error y corregí. No repitas el mismo comando esperando otro resultado.\n"
        "4. Verificá tu trabajo ejecutándolo cuando sea posible.\n"
        "5. Respondé siempre en español, breve y directo. Al terminar, resumí qué hiciste en una o dos líneas.\n"
        "6. Sé frugal con los tokens: no imprimas archivos enteros en tus respuestas ni repitas contenido que ya está en el historial.\n"
        "7. Para crear o modificar archivos usá siempre 'escribir' o 'editar', nunca redirecciones de shell (> o >>): en Windows generan encodings rotos.\n"
        "8. Tras renombrar algo o cambiar una interfaz, usá 'buscar' para encontrar todas las referencias restantes antes de dar por terminado."
    )


def num_lineas(texto):
    return "\n".join(f"{i + 1}\t{l}" for i, l in enumerate(texto.splitlines()))


def truncar(texto, limite=MAX_SALIDA_HERRAMIENTA):
    if len(texto) <= limite:
        return texto
    return texto[:limite] + f"\n[... truncado: {len(texto) - limite} caracteres más]"


def ejecutar_herramienta(nombre, args, auto):
    try:
        if nombre == "leer":
            ruta = Path(args["ruta"])
            if not ruta.is_file():
                return f"ERROR: no existe el archivo {ruta}"
            return truncar(num_lineas(ruta.read_text(encoding="utf-8", errors="replace")))

        if nombre == "escribir":
            ruta = Path(args["ruta"])
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(args["contenido"], encoding="utf-8")
            return f"OK: escrito {ruta} ({len(args['contenido'])} caracteres)"

        if nombre == "editar":
            ruta = Path(args["ruta"])
            if not ruta.is_file():
                return f"ERROR: no existe el archivo {ruta}"
            contenido = ruta.read_text(encoding="utf-8", errors="replace")
            ocurrencias = contenido.count(args["buscar"])
            if ocurrencias == 0:
                return "ERROR: el texto a buscar no aparece en el archivo. Leé el archivo y usá el texto exacto."
            if ocurrencias > 1:
                return f"ERROR: el texto aparece {ocurrencias} veces. Agregá más contexto para que sea único."
            nuevo = contenido.replace(args["buscar"], args["reemplazar"], 1)
            # Guardrail: si el archivo compilaba y la edición lo rompe, rechazarla.
            # (Si ya estaba roto no se bloquea: el modelo puede estar reparándolo.)
            if ruta.suffix == ".py":
                def _compila(texto):
                    try:
                        compile(texto, str(ruta), "exec")
                        return None
                    except SyntaxError as e:
                        return e
                if _compila(contenido) is None and (e := _compila(nuevo)):
                    return (f"ERROR: esta edición rompería la sintaxis de Python "
                            f"(línea {e.lineno}: {e.msg}). NO se aplicó. "
                            "Revisá comillas, paréntesis y escapes, y reintentá.")
            ruta.write_text(nuevo, encoding="utf-8")
            print(f"    - buscar:     {args['buscar'][:200]!r}")
            print(f"    - reemplazar: {args['reemplazar'][:200]!r}")
            return f"OK: editado {ruta}"

        if nombre == "buscar":
            texto = args["texto"]
            ext = args.get("extension") or ""
            coincidencias = []
            for archivo in sorted(Path(".").rglob("*")):
                if set(archivo.parts) & {".git", "__pycache__", "node_modules", ".venv", "venv"}:
                    continue
                if not archivo.is_file() or (ext and archivo.suffix != ext):
                    continue
                try:
                    if archivo.stat().st_size > 1_000_000:
                        continue
                    for i, linea in enumerate(
                            archivo.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if texto in linea:
                            coincidencias.append(f"{archivo}:{i}: {linea.strip()[:120]}")
                            if len(coincidencias) >= 50:
                                break
                except OSError:
                    continue
                if len(coincidencias) >= 50:
                    break
            return truncar("\n".join(coincidencias) or "(sin coincidencias)")

        if nombre == "ejecutar":
            comando = args["comando"]
            if not auto:
                respuesta = input(f"\n  ¿Ejecutar '{comando}'? [s/n] ").strip().lower()
                if respuesta not in ("s", "si", "sí", "y", "yes"):
                    return "El usuario rechazó la ejecución de este comando."
            r = subprocess.run(comando, shell=True, capture_output=True, text=True,
                               timeout=120, encoding="utf-8", errors="replace")
            salida = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
            return truncar(f"[código de salida: {r.returncode}]\n{salida.strip() or '(sin salida)'}")

        return f"ERROR: herramienta desconocida '{nombre}'"
    except subprocess.TimeoutExpired:
        return "ERROR: el comando superó los 120 segundos y fue cancelado."
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def compactar(mensajes):
    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
    total = sum(len(str(m.get("content") or "")) for m in mensajes)
    if total <= MAX_CONTEXTO_CHARS:
        return
    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
            total = sum(len(str(x.get("content") or "")) for x in mensajes)
            if total <= MAX_CONTEXTO_CHARS:
                break


def cliente_para(modelo_completo):
    """Devuelve (cliente, nombre_de_modelo) para un string proveedor/modelo, o None si falta la key."""
    if modelo_completo in CLIENTES:
        return CLIENTES[modelo_completo]
    partes = modelo_completo.split("/", 1)
    prov = PROVEEDORES.get(partes[0])
    if not prov:
        return None
    api_key = "sin-key"
    if prov["key_env"]:
        api_key = os.environ.get(prov["key_env"], "")
        if not api_key:
            return None
    par = (OpenAI(base_url=prov["base_url"], api_key=api_key),
           partes[1] if len(partes) > 1 and partes[1] else prov["default"])
    CLIENTES[modelo_completo] = par
    return par


def llamar_con_reintentos(estado, mensajes):
    """Intenta con el modelo actual; si agota los reintentos por rate limit,
    cae en cascada al siguiente modelo de la lista (presupuestos separados)."""
    while estado["idx"] < len(estado["modelos"]):
        par = cliente_para(estado["modelos"][estado["idx"]])
        if par is None:
            estado["idx"] += 1
            continue
        client, modelo = par
        # Groq en free tier suele devolver 429 casi instantáneo (sin cupo,
        # no por ráfaga): insistir mucho en el mismo modelo quema el presupuesto
        # de tiempo del proceso. Mejor fallar rápido (2 intentos) y probar el
        # siguiente modelo de la cadena, que tiene presupuesto propio intacto.
        for intento in range(2):
            try:
                respuesta = client.chat.completions.create(
                    model=modelo, messages=mensajes, tools=HERRAMIENTAS, temperature=0.2)
                ESTADISTICAS["llamadas"] += 1
                if respuesta.usage:
                    ESTADISTICAS["tokens"] += respuesta.usage.total_tokens or 0
                return respuesta
            except RateLimitError as e:
                m = re.search(r"try again in ([0-9.]+)s", str(e))
                espera = min(30.0, float(m.group(1)) + 1) if m else 10.0 * (intento + 1)
                print(f"  [límite de tasa en {modelo}; esperando {espera:.0f}s...]")
                time.sleep(espera)
        estado["idx"] += 1
        if estado["idx"] < len(estado["modelos"]):
            print(f"  [rate limit persistente; fallback a {estado['modelos'][estado['idx']]}]")
    raise SystemExit("ERROR: todos los modelos de la cadena agotaron su límite de tasa. "
                     "Esperá unos minutos o agregá otro proveedor con --fallback.")


def turno(estado, mensajes, auto):
    """Un pedido del usuario: itera hasta que el modelo deja de pedir herramientas."""
    for _ in range(MAX_TURNOS):
        compactar(mensajes)
        try:
            respuesta = llamar_con_reintentos(estado, mensajes)
        except BadRequestError as e:
            # Algunos proveedores (Groq) devuelven 400 si el modelo alucina una
            # herramienta inexistente o genera un tool call malformado;
            # se lo devolvemos para que se corrija. El sleep evita ráfagas de
            # 400+429 retroalimentándose contra el límite de requests/minuto.
            if "tool" in str(e).lower() or "failed_generation" in str(e):
                print("  [tool call inválido del modelo; corrigiendo...]")
                time.sleep(2)
                mensajes.append({"role": "user", "content":
                    "[sistema] Tu llamada a herramienta fue inválida. Las únicas herramientas "
                    "disponibles son: leer, escribir, editar, ejecutar, buscar. Reintentá."})
                continue
            raise
        msg = respuesta.choices[0].message

        if not msg.tool_calls:
            print(f"\n{msg.content or '(sin respuesta)'}")
            mensajes.append({"role": "assistant", "content": msg.content or ""})
            return

        mensajes.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            } for tc in msg.tool_calls],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            detalle = args.get("comando") or args.get("ruta") or args.get("texto") or ""
            print(f"  → {tc.function.name}: {detalle}")
            resultado = ejecutar_herramienta(tc.function.name, args, auto)
            mensajes.append({"role": "tool", "tool_call_id": tc.id, "content": resultado})

    print("\n[VERBO alcanzó el máximo de iteraciones para este pedido]")


def main():
    parser = argparse.ArgumentParser(description="VERBO — agente de código a costo cero")
    parser.add_argument("-p", "--prompt", help="Tarea única (sin esto, entra en modo interactivo)")
    parser.add_argument("-m", "--modelo", default="groq/openai/gpt-oss-120b",
                        help="proveedor/modelo, ej: groq/llama-3.3-70b-versatile, gemini/gemini-2.5-flash, ollama/qwen2.5-coder:7b")
    parser.add_argument("--auto", action="store_true",
                        help="No pedir confirmación antes de ejecutar comandos")
    parser.add_argument("--fallback", default=os.environ.get("VERBO_FALLBACKS", FALLBACKS_DEFAULT),
                        help="Modelos alternativos si el principal agota su rate limit, "
                             "separados por coma. '' para desactivar.")
    args = parser.parse_args()

    cargar_env()

    partes = args.modelo.split("/", 1)
    if partes[0] not in PROVEEDORES:
        print(f"Proveedor desconocido: '{partes[0]}'. Opciones: {', '.join(PROVEEDORES)}")
        sys.exit(1)
    prov = PROVEEDORES[partes[0]]
    if prov["key_env"] and not os.environ.get(prov["key_env"], ""):
        print(f"Falta la key: definí {prov['key_env']} (conseguila gratis en {prov['key_url']})")
        sys.exit(1)

    cadena = [args.modelo] + [m.strip() for m in args.fallback.split(",")
                              if m.strip() and m.strip() != args.modelo]
    estado = {"modelos": cadena, "idx": 0}
    par = cliente_para(args.modelo)
    modelo = par[1] if par else args.modelo
    mensajes = [{"role": "system", "content": prompt_sistema()}]

    print(f"VERBO · {partes[0]} · {modelo} · {os.getcwd()}")

    if args.prompt:
        inicio = time.time()
        mensajes.append({"role": "user", "content": args.prompt})
        turno(estado, mensajes, args.auto)
        print(f"[verbo-stats] llamadas={ESTADISTICAS['llamadas']} "
              f"tokens={ESTADISTICAS['tokens']} segundos={time.time() - inicio:.1f}")
        return

    print("Modo interactivo. Escribí tu pedido ('salir' para terminar).\n")
    while True:
        try:
            pedido = input("verbo> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not pedido:
            continue
        if pedido.lower() in ("salir", "exit", "quit", "chau"):
            break
        mensajes.append({"role": "user", "content": pedido})
        turno(estado, mensajes, args.auto)


if __name__ == "__main__":
    main()
