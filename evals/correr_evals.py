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
import os
import re
import signal
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


def correr_con_timeout(cmd, timeout, cwd):
    """subprocess.run con timeout, pero matando el ÁRBOL entero. run() mata
    solo al hijo directo: si el agente dejó corriendo un script o un server,
    ese nieto sobrevive, sigue comiendo CPU en las tareas siguientes y, si
    tiene el pipe abierto, deja a communicate() esperando para siempre."""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace",
                         start_new_session=os.name == "posix")
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(p.pid, signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                           capture_output=True)
        p.communicate()
        raise


# Lo que imprime verbo.py cuando no le queda ningún modelo con cupo: una
# corrida así no dice nada del agente, solo del proveedor.
SENIALES_SIN_CUPO = ("agotaron su límite de tasa", "ningún modelo de la cadena está disponible")


def correr_tarea(tarea: Path, modelo: str, pausa: int, puro: bool = False, verbo: Path = VERBO):
    prompt = (tarea / "prompt.txt").read_text(encoding="utf-8").strip()
    sandbox = Path(tempfile.mkdtemp(prefix=f"verbo-eval-{tarea.name}-"))
    setup = tarea / "setup"
    if setup.is_dir():
        for archivo in setup.iterdir():
            shutil.copy(archivo, sandbox / archivo.name)

    cmd = [sys.executable, str(verbo), "--auto", "-p", prompt]
    if modelo:
        cmd += ["-m", modelo]
    if puro:
        cmd += ["--fallback", ""]

    inicio = time.time()
    try:
        codigo, out, err = correr_con_timeout(cmd, TIMEOUT_TAREA, sandbox)
        salida_agente = (out or "") + (err or "")
        agente_ok = codigo == 0
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
            codigo, out, err = correr_con_timeout(
                [sys.executable, str(tarea / "verificar.py")], 60, sandbox)
            paso = codigo == 0
            verificacion = (err or out or "").strip()
        except subprocess.TimeoutExpired:
            paso, verificacion = False, "[timeout de verificación]"
    else:
        paso = False
        verificacion = salida_agente.strip().splitlines()[-1] if salida_agente.strip() else "[el agente falló]"

    shutil.rmtree(sandbox, ignore_errors=True)
    if pausa:
        time.sleep(pausa)

    sin_cupo = not paso and any(s in salida_agente for s in SENIALES_SIN_CUPO)
    return {"tarea": tarea.name, "paso": paso, "segundos": round(duracion, 1),
            **stats, "sin_cupo": sin_cupo, "detalle": "" if paso else verificacion[-300:]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--modelo", action="append", default=[],
                        help="Modelo a evaluar (repetible para comparar varios)")
    parser.add_argument("--tarea", action="append", default=[],
                        help="Correr solo esta tarea (nombre de carpeta; repetible)")
    parser.add_argument("--pausa", type=int, default=15,
                        help="Segundos de espera entre tareas para respetar límites TPM (default 15)")
    parser.add_argument("-r", "--repeticiones", type=int, default=1,
                        help="Corridas por tarea: los agentes no son deterministas, 3 da un pass rate honesto")
    parser.add_argument("--puro", action="store_true",
                        help="Desactiva la cadena de fallbacks: mide cada modelo aislado "
                             "(sin esto, un 429 haría que otro modelo resuelva la tarea)")
    parser.add_argument("--contra", type=Path,
                        help="Otro verbo.py contra el que comparar: cada corrida de cada "
                             "tarea se mide con los dos seguidos, alternando quién va primero")
    parser.add_argument("--hasta", type=float,
                        help="Hora límite (epoch): no se arranca ninguna corrida que, en el "
                             "peor caso, termine después. Lo que no entró queda sin medir")
    args = parser.parse_args()

    modelos = args.modelo or [None]  # None = default de verbo.py
    tareas = sorted(t for t in TAREAS.iterdir() if t.is_dir())
    if args.tarea:
        faltan = set(args.tarea) - {t.name for t in tareas}
        if faltan:
            sys.exit(f"No existe la tarea: {', '.join(sorted(faltan))}")
        tareas = [t for t in tareas if t.name in args.tarea]

    if args.contra:
        guardar(comparar(tareas, modelos[0], args))
        return

    todos = {}
    for modelo in modelos:
        etiqueta = modelo or "(default)"
        print(f"\n=== Evaluando: {etiqueta} — {len(tareas)} tareas ===")
        resultados = []
        for tarea in tareas:
            if not entra(args, 1):
                print(f"  [sin tiempo] quedan sin medir desde {tarea.name}")
                break
            print(f"  {tarea.name} ... ", end="", flush=True)
            corridas = []
            for i in range(args.repeticiones):
                if not entra(args, 1):
                    break
                es_ultima = tarea == tareas[-1] and i == args.repeticiones - 1
                res = correr_tarea(tarea, modelo, 0 if es_ultima else args.pausa,
                                   puro=args.puro)
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
    guardar(todos)


def entra(args, corridas):
    """¿Entran `corridas` más antes de --hasta, contando cada una en su peor
    caso? Sin esto la suite intercalada (2 x 13 tareas x 3) no tenía techo y
    el workflow la cancelaba a las 3 horas sin dejar ni la bitácora."""
    if not args.hasta:
        return True
    return time.time() + corridas * (TIMEOUT_TAREA + 60 + args.pausa) <= args.hasta


def guardar(datos):
    archivo = AQUI / f"resultados-{datetime.now():%Y%m%d-%H%M%S}.json"
    archivo.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados guardados en {archivo.name}")


def comparar(tareas, modelo, args):
    """Mide verbo.py y --contra intercalados: cada corrida de cada tarea va con
    los dos seguidos, y el que arranca se alterna. Medidos en bloque, el
    segundo heredaba un cupo ya gastado: en el run 38994268353 el baseline se
    llevó el día y el candidato falló 13 tareas en menos de un segundo cada
    una. Así los dos pagan el mismo desgaste del cupo."""
    lados = {"verbo": VERBO, "contra": args.contra.resolve()}
    resultados = {lado: [] for lado in lados}
    incompleto = False
    print(f"\n=== Comparando verbo.py contra {args.contra.name} — {len(tareas)} tareas "
          f"x{args.repeticiones}, intercalado ===")
    for tarea in tareas:
        print(f"  {tarea.name} ... ", end="", flush=True)
        corridas = {lado: [] for lado in lados}
        for i in range(args.repeticiones):
            # Por par: un lado medido sin el otro no sirve para comparar.
            if not entra(args, 2):
                incompleto = True
                break
            orden = ["verbo", "contra"] if i % 2 == 0 else ["contra", "verbo"]
            for lado in orden:
                es_ultima = (tarea == tareas[-1] and i == args.repeticiones - 1
                             and lado == orden[-1])
                res = correr_tarea(tarea, modelo, 0 if es_ultima else args.pausa,
                                   puro=args.puro, verbo=lados[lado])
                corridas[lado].append(res)
            print("".join("-" if r["sin_cupo"] else ("P" if r["paso"] else "F")
                          for r in (corridas["verbo"][-1], corridas["contra"][-1])) + " ",
                  end="", flush=True)
        print()
        for lado in lados:
            for r in corridas[lado]:
                if not r["paso"] and r["detalle"]:
                    print(f"      [{lado}] motivo: {r['detalle'][-200:]}")
            resultados[lado].append({"tarea": tarea.name,
                                     "aciertos": sum(r["paso"] for r in corridas[lado]),
                                     "corridas": corridas[lado]})
        if incompleto:
            print(f"  [sin tiempo] se cortó en {tarea.name}; lo que sigue queda sin medir")
            break
    for lado in lados:
        ok = sum(t["aciertos"] for t in resultados[lado])
        total = sum(len(t["corridas"]) for t in resultados[lado])
        print(f"  {lado}: {ok}/{total} PASS")
    resultados["incompleto"] = incompleto
    return resultados


if __name__ == "__main__":
    main()
