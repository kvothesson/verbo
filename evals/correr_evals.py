#!/usr/bin/env python3
"""
Runner de evals para VERBO.

Cada tarea en tareas/ tiene:
    prompt.txt      — el pedido que recibe el agente
    setup/          — (opcional) archivos de partida copiados al sandbox
    verificar.py    — script que decide PASS/FAIL; el agente nunca lo ve

Uso:
    python correr_evals.py                                  # modelo default de VERBO
    python correr_evals.py -m groq/llama-3.3-70b-versatile
    python correr_evals.py -m groq/openai/gpt-oss-120b -m gemini/gemini-2.5-flash
    python correr_evals.py --tarea 02-bug-promedio          # una sola tarea
    python correr_evals.py --pausa 30                       # más espera entre tareas (TPM)
"""
import argparse
import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).parent
VERBO = AQUI.parent / "verbo.py"
TAREAS = AQUI / "tareas"
TIMEOUT_TAREA = 300


def correr_tarea(tarea: Path, modelo: str, pausa: int):
    prompt = (tarea / "prompt.txt").read_text(encoding="utf-8").strip()
    sandbox = Path(tempfile.mkdtemp(prefix=f"verbo-eval-{tarea.name}-"))
    setup = tarea / "setup"
    if setup.is_dir():
        for archivo in setup.iterdir():
            shutil.copy(archivo, sandbox / archivo.name)

    cmd = [sys.executable, str(VERBO), "--auto", "-p", prompt]
    if modelo:
        cmd += ["-m", modelo]

    inicio = time.time()
    try:
        r = subprocess.run(cmd, cwd=sandbox, capture_output=True, text=True,
                           timeout=TIMEOUT_TAREA, encoding="utf-8", errors="replace")
        salida_agente = (r.stdout or "") + (r.stderr or "")
        agente_ok = r.returncode == 0
    except subprocess.TimeoutExpired:
        salida_agente = "[timeout del agente]"
        agente_ok = False
    duracion = time.time() - inicio

    stats = {"llamadas": 0, "tokens": 0}
    m = re.search(r"\[verbo-stats\] llamadas=(\d+) tokens=(\d+)", salida_agente)
    if m:
        stats = {"llamadas": int(m.group(1)), "tokens": int(m.group(2))}

    verificacion = ""
    if agente_ok:
        try:
            v = subprocess.run([sys.executable, str(tarea / "verificar.py")],
                               cwd=sandbox, capture_output=True, text=True,
                               timeout=60, encoding="utf-8", errors="replace")
            paso = v.returncode == 0
            verificacion = (v.stderr or v.stdout or "").strip()
        except subprocess.TimeoutExpired:
            paso, verificacion = False, "[timeout de verificación]"
    else:
        paso = False
        verificacion = salida_agente.strip().splitlines()[-1] if salida_agente.strip() else "[el agente falló]"

    shutil.rmtree(sandbox, ignore_errors=True)
    if pausa:
        time.sleep(pausa)

    return {"tarea": tarea.name, "paso": paso, "segundos": round(duracion, 1),
            **stats, "detalle": "" if paso else verificacion[-300:]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--modelo", action="append", default=[],
                        help="Modelo a evaluar (repetible para comparar varios)")
    parser.add_argument("--tarea", help="Correr solo esta tarea (nombre de carpeta)")
    parser.add_argument("--pausa", type=int, default=15,
                        help="Segundos de espera entre tareas para respetar límites TPM (default 15)")
    parser.add_argument("-r", "--repeticiones", type=int, default=1,
                        help="Corridas por tarea: los agentes no son deterministas, 3 da un pass rate honesto")
    args = parser.parse_args()

    modelos = args.modelo or [None]  # None = default de verbo.py
    tareas = sorted(t for t in TAREAS.iterdir() if t.is_dir())
    if args.tarea:
        tareas = [t for t in tareas if t.name == args.tarea]
        if not tareas:
            sys.exit(f"No existe la tarea '{args.tarea}'")

    todos = {}
    for modelo in modelos:
        etiqueta = modelo or "(default)"
        print(f"\n=== Evaluando: {etiqueta} — {len(tareas)} tareas ===")
        resultados = []
        for tarea in tareas:
            print(f"  {tarea.name} ... ", end="", flush=True)
            corridas = []
            for i in range(args.repeticiones):
                es_ultima = tarea == tareas[-1] and i == args.repeticiones - 1
                res = correr_tarea(tarea, modelo, 0 if es_ultima else args.pausa)
                corridas.append(res)
                print("P" if res["paso"] else "F", end="", flush=True)
            aciertos_tarea = sum(r["paso"] for r in corridas)
            seg = sum(r["segundos"] for r in corridas) / len(corridas)
            tok = sum(r["tokens"] for r in corridas) // len(corridas)
            print(f"  {aciertos_tarea}/{len(corridas)} PASS  (prom: {seg:.1f}s · {tok} tokens)")
            for r in corridas:
                if not r["paso"] and r["detalle"]:
                    print(f"      motivo: {r['detalle']}")
            resultados.append({"tarea": tarea.name, "aciertos": aciertos_tarea,
                               "corridas": corridas})
        total_ok = sum(r["aciertos"] for r in resultados)
        total = sum(len(r["corridas"]) for r in resultados)
        tokens = sum(c["tokens"] for r in resultados for c in r["corridas"])
        print(f"  TOTAL: {total_ok}/{total} PASS ({100 * total_ok / total:.0f}%) · {tokens} tokens")
        todos[etiqueta] = resultados

    archivo = AQUI / f"resultados-{datetime.now():%Y%m%d-%H%M%S}.json"
    archivo.write_text(json.dumps(todos, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados guardados en {archivo.name}")


if __name__ == "__main__":
    main()
