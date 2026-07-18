#!/usr/bin/env python3
"""
Auto-iteración de VERBO: el agente mejora su propio código usando la suite
de evals como juez.

Loop por iteración:
  1. correr la suite (baseline)
  2. un modelo mutador lee verbo.py + el reporte de fallas y propone
     una mejora mínima (ediciones exactas estilo buscar/reemplazar)
  3. aplicar, chequear sintaxis
  4. correr la suite de nuevo (candidato)
  5. si el fitness mejora -> git commit; si no -> git checkout (revert)

Fitness: primero aciertos, después frugalidad de tokens (-10% o más).

Guardrails:
  - Solo se modifica verbo.py; evals/ es intocable (nadie corrige su propio examen)
  - py_compile antes de gastar tokens en evaluar un candidato roto
  - git como memoria: cada mejora aceptada es un commit, cada regresión se revierte
  - máximo de iteraciones explícito; sin loop infinito

Uso:
    python evolucionar.py --iteraciones 1 -r 1
    python evolucionar.py --modelo-agente groq/llama-3.3-70b-versatile \
                          --modelo-mutador groq/openai/gpt-oss-120b -r 2
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AQUI = Path(__file__).parent
REPO = AQUI.parent
ARCHIVO_VERBO = REPO / "verbo.py"

sys.path.insert(0, str(REPO))
import verbo  # reutilizamos PROVEEDORES y cargar_env del propio agente

from openai import OpenAI


def git(*args, check=True):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, check=check,
                          encoding="utf-8", errors="replace")


def correr_suite(modelo_agente, reps, pausa):
    cmd = [sys.executable, str(AQUI / "correr_evals.py"), "-r", str(reps), "--pausa", str(pausa)]
    if modelo_agente:
        cmd += ["-m", modelo_agente]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                       encoding="utf-8", errors="replace")
    print(r.stdout)
    archivos = sorted(AQUI.glob("resultados-*.json"))
    if not archivos:
        raise SystemExit("la suite no generó resultados")
    datos = json.loads(archivos[-1].read_text(encoding="utf-8"))
    resultados = next(iter(datos.values()))
    return {
        "aciertos": sum(t["aciertos"] for t in resultados),
        "total": sum(len(t["corridas"]) for t in resultados),
        "tokens": sum(c["tokens"] for t in resultados for c in t["corridas"]),
        "fallas": [{"tarea": t["tarea"], "detalle": c["detalle"][:400]}
                   for t in resultados for c in t["corridas"] if not c["paso"]],
    }


def pedir_mutacion(client, modelo_mutador, fuente, base):
    reporte = (f"aciertos: {base['aciertos']}/{base['total']} · "
               f"tokens totales: {base['tokens']}\n")
    if base["fallas"]:
        reporte += "FALLAS:\n" + "\n".join(
            f"- [{f['tarea']}] {f['detalle']}" for f in base["fallas"])
    else:
        reporte += "Sin fallas: el objetivo es reducir tokens/llamadas sin romper nada."

    instrucciones = (
        "Sos un ingeniero de agentes LLM. Este es el código completo de un coding "
        "agent minimalista (verbo.py) y el reporte de su suite de evaluación.\n"
        "Proponé UNA mejora mínima y segura al código que suba el pass rate "
        "(o, si no hay fallas, que reduzca el consumo de tokens). Puede ser al "
        "prompt de sistema, al manejo de errores, al loop, o a las herramientas.\n"
        "Reglas estrictas:\n"
        "- Máximo 3 ediciones de tipo buscar/reemplazar con texto EXACTO y único\n"
        "- No agregar dependencias nuevas ni cambiar la interfaz de línea de comandos\n"
        "- Cambios conservadores: mejor una mejora chica que un rediseño\n"
        "Respondé SOLO con un JSON válido con esta forma:\n"
        '{"razon": "una línea explicando la mejora", '
        '"ediciones": [{"buscar": "texto exacto actual", "reemplazar": "texto nuevo"}]}'
    )
    r = client.chat.completions.create(
        model=modelo_mutador, temperature=0.4,
        messages=[
            {"role": "system", "content": instrucciones},
            {"role": "user", "content": f"REPORTE:\n{reporte}\n\nCODIGO:\n{fuente}"},
        ])
    texto = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return None
    try:
        mut = json.loads(m.group(0))
        assert isinstance(mut.get("ediciones"), list) and mut["ediciones"]
        return mut
    except (json.JSONDecodeError, AssertionError):
        return None


def aplicar(fuente, ediciones):
    for ed in ediciones[:3]:
        buscar = ed.get("buscar", "")
        if fuente.count(buscar) != 1:
            return None, f"edición no aplicable (apariciones={fuente.count(buscar)}): {buscar[:80]!r}"
        fuente = fuente.replace(buscar, ed.get("reemplazar", ""), 1)
    return fuente, None


def compila():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(ARCHIVO_VERBO)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def es_mejor(cand, base):
    if cand["aciertos"] != base["aciertos"]:
        return cand["aciertos"] > base["aciertos"]
    return cand["tokens"] < base["tokens"] * 0.9


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteraciones", type=int, default=1)
    parser.add_argument("--modelo-agente", default=None,
                        help="Modelo que usa VERBO en los evals (default: el de verbo.py)")
    parser.add_argument("--modelo-mutador", default="groq/openai/gpt-oss-120b",
                        help="Modelo que propone las mejoras al código")
    parser.add_argument("-r", "--repeticiones", type=int, default=1)
    parser.add_argument("--pausa", type=int, default=15)
    args = parser.parse_args()

    if git("status", "--porcelain").stdout.strip():
        raise SystemExit("el repo tiene cambios sin commitear; commiteá o revertí antes de evolucionar")

    verbo.cargar_env()
    partes = args.modelo_mutador.split("/", 1)
    prov = verbo.PROVEEDORES[partes[0]]
    import os
    client = OpenAI(base_url=prov["base_url"],
                    api_key=os.environ.get(prov["key_env"] or "", "sin-key"))
    modelo_mutador = partes[1]

    print(f"[evolucion] baseline con agente={args.modelo_agente or '(default)'}")
    base = correr_suite(args.modelo_agente, args.repeticiones, args.pausa)
    print(f"[evolucion] baseline: {base['aciertos']}/{base['total']} · {base['tokens']} tokens")

    for i in range(1, args.iteraciones + 1):
        print(f"\n[evolucion] iteración {i}: pidiendo mutación a {args.modelo_mutador}")
        fuente = ARCHIVO_VERBO.read_text(encoding="utf-8")
        mut = pedir_mutacion(client, modelo_mutador, fuente, base)
        if not mut:
            print("[evolucion] el mutador no produjo una mutación válida; salto iteración")
            continue
        print(f"[evolucion] propuesta: {mut.get('razon', '(sin razón)')}")

        nueva, err = aplicar(fuente, mut["ediciones"])
        if err:
            print(f"[evolucion] {err}; salto iteración")
            continue
        ARCHIVO_VERBO.write_text(nueva, encoding="utf-8")

        ok, err_compilacion = compila()
        if not ok:
            print(f"[evolucion] el candidato no compila; revert. {err_compilacion.strip()[:200]}")
            git("checkout", "--", "verbo.py")
            continue

        print("[evolucion] evaluando candidato...")
        cand = correr_suite(args.modelo_agente, args.repeticiones, args.pausa)
        print(f"[evolucion] candidato: {cand['aciertos']}/{cand['total']} · {cand['tokens']} tokens "
              f"(baseline: {base['aciertos']}/{base['total']} · {base['tokens']})")

        if es_mejor(cand, base):
            git("add", "verbo.py")
            git("commit", "-m",
                f"auto-iteración: {mut.get('razon', 'mejora')}\n\n"
                f"Fitness: {base['aciertos']}/{base['total']} ({base['tokens']} tok) -> "
                f"{cand['aciertos']}/{cand['total']} ({cand['tokens']} tok)\n\n"
                "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>")
            print("[evolucion] MEJORA ACEPTADA — commit hecho")
            base = cand
        else:
            git("checkout", "--", "verbo.py")
            print("[evolucion] sin mejora — revert")

    print(f"\n[evolucion] FIN · fitness final: {base['aciertos']}/{base['total']} · {base['tokens']} tokens")


if __name__ == "__main__":
    main()
