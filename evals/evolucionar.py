#!/usr/bin/env python3
"""
Auto-iteración de VERBO: el agente mejora su propio código, con la suite
de evals como juez y git como red de seguridad.

El mutador ES el propio VERBO: se lanza una instancia del agente sobre su
propio repositorio con la instrucción de leer verbo.py y aplicar una mejora
mínima usando sus herramientas (leer/editar). Esto es mucho más robusto que
pedir parches "a ciegas" a un modelo: el agente ve el texto exacto del código.

Loop por iteración:
  1. correr la suite (baseline)
  2. VERBO se auto-edita guiado por el reporte de fallas
  3. guardrails: solo verbo.py puede cambiar + py_compile
  4. correr la suite de nuevo (candidato)
  5. si el fitness mejora -> git commit; si no -> git checkout (revert)

Fitness: primero aciertos, después frugalidad de tokens (-10% o más).

Guardrails:
  - si el mutador toca cualquier archivo que no sea verbo.py, se revierte TODO
  - py_compile antes de gastar tokens en evaluar un candidato roto
  - cada mejora aceptada es un commit; cada regresión se revierte
  - iteraciones acotadas; sin loop infinito

Uso:
    python evolucionar.py --iteraciones 1 -r 1
    python evolucionar.py --modelo-agente groq/llama-3.3-70b-versatile \
                          --modelo-mutador groq/openai/gpt-oss-120b -r 2
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AQUI = Path(__file__).parent
REPO = AQUI.parent
ARCHIVO_VERBO = REPO / "verbo.py"


def git(*args, check=True):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, check=check,
                          encoding="utf-8", errors="replace")


def archivos_sin_trackear():
    return {l[3:].strip() for l in git("status", "--porcelain").stdout.splitlines()
            if l.startswith("??")}


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


def mutar_con_verbo(modelo_mutador, base):
    """VERBO se edita a sí mismo guiado por el reporte de la suite."""
    reporte = f"aciertos: {base['aciertos']}/{base['total']} · tokens totales: {base['tokens']}\n"
    if base["fallas"]:
        reporte += "FALLAS OBSERVADAS:\n" + "\n".join(
            f"- [{f['tarea']}] {f['detalle']}" for f in base["fallas"])
    else:
        reporte += "Sin fallas: el objetivo es reducir el consumo de tokens sin romper nada."

    prompt = (
        "Estás mejorando TU PROPIO código fuente: el archivo verbo.py de este directorio "
        "es el agente que sos vos. Este es el reporte de tu última evaluación:\n\n"
        f"{reporte}\n\n"
        "Leé verbo.py y aplicá UNA mejora mínima y conservadora que ataque la causa "
        "de las fallas (o que reduzca consumo de tokens si no hay fallas). Típicamente: "
        "una regla nueva en el prompt de sistema, o un manejo de error más robusto.\n"
        "Reglas estrictas: usá la herramienta editar (no reescribas el archivo entero); "
        "NO toques ningún otro archivo; NO cambies la interfaz de línea de comandos; "
        "NO agregues dependencias. Al final explicá la mejora en una línea."
    )
    r = subprocess.run(
        [sys.executable, str(ARCHIVO_VERBO), "--auto", "-m", modelo_mutador, "-p", prompt],
        cwd=REPO, capture_output=True, text=True, timeout=600,
        encoding="utf-8", errors="replace")
    salida = (r.stdout or "").strip()
    print("  --- mutador ---")
    print("  " + "\n  ".join(salida.splitlines()[-8:]))
    lineas = [l for l in salida.splitlines() if l.strip() and not l.startswith(("[verbo-stats]", "  →", "VERBO ·"))]
    return lineas[-1][:100] if lineas else "mejora automática"


def compila():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(ARCHIVO_VERBO)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def es_mejor(cand, base):
    if cand["aciertos"] != base["aciertos"]:
        return cand["aciertos"] > base["aciertos"]
    return cand["tokens"] < base["tokens"] * 0.9


def revertir(nuevos_untracked):
    git("checkout", "--", ".")
    for f in nuevos_untracked:
        if not f.startswith("evals/resultados-"):
            (REPO / f).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteraciones", type=int, default=1)
    parser.add_argument("--modelo-agente", default=None,
                        help="Modelo que usa VERBO en los evals (default: el de verbo.py)")
    parser.add_argument("--modelo-mutador", default="groq/openai/gpt-oss-120b",
                        help="Modelo con el que VERBO se auto-edita")
    parser.add_argument("-r", "--repeticiones", type=int, default=1)
    parser.add_argument("--pausa", type=int, default=15)
    args = parser.parse_args()

    sucios = [l for l in git("status", "--porcelain").stdout.splitlines()
              if not l[3:].strip().startswith("evals/resultados-")]
    if sucios:
        raise SystemExit(f"el repo tiene cambios sin commitear: {sucios}")

    print(f"[evolucion] baseline con agente={args.modelo_agente or '(default)'}")
    base = correr_suite(args.modelo_agente, args.repeticiones, args.pausa)
    print(f"[evolucion] baseline: {base['aciertos']}/{base['total']} · {base['tokens']} tokens")

    for i in range(1, args.iteraciones + 1):
        print(f"\n[evolucion] iteración {i}: VERBO se auto-edita con {args.modelo_mutador}")
        untracked_antes = archivos_sin_trackear()
        razon = mutar_con_verbo(args.modelo_mutador, base)
        nuevos = archivos_sin_trackear() - untracked_antes

        cambiados = [f for f in git("diff", "--name-only").stdout.split() if f]
        if cambiados != ["verbo.py"] or any(not f.startswith("evals/resultados-") for f in nuevos):
            print(f"[evolucion] el mutador tocó archivos prohibidos (diff={cambiados}, "
                  f"nuevos={sorted(nuevos)}); revert total")
            revertir(nuevos)
            continue

        ok, err_compilacion = compila()
        if not ok:
            print(f"[evolucion] el candidato no compila; revert. {err_compilacion.strip()[:200]}")
            revertir(nuevos)
            continue

        print("[evolucion] evaluando candidato...")
        cand = correr_suite(args.modelo_agente, args.repeticiones, args.pausa)
        print(f"[evolucion] candidato: {cand['aciertos']}/{cand['total']} · {cand['tokens']} tokens "
              f"(baseline: {base['aciertos']}/{base['total']} · {base['tokens']})")

        if es_mejor(cand, base):
            git("add", "verbo.py")
            git("commit", "-m",
                f"auto-iteración: {razon}\n\n"
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
