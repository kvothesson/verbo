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
  2. VERBO se auto-edita guiado por el reporte de fallas Y por su bitácora
  3. guardrails: solo verbo.py puede cambiar + py_compile
  4. correr la suite de nuevo (candidato)
  5. si el fitness mejora -> git commit; si no -> git checkout (revert)
  6. pase lo que pase, el intento queda anotado en la bitácora (commiteada)

Fitness: aciertos con margen sobre la varianza, después frugalidad de tokens.

Memoria: evals/memoria-evolucion.md, commiteada al repo (sin base de datos).
El mutador la lee antes de editar, con el diff real de cada intento pasado y
su veredicto — sin eso arranca ciego cada día y recicla ideas ya descartadas.

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
LOG = AQUI / "evolucion.log"

# La bitácora ES la memoria del mutador, y se commitea al repo: sin base de
# datos, versionada y legible en GitHub. Sin esto cada corrida arranca ciega
# y recicla ideas ya descartadas — así la evolución tocó tres veces la misma
# línea (agregar excepthook, comentarlo, descomentarlo) en 17 días.
MEMORIA = AQUI / "memoria-evolucion.md"
MEMORIA_ENTRADAS = 12      # cuántos intentos pasados ve el mutador
MEMORIA_CHARS = 5000       # tope de contexto que se le dedica a la memoria


class Tee:
    """Duplica stdout al log para que el progreso sea visible desde afuera."""

    def __init__(self, pantalla, archivo):
        self.pantalla, self.archivo = pantalla, archivo

    def write(self, s):
        self.pantalla.write(s)
        self.archivo.write(s)
        self.archivo.flush()

    def flush(self):
        self.pantalla.flush()
        self.archivo.flush()


sys.stdout = Tee(sys.stdout, open(LOG, "a", encoding="utf-8", errors="replace"))


def git(*args, check=True):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, check=check,
                          encoding="utf-8", errors="replace")


def git_commit(mensaje):
    """Commit con identidad explícita: todo lo que publica el proyecto firma
    como Kvothesson, corra en la nube o en una máquina cualquiera."""
    return git("-c", "user.name=Kvothesson",
               "-c", "user.email=kvothesson@users.noreply.github.com",
               "commit", "-m", mensaje, check=False)


def archivos_sin_trackear():
    return {l[3:].strip() for l in git("status", "--porcelain").stdout.splitlines()
            if l.startswith("??")}


def leer_memoria():
    """Últimos intentos, del más reciente al más viejo, acotados en contexto."""
    if not MEMORIA.is_file():
        return ""
    entradas = [e for e in MEMORIA.read_text(encoding="utf-8").split("\n## ") if e.strip()]
    recientes = [e if e.startswith("## ") else "## " + e
                 for e in entradas[-MEMORIA_ENTRADAS:]][::-1]
    texto = ""
    for e in recientes:
        if len(texto) + len(e) > MEMORIA_CHARS:
            break
        texto += e.rstrip() + "\n\n"
    return texto.strip()


def registrar(veredicto, razon, diff, base=None, cand=None):
    """Anota el intento en la bitácora y la commitea. Se llama SIEMPRE, incluso
    cuando no hubo mutación o se revirtió: el valor está justamente en recordar
    lo que no funcionó, para no reintentarlo mañana."""
    from datetime import datetime
    if not MEMORIA.is_file():
        MEMORIA.write_text(
            "# Bitácora de evolución\n\n"
            "Memoria del mutador: cada intento de auto-mejora con su resultado.\n"
            "La lee antes de mutar para no repetir ideas ya descartadas.\n",
            encoding="utf-8")
    entrada = [f"\n## {datetime.now():%Y-%m-%d} · {veredicto}",
               f"- **Intento:** {razon}"]
    if base and cand:
        entrada.append(f"- **Medición:** aciertos {base['aciertos']}/{base['total']} → "
                       f"{cand['aciertos']}/{cand['total']} · tokens {base['tokens']} → "
                       f"{cand['tokens']}")
    if diff:
        entrada.append("- **Diff:**\n```diff\n" + diff.strip()[:900] + "\n```")
    with MEMORIA.open("a", encoding="utf-8") as f:
        f.write("\n".join(entrada) + "\n")
    git("add", str(MEMORIA.relative_to(REPO)).replace("\\", "/"))
    git_commit(f"bitácora: {veredicto} — {razon[:60]}")


def correr_suite(modelo_agente, reps, pausa):
    cmd = [sys.executable, str(AQUI / "correr_evals.py"), "-r", str(reps), "--pausa", str(pausa)]
    if modelo_agente:
        cmd += ["-m", modelo_agente]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", bufsize=1) as p:
        for linea in p.stdout:
            print("  " + linea.rstrip())
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

    memoria = leer_memoria()
    bloque_memoria = (
        "INTENTOS ANTERIORES (tu memoria; lo REVERTIDO ya se probó y no funcionó, "
        "no lo repitas ni lo deshagas):\n\n" + memoria + "\n\n"
    ) if memoria else ""

    prompt = (
        "Estás mejorando TU PROPIO código fuente: el archivo verbo.py de este directorio "
        "es el agente que sos vos. Este es el reporte de tu última evaluación:\n\n"
        f"{reporte}\n\n"
        f"{bloque_memoria}"
        "Leé verbo.py y aplicá UNA mejora que ataque la causa de las fallas (o que "
        "reduzca el consumo de tokens si no hay fallas). Para aceptarse tiene que "
        "hacer pasar al menos 2 tareas más de forma sostenida, o ahorrar más del 10% "
        "de tokens: un retoque cosmético no alcanza. Podés cambiar el prompt de "
        "sistema, el loop agéntico, la validación de las herramientas o agregar un "
        "paso de verificación — siempre que sea coherente y esté acotado a un cambio.\n"
        "PROHIBIDO hacer trampa contra tu propia evaluación: no metas en el prompt "
        "de sistema ni en el código respuestas específicas de las tareas que fallaron "
        "(del tipo 'devolvé tuplas' o 'filtrá los negativos'). Eso sube el puntaje "
        "sin mejorar al agente, y lo empeora para cualquier otro trabajo. La mejora "
        "tiene que ser general: valer para tareas que nunca viste.\n"
        "Trabajá SOBRE verbo.py: no explores ni leas las tareas de evals/, no podés "
        "modificarlas y ahí no está la mejora. Tenés pocos turnos: leé verbo.py, "
        "decidí el cambio y aplicalo.\n"
        "Reglas estrictas: usá la herramienta editar (no reescribas el archivo entero); "
        "NO toques ningún otro archivo; NO cambies la interfaz de línea de comandos; "
        "NO agregues dependencias. La herramienta editar valida la sintaxis de Python "
        "automáticamente: si te devuelve error, tu edición no se aplicó — corregila y "
        "reintentá hasta que aplique. Al final explicá la mejora en una línea."
    )
    r = subprocess.run(
        [sys.executable, str(ARCHIVO_VERBO), "--auto", "-m", modelo_mutador, "-p", prompt],
        cwd=REPO, capture_output=True, text=True, timeout=600,
        encoding="utf-8", errors="replace")
    salida = (r.stdout or "").strip()
    print("  --- mutador (salida completa) ---")
    print("  " + "\n  ".join(salida.splitlines()))
    print("  --- fin mutador ---")
    # Se filtra por el texto YA sin sangría: VERBO imprime las herramientas
    # como "  → nombre", sus resultados como "    ← resumen" y los detalles de
    # edición como "    - buscar:". Filtrar por el string crudo dejaba pasar
    # esas líneas y la "razón" del commit terminaba siendo un output de tool.
    ruido = ("→", "←", "- buscar:", "- reemplazar:", "[verbo-stats]",
             "[límite", "[tool call", "[VERBO", "VERBO ·")
    lineas = [l.strip() for l in salida.splitlines()
              if l.strip() and not l.strip().startswith(ruido)]
    return lineas[-1][:100] if lineas else "mejora automática"


def compila():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(ARCHIVO_VERBO)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr


# La suite no es determinista: con las tareas de BigCodeBench, una misma
# versión de verbo.py osciló entre 7/13 y 9/13 en días distintos. Aceptar
# cualquier +1 de aciertos con una sola corrida es aceptar RUIDO — así la
# evolución hizo tres commits en 17 días tocando la misma línea de ida y
# vuelta, con saldo neto cero. El margen exige que la mejora supere la
# varianza observada; correr con -r 3 la reduce y hace el margen alcanzable.
# Se escala con las repeticiones: con -r 3 los aciertos se cuentan sobre 39
# corridas en vez de 13, así que un "+2" absoluto sería una vara MÁS BLANDA.
# El margen se expresa en tareas-equivalente para que exigir lo mismo cueste
# lo mismo con cualquier -r.
MARGEN_POR_TAREA = 2  # tareas de ventaja mínima para creerle a una mejora


def es_mejor(cand, base, reps=1):
    delta = cand["aciertos"] - base["aciertos"]
    # Con una sola corrida no hay forma de separar señal de ruido: el swing
    # observado con código idéntico fue de 2 tareas, el margen entero. Por eso
    # una mejora de aciertos solo se cree con al menos 2 repeticiones.
    if reps >= 2 and delta >= MARGEN_POR_TAREA * reps:
        return True
    if delta < 0:
        return False
    # Empate (o mejora dentro del ruido): solo se acepta si además no perdió
    # aciertos y ahorra tokens de forma contundente.
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
              if not l[3:].strip().startswith(("evals/resultados-", "evals/evolucion.log"))]
    if sucios:
        raise SystemExit(f"el repo tiene cambios sin commitear: {sucios}")

    from datetime import datetime
    print(f"\n===== evolución {datetime.now():%Y-%m-%d %H:%M:%S} · "
          f"agente={args.modelo_agente or '(default)'} · mutador={args.modelo_mutador} =====")
    print(f"[evolucion] baseline con agente={args.modelo_agente or '(default)'}")
    base = correr_suite(args.modelo_agente, args.repeticiones, args.pausa)
    print(f"[evolucion] baseline: {base['aciertos']}/{base['total']} · {base['tokens']} tokens")

    for i in range(1, args.iteraciones + 1):
        print(f"\n[evolucion] iteración {i}: VERBO se auto-edita con {args.modelo_mutador}")
        untracked_antes = archivos_sin_trackear()
        razon = mutar_con_verbo(args.modelo_mutador, base)
        nuevos = archivos_sin_trackear() - untracked_antes

        cambiados = [f for f in git("diff", "--name-only").stdout.split() if f]
        intrusos = sorted(f for f in nuevos if not f.startswith("evals/resultados-"))
        # Se captura ANTES de revertir: es lo que hace que la memoria sirva
        # (saber qué línea se tocó, no solo la explicación del modelo).
        diff = git("diff", "--", "verbo.py").stdout
        if not cambiados and not intrusos:
            # Distinto de "tocó lo prohibido": el mutador simplemente no logró
            # editar nada (se quedó sin cupo, no encontró el texto exacto, o
            # agotó sus turnos). Sin esta rama el caso se reportaba como una
            # violación de guardrail y ocultaba que la mutación nunca ocurrió.
            print("[evolucion] el mutador no produjo ninguna edición; "
                  "no hay candidato que evaluar")
            revertir(nuevos)
            registrar("SIN MUTACIÓN", razon, "")
            continue
        if cambiados != ["verbo.py"] or intrusos:
            print(f"[evolucion] el mutador tocó archivos prohibidos (diff={cambiados}, "
                  f"nuevos={intrusos}); revert total")
            revertir(nuevos)
            registrar("REVERTIDA (tocó archivos prohibidos)",
                      f"{razon} [tocó: {cambiados + intrusos}]", diff)
            continue

        ok, err_compilacion = compila()
        if not ok:
            print(f"[evolucion] el candidato no compila; revert. {err_compilacion.strip()[:200]}")
            revertir(nuevos)
            registrar("REVERTIDA (no compila)",
                      f"{razon} [{err_compilacion.strip()[:120]}]", diff)
            continue

        print("[evolucion] evaluando candidato...")
        cand = correr_suite(args.modelo_agente, args.repeticiones, args.pausa)
        print(f"[evolucion] candidato: {cand['aciertos']}/{cand['total']} · {cand['tokens']} tokens "
              f"(baseline: {base['aciertos']}/{base['total']} · {base['tokens']})")

        if es_mejor(cand, base, args.repeticiones):
            git("add", "verbo.py")
            git_commit(
                f"auto-iteración: {razon}\n\n"
                f"Fitness: {base['aciertos']}/{base['total']} ({base['tokens']} tok) -> "
                f"{cand['aciertos']}/{cand['total']} ({cand['tokens']} tok)\n\n"
                "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>")
            print("[evolucion] MEJORA ACEPTADA — commit hecho")
            registrar("ACEPTADA", razon, diff, base, cand)
            base = cand
        else:
            git("checkout", "--", "verbo.py")
            print("[evolucion] sin mejora — revert")
            registrar("REVERTIDA (no superó el fitness)", razon, diff, base, cand)

    print(f"\n[evolucion] FIN · fitness final: {base['aciertos']}/{base['total']} · {base['tokens']} tokens")


if __name__ == "__main__":
    main()
