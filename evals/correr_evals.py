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
MARGEN_TIEMPO = 30   # segundos antes del kill en que verbo.py corta solo


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
        # Lo que alcanzó a escribir antes de morir: es justo lo que explica
        # por qué no terminó. Antes quedaba solo "[timeout del agente]".
        out, err = p.communicate()
        return None, out, err


def tapar_secretos(texto):
    """Reemplaza por *** el valor de cualquier key del entorno. Los detalles
    de las fallas terminan en fitness-actual.json y en la bitácora, que se
    commitean a un repo público: un agente (o un candidato) que imprima una
    key no puede dejarla publicada."""
    for nombre, valor in os.environ.items():
        if len(valor) >= 8 and re.search(r"(KEY|TOKEN|SECRET)", nombre, re.I):
            texto = texto.replace(valor, "***")
    return texto


# Líneas de la salida de verbo.py que cuentan qué hizo: herramientas, sus
# resultados, esperas por cupo y cortes. Es lo que el mutador necesita para
# entender una falla, y entra en pocos cientos de caracteres.
PREFIJOS_TRAZA = ("→", "←", "[límite", "[toda la cadena", "[VERBO", "[tool call",
                  "[contexto", "ERROR")
LINEAS_TRAZA = 14


def traza_de(salida):
    lineas = [l.strip()[:160] for l in salida.splitlines()
              if l.strip().startswith(PREFIJOS_TRAZA)]
    return "\n".join(lineas[-LINEAS_TRAZA:])


# Lo que imprime verbo.py cuando no le queda ningún modelo con cupo: una
# corrida así no dice nada del agente, solo del proveedor.
SENIALES_SIN_CUPO = ("agotaron su límite de tasa", "ningún modelo de la cadena está disponible")


def correr_tarea(tarea: Path, modelo: str, pausa: int, puro: bool = False, verbo: Path = None):
    verbo = verbo or VERBO
    prompt = (tarea / "prompt.txt").read_text(encoding="utf-8").strip()
    sandbox = Path(tempfile.mkdtemp(prefix=f"verbo-eval-{tarea.name}-"))
    setup = tarea / "setup"
    if setup.is_dir():
        for archivo in setup.iterdir():
            shutil.copy(archivo, sandbox / archivo.name)

    # --tiempo un poco antes del timeout duro: verbo.py corta solo, deja su
    # salida y sus tokens. El kill queda de red por si el candidato no cumple.
    cmd = [sys.executable, "-u", str(verbo), "--auto", "-p", prompt,
           "--tiempo", str(TIMEOUT_TAREA - MARGEN_TIEMPO)]
    if modelo:
        cmd += ["-m", modelo]
    if puro:
        cmd += ["--fallback", ""]

    inicio = time.time()
    codigo, out, err = correr_con_timeout(cmd, TIMEOUT_TAREA, sandbox)
    salida_agente = tapar_secretos((out or "") + (err or ""))
    matado = codigo is None
    if matado:
        salida_agente += "\n[timeout del agente]"
    # 3 = se quedó sin --tiempo pero terminó prolijo: lo que haya dejado
    # escrito se verifica igual, como haría un usuario.
    agente_ok = codigo in (0, 3)
    duracion = time.time() - inicio

    stats = {"llamadas": 0, "tokens": 0}
    m = re.search(r"\[verbo-stats\] llamadas=(\d+) tokens=(\d+)", salida_agente)
    if m:
        stats = {"llamadas": int(m.group(1)), "tokens": int(m.group(2))}

    verificacion = ""
    if agente_ok:
        codigo, out, err = correr_con_timeout(
            [sys.executable, str(tarea / "verificar.py")], 60, sandbox)
        paso = codigo == 0
        verificacion = "[timeout de verificación]" if codigo is None else (err or out or "").strip()
    else:
        paso = False
        verificacion = salida_agente.strip().splitlines()[-1] if salida_agente.strip() else "[el agente falló]"

    shutil.rmtree(sandbox, ignore_errors=True)
    if pausa:
        time.sleep(pausa)

    sin_cupo = not paso and any(s in salida_agente for s in SENIALES_SIN_CUPO)
    return {"tarea": tarea.name, "paso": paso, "segundos": round(duracion, 1),
            **stats, "sin_cupo": sin_cupo,
            # Sin stats confiables: un candidato que se cuelga más no puede
            # "ahorrar tokens" gracias a los 0 de las corridas matadas.
            "matado": matado, "sin_tiempo": codigo == 3,
            "detalle": "" if paso else tapar_secretos(verificacion)[-300:],
            "traza": "" if paso else traza_de(salida_agente)}


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
    parser.add_argument("--costo", type=float,
                        help="Segundos estimados por corrida, para decidir si entra otra ronda "
                             f"antes de --hasta (default {COSTO_DEFAULT})")
    parser.add_argument("--verbo", type=Path,
                        help="verbo.py a evaluar (default: el del repo). La evolución pasa "
                             "una copia fuera del repo, donde el candidato no ve los tests")
    args = parser.parse_args()
    global VERBO
    if args.verbo:
        VERBO = args.verbo.resolve()

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


COSTO_DEFAULT = 180   # segundos estimados por corrida si no se pasa --costo


def entra(args, corridas, peor_caso=True):
    """¿Entran `corridas` más antes de --hasta? Sin esto la suite intercalada
    (2 x 13 tareas x 3) no tenía techo y el workflow la cancelaba a las 3
    horas sin dejar ni la bitácora. Por corrida suelta se cuenta el peor caso;
    para decidir si arrancar una ronda entera, el costo medido (--costo):
    con el peor caso no entraría nunca ninguna."""
    if not args.hasta:
        return True
    costo = (TIMEOUT_TAREA + 60) if peor_caso else (getattr(args, "costo", None) or COSTO_DEFAULT)
    return time.time() + corridas * (costo + args.pausa) <= args.hasta


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
    corridas = {lado: {t.name: [] for t in tareas} for lado in lados}
    rondas = 0
    print(f"\n=== Comparando {VERBO.name} contra {args.contra.name} — {len(tareas)} tareas "
          f"x{args.repeticiones}, intercalado por rondas ===")
    # Por RONDAS (todas las tareas una vez, después todas otra vez) y no tarea
    # por tarea: si el tiempo corta, lo medido son rondas completas sobre
    # TODA la suite, que sí es una muestra. Cortar a mitad de la lista
    # alfabética dejaba medidas solo las primeras tareas y no se podía decidir.
    for i in range(args.repeticiones):
        if not entra(args, 2 * len(tareas), peor_caso=False):
            print(f"  [sin tiempo] no entra la ronda {i + 1}; quedan {rondas} completas")
            break
        orden = ["verbo", "contra"] if i % 2 == 0 else ["contra", "verbo"]
        print(f"  ronda {i + 1} (arranca {orden[0]})")
        cortada = False
        for tarea in tareas:
            # Red por par con el peor caso: si la estimación falló, la ronda
            # se abandona entera (una ronda a medias no es muestra).
            if not entra(args, 2):
                cortada = True
                break
            print(f"    {tarea.name} ... ", end="", flush=True)
            for lado in orden:
                es_ultima = (tarea == tareas[-1] and i == args.repeticiones - 1
                             and lado == orden[-1])
                res = correr_tarea(tarea, modelo, 0 if es_ultima else args.pausa,
                                   puro=args.puro, verbo=lados[lado])
                corridas[lado][tarea.name].append(res)
            print("".join("-" if r["sin_cupo"] else ("P" if r["paso"] else "F")
                          for r in (corridas["verbo"][tarea.name][-1],
                                    corridas["contra"][tarea.name][-1])))
            for lado in lados:
                r = corridas[lado][tarea.name][-1]
                if not r["paso"] and r["detalle"]:
                    print(f"      [{lado}] motivo: {r['detalle'][-200:]}")
        if cortada:
            for lado in lados:
                for t in tareas:
                    del corridas[lado][t.name][rondas:]
            print(f"  [sin tiempo] la ronda {i + 1} no terminó y se descarta; quedan {rondas} completas")
            break
        rondas += 1
    resultados = {lado: [{"tarea": t.name,
                          "aciertos": sum(r["paso"] for r in corridas[lado][t.name]),
                          "corridas": corridas[lado][t.name]} for t in tareas]
                  for lado in lados}
    for lado in lados:
        ok = sum(t["aciertos"] for t in resultados[lado])
        total = sum(len(t["corridas"]) for t in resultados[lado])
        print(f"  {lado}: {ok}/{total} PASS")
    resultados["rondas"] = rondas
    resultados["incompleto"] = rondas < args.repeticiones
    return resultados


if __name__ == "__main__":
    main()
