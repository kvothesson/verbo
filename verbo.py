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
        "default": "deepseek/deepseek-chat-v3-0324:free",
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
        "Tenés herramientas para leer, escribir y editar archivos, y ejecutar comandos de shell. "
        "Usalas para completar la tarea de punta a punta: no describas lo que harías, hacelo.\n"
        "Reglas:\n"
        "1. Antes de modificar un archivo existente, leelo.\n"
        "2. Hacé el cambio mínimo necesario; preferí 'editar' sobre 'escribir' en archivos existentes.\n"
        "3. Si un comando falla, leé el error y corregí. No repitas el mismo comando esperando otro resultado.\n"
        "4. Verificá tu trabajo ejecutándolo cuando sea posible.\n"
        "5. Respondé siempre en español, breve y directo. Al terminar, resumí qué hiciste en una o dos líneas.\n"
        "6. Sé frugal con los tokens: no imprimas archivos enteros en tus respuestas ni repitas contenido que ya está en el historial."
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
            ruta.write_text(contenido.replace(args["buscar"], args["reemplazar"], 1), encoding="utf-8")
            return f"OK: editado {ruta}"

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


def llamar_con_reintentos(client, modelo, mensajes):
    for intento in range(5):
        try:
            respuesta = client.chat.completions.create(
                model=modelo, messages=mensajes, tools=HERRAMIENTAS, temperature=0.2)
            ESTADISTICAS["llamadas"] += 1
            if respuesta.usage:
                ESTADISTICAS["tokens"] += respuesta.usage.total_tokens or 0
            return respuesta
        except RateLimitError as e:
            m = re.search(r"try again in ([0-9.]+)s", str(e))
            espera = min(60.0, float(m.group(1)) + 1) if m else 15.0 * (intento + 1)
            print(f"  [límite de tasa del proveedor; esperando {espera:.0f}s...]")
            time.sleep(espera)
    raise SystemExit("ERROR: demasiados límites de tasa seguidos. Probá otro modelo (-m) o esperá un minuto.")


def turno(client, modelo, mensajes, auto):
    """Un pedido del usuario: itera hasta que el modelo deja de pedir herramientas."""
    for _ in range(MAX_TURNOS):
        compactar(mensajes)
        try:
            respuesta = llamar_con_reintentos(client, modelo, mensajes)
        except BadRequestError as e:
            # Algunos proveedores (Groq) devuelven 400 si el modelo alucina una
            # herramienta inexistente; se lo devolvemos para que se corrija.
            if "tool" in str(e).lower():
                print("  [el modelo llamó una herramienta inexistente; corrigiendo...]")
                mensajes.append({"role": "user", "content":
                    "[sistema] Llamaste una herramienta que no existe. Las únicas herramientas "
                    "disponibles son: leer, escribir, editar, ejecutar. Reintentá con una de esas."})
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
            detalle = args.get("comando") or args.get("ruta") or ""
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
    args = parser.parse_args()

    cargar_env()

    partes = args.modelo.split("/", 1)
    if partes[0] not in PROVEEDORES:
        print(f"Proveedor desconocido: '{partes[0]}'. Opciones: {', '.join(PROVEEDORES)}")
        sys.exit(1)
    prov = PROVEEDORES[partes[0]]
    modelo = partes[1] if len(partes) > 1 and partes[1] else prov["default"]

    api_key = "sin-key"
    if prov["key_env"]:
        api_key = os.environ.get(prov["key_env"], "")
        if not api_key:
            print(f"Falta la key: definí {prov['key_env']} (conseguila gratis en {prov['key_url']})")
            sys.exit(1)

    client = OpenAI(base_url=prov["base_url"], api_key=api_key)
    mensajes = [{"role": "system", "content": prompt_sistema()}]

    print(f"VERBO · {partes[0]} · {modelo} · {os.getcwd()}")

    if args.prompt:
        inicio = time.time()
        mensajes.append({"role": "user", "content": args.prompt})
        turno(client, modelo, mensajes, args.auto)
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
        turno(client, modelo, mensajes, args.auto)


if __name__ == "__main__":
    main()
