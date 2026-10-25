#!/usr/bin/env python3
"""
Auto-iteración de VERBO: el agente mejora su propio código, con la suite
de evals como juez y git como red de seguridad.

El mutador ES el propio VERBO: se lanza una instancia del agente en un taller
fuera del repo, con una copia de verbo.py, su genoma, un mapa del código y
las trazas de sus fallas. Desde el 2026-10-24 puede editar TODO verbo.py, no
solo el genoma: en dos meses de genoma solo, movió los mismos dos números.
Lee por rangos (leer desde/hasta): el archivo entero no entra en los 8k
tokens por minuto de Groq gratis.

Loop por corrida (varios candidatos, mientras alcance el presupuesto):
  0. chequeo de proveedores: una llamada mínima a cada modelo; los que
     rechazan quedan afuera y, si no queda ninguno, la corrida sale en rojo
  1. VERBO se edita guiado por el fitness, las trazas del último filtro, su
     bitácora y la lista de zonas que ya probó sin éxito
  2. si no editó nada, se corta acá: sin candidato no se gasta un token
  3. guardrails baratos: py_compile, genoma válido y con límites, contrato
     de la CLI, tamaño del prompt, nada de red/entorno/tests; y si el cambio
     repite un intento o solo mueve perillas agotadas, no se mide
  4. filtro barato: baseline y candidato (copias fuera del repo, donde no
     ven los tests) intercalados sobre las tareas difíciles más el canario;
     tiene que ganarle al baseline medido hoy, o ahorrar tokens sin perder
  5. suite completa por RONDAS intercaladas, tantas como entren en el
     tiempo; los pares en que cualquiera se quedó sin cupo se descartan juntos
  6. se acepta con un test de signos sobre los pares (p ≤ 0.05), o por ahorro
     de tokens sin perder aciertos ni colgarse más -> commit
  7. pase lo que pase, el intento queda anotado en la bitácora (commiteada)

Se muta ANTES de medir a propósito: la suite y el mutador comen del mismo
cupo gratis, y medir primero dejaba al mutador sin nada con qué trabajar.

Memoria: evals/memoria-evolucion.md, commiteada al repo (sin base de datos).
El mutador la lee antes de editar, con el diff real de cada intento pasado,
su veredicto y las zonas que tocó.

Lo que NO puede tocar nunca: el evaluador (correr_evals.py, las tareas y sus
verificar.py), este archivo y el workflow. Si pudiera, subiría el puntaje
sin mejorar el agente. Y corre con keys reales en un repo público: todo lo
que se commitea pasa por tapar_secretos().

Uso:
    python evolucionar.py --iteraciones 4 -r 3 --minutos 150
    python evolucionar.py --modelo-agente groq/llama-3.3-70b-versatile \
                          --modelo-mutador groq/openai/gpt-oss-120b -r 2
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))
from correr_evals import tapar_secretos  # noqa: E402

REPO = AQUI.parent
ARCHIVO_VERBO = REPO / "verbo.py"
LOG = AQUI / "evolucion.log"

# La bitácora ES la memoria del mutador, y se commitea al repo: sin base de
# datos, versionada y legible en GitHub. Sin esto cada corrida arranca ciega
# y recicla ideas ya descartadas — así la evolución tocó tres veces la misma
# línea (agregar excepthook, comentarlo, descomentarlo) en 17 días.
MEMORIA = AQUI / "memoria-evolucion.md"
MEMORIA_ENTRADAS = 12      # cuántos intentos pasados ve el mutador
MEMORIA_CHARS = 2500       # tope de contexto: todo el pedido tiene que entrar en 8k tokens

# Último fitness medido, commiteado al repo porque el runner de Actions es
# efímero: sin esto, cada día arranca sin saber cómo le fue al código actual
# y hay que volver a medirlo antes de poder mutar.
FITNESS = AQUI / "fitness-actual.json"

# El mutador y la suite competían por el MISMO cupo gratis. La suite corría
# primero, se comía ~295k tokens del día, y el mutador arrancaba con groq y
# cerebras ya enfriados: 1286s de espera contra los 120s de MAX_ESPERA_GLOBAL,
# así que abandonaba sin editar una línea. Cinco "SIN MUTACIÓN" seguidos no
# fueron falta de ideas, fue falta de cupo. Ahora cada uno tiene su proveedor.
CADENA_EVALS = ("groq/qwen/qwen3.8-27b,groq/openai/gpt-oss-20b,"
                "openrouter/nvidia/nemotron-3-super-120b-a12b:free,"
                "openrouter/poolside/laguna-s-2.1:free,"
                "openrouter/google/gemma-4-31b-it:free")
# Cerebras era el primario hasta que su tier gratis empezó a devolver 402
# (2026-08-18). Ojo: groq/openai/gpt-oss-120b también es el modelo principal
# de la suite (el default de verbo.py), así que vuelven a compartir cupo. Lo
# que lo hace tolerable es el orden: se muta primero, el filtro gasta poco, y
# la suite completa solo corre si el candidato lo pasó; si el principal se
# agota, la suite sigue con CADENA_EVALS.
MODELO_MUTADOR_DEFAULT = "groq/openai/gpt-oss-120b"
# gpt-oss-20b tiene cupo propio en Groq (los límites son por modelo).
# laguna de OpenRouter al final: ahora el mutador lee código y su historial
# crece; cuando Groq lo rechaza por tamaño (413, el pedido supera los 8k
# tokens por minuto) hace falta alguien con más margen donde caer.
CADENA_MUTADOR = ("groq/openai/gpt-oss-20b,groq/qwen/qwen3.8-27b,"
                  "openrouter/poolside/laguna-s-2.1:free,cerebras/gpt-oss-120b")
MODELO_SUITE = "groq/openai/gpt-oss-120b"  # el default de verbo.py

# El genoma es lo único que el mutador puede tocar (ver el bloque en verbo.py).
# Los límites existen para que una mutación no pueda "ganar" rompiendo la
# promesa del proyecto: un prompt chico que entra en los tiers gratis.
MARCA_INICIO = "# >>> GENOMA\n"
MARCA_FIN = "# <<< GENOMA\n"
LIMITES_GENOMA = {
    "max_turnos": (5, 60),
    "max_salida_herramienta": (1000, 20000),
    "max_contexto_chars": (20000, 200000),
    "temperatura": (0.0, 1.0),
}
MAX_CHARS_TEXTO_GENOMA = 6000   # reglas + descripciones + cierre (~1.5k tokens)

# Filtro barato: antes de pagar baseline + candidato completos (2 x 13 tareas
# x -r), el candidato corre una vez sobre las tareas que el baseline fallaba
# más el canario. Cuesta ~1/10 de una suite y descarta lo que no mueve nada.
CANARIO = "01-crear-script"

# 600s eran la herencia de cuando el mutador arrancaba sin cupo y moría rápido:
# servían de corte de pérdidas. Con proveedor propio el mutador SÍ trabaja, y
# 10 minutos no le alcanzan para leer verbo.py entero, decidir y editar (run 38,
# 2026-08-16: se comió los 600s sin llegar a nada). Pero con varios candidatos
# por corrida, 40 min de un solo mutador son un día perdido; ahora lee por
# rangos con el mapa del código en vez del archivo entero.
TIMEOUT_MUTADOR = 1200     # segundos; agotarlo es un veredicto, no un crash

# Presupuesto de la corrida entera. El workflow corta a los 180 min, y cuando
# cortaba él (18, 20, 22 y 24 de octubre de 2026) se perdía todo: ni bitácora
# ni push, solo "The operation was canceled". Cortando acá antes, el día queda
# anotado como SIN TIEMPO y el push alcanza a correr.
MINUTOS_DEFAULT = 150
HASTA = None               # epoch límite; lo fija main()


class Tee:
    """Duplica stdout al log para que el progreso sea visible desde afuera."""

    def __init__(self, pantalla, archivo):
        self.pantalla, self.archivo = pantalla, archivo

    def write(self, s):
        # Flush también a pantalla: en Actions stdout es un pipe, va bufferado
        # en bloques de 8 KB, y al cancelar el job se perdía todo lo que no
        # había llenado un bloque. Por eso los runs cancelados de octubre de
        # 2026 parecían colgados justo después del chequeo de proveedores.
        self.pantalla.write(s)
        self.pantalla.flush()
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
    # Los días en que no pasó nada no le enseñan nada al mutador, y con 60
    # "SIN MUTACIÓN" seguidos tapaban todo lo que sí servía. Quedan los
    # intentos con diff o medición y las notas del mantenimiento.
    entradas = [e for e in entradas if "**Diff:**" in e or "**Medición:**" in e
                or "NOTA DEL MANTENIMIENTO" in e or "Por qué NO sirve" in e]
    recientes = [e if e.startswith("## ") else "## " + e
                 for e in entradas[-MEMORIA_ENTRADAS:]][::-1]
    texto = ""
    for e in recientes:
        if len(texto) + len(e) > MEMORIA_CHARS:
            break
        texto += e.rstrip() + "\n\n"
    return texto.strip()


def leer_fitness():
    """Fitness de la última medición, o None si nunca se midió."""
    if not FITNESS.is_file():
        return None
    try:
        return json.loads(FITNESS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def guardar_fitness(datos):
    """Guarda la medición para que mañana el mutador tenga el reporte de fallas
    sin pagar la suite de nuevo. Lo commitea registrar(), junto con la bitácora."""
    from datetime import datetime
    FITNESS.write_text(
        json.dumps({**datos, "medido": f"{datetime.now():%Y-%m-%d}"},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")


def registrar(veredicto, razon, diff, base=None, cand=None, zonas=None):
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
    razon, diff = tapar_secretos(razon), tapar_secretos(diff or "")
    entrada = [f"\n## {datetime.now():%Y-%m-%d} · {veredicto}",
               f"- **Intento:** {razon}"]
    if zonas:
        # Qué partes de verbo.py tocó: con esto se detectan las zonas
        # quemadas sin depender de que el diff (truncado) lo diga.
        entrada.append(f"- **Zonas:** {', '.join(zonas)}")
    if base and cand:
        entrada.append(f"- **Medición:** aciertos {base['aciertos']}/{base['total']} → "
                       f"{cand['aciertos']}/{cand['total']} · tokens {base['tokens']} → "
                       f"{cand['tokens']}")
    if diff:
        entrada.append("- **Diff:**\n```diff\n" + diff.strip()[:900] + "\n```")
    with MEMORIA.open("a", encoding="utf-8") as f:
        f.write("\n".join(entrada) + "\n")
    for archivo in (MEMORIA, FITNESS):
        if archivo.is_file():
            git("add", str(archivo.relative_to(REPO)).replace("\\", "/"))
    git_commit(f"bitácora: {veredicto} — {razon[:60]}")


def correr_suite(modelo_agente, reps, pausa, tareas=None):
    cmd = [sys.executable, str(AQUI / "correr_evals.py"), "-r", str(reps), "--pausa", str(pausa)]
    if modelo_agente:
        cmd += ["-m", modelo_agente]
    for tarea in tareas or []:
        cmd += ["--tarea", tarea]
    if HASTA:
        cmd += ["--hasta", str(HASTA)]
    # correr_evals.py hereda el entorno y verbo.py lee VERBO_FALLBACKS: la
    # suite usa su propia cadena, ya filtrada por el chequeo de proveedores.
    entorno = {**os.environ, "VERBO_FALLBACKS": CADENA_EVALS}
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", bufsize=1,
                          env=entorno) as p:
        for linea in p.stdout:
            print("  " + linea.rstrip())
    return resumir(next(iter(ultimos_resultados().values())))


def ultimos_resultados():
    archivos = sorted(AQUI.glob("resultados-*.json"))
    if not archivos:
        raise SystemExit("la suite no generó resultados")
    return json.loads(archivos[-1].read_text(encoding="utf-8"))


def resumir(resultados):
    """De la lista por tarea de correr_evals.py al fitness."""
    tareas = [t for t in resultados if t["corridas"]]
    corridas = [c for t in tareas for c in t["corridas"]]
    return {
        "aciertos": sum(c["paso"] for c in corridas),
        "total": len(corridas),
        "tokens": sum(c["tokens"] for c in corridas),
        # Las corridas matadas no informan tokens (quedan en 0): sin contarlas
        # aparte, colgarse más pasaba por "ahorrar".
        "matados": sum(bool(c.get("matado")) for c in corridas),
        "sin_tiempo": sum(bool(c.get("sin_tiempo")) for c in corridas),
        "segundos": sum(c.get("segundos", 0) for c in corridas),
        "fallas": [{"tarea": t["tarea"], "detalle": c["detalle"][:400],
                    "traza": c.get("traza", "")[:1200]}
                   for t in tareas for c in t["corridas"] if not c["paso"]],
        "por_tarea": {t["tarea"]: {"aciertos": sum(c["paso"] for c in t["corridas"]),
                                   "corridas": len(t["corridas"]),
                                   "tokens": sum(c["tokens"] for c in t["corridas"])
                                   // len(t["corridas"])}
                      for t in tareas},
    }


# Una comparación con muchos pares sin cupo no mide al agente, mide el día del
# proveedor: por debajo de esto no se decide nada.
MIN_FRACCION_VALIDA = 0.75


def comparar_suite(modelo_agente, reps, pausa, referencia, candidato, tareas=None, costo=None):
    """Mide `candidato` contra `referencia` (baseline), los dos copias fuera
    del repo, intercalados por rondas para que gasten el mismo cupo. Los pares
    en que cualquiera de los dos se quedó sin cupo se descartan juntos.
    Devuelve {base, cand, pares, valida, rondas, incompleto, costo_corrida}."""
    cmd = [sys.executable, str(AQUI / "correr_evals.py"), "-r", str(reps),
           "--pausa", str(pausa), "--contra", str(referencia), "--verbo", str(candidato)]
    if modelo_agente:
        cmd += ["-m", modelo_agente]
    for tarea in tareas or []:
        cmd += ["--tarea", tarea]
    if HASTA:
        cmd += ["--hasta", str(HASTA)]
    if costo:
        cmd += ["--costo", f"{costo:.0f}"]
    entorno = {**os.environ, "VERBO_FALLBACKS": CADENA_EVALS}
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", bufsize=1,
                          env=entorno) as p:
        for linea in p.stdout:
            print("  " + linea.rstrip())
    datos = ultimos_resultados()
    rondas = datos.pop("rondas", reps)
    incompleto = datos.pop("incompleto", False)
    if set(datos) != {"verbo", "contra"}:
        raise SystemExit("la comparación no generó resultados")
    validos = total = 0
    pares = []
    filtrados = {"verbo": [], "contra": []}
    for t_cand, t_base in zip(datos["verbo"], datos["contra"]):
        todos = list(zip(t_cand["corridas"], t_base["corridas"]))
        buenos = [(c, b) for c, b in todos if not c.get("sin_cupo") and not b.get("sin_cupo")]
        total += len(todos)
        validos += len(buenos)
        pares += [(c["paso"], b["paso"]) for c, b in buenos]
        filtrados["verbo"].append({"tarea": t_cand["tarea"], "corridas": [c for c, _ in buenos]})
        filtrados["contra"].append({"tarea": t_base["tarea"], "corridas": [b for _, b in buenos]})
    base, cand = resumir(filtrados["contra"]), resumir(filtrados["verbo"])
    corridas = base["total"] + cand["total"]
    return {"base": base, "cand": cand, "pares": pares, "valida": validos / max(1, total),
            "rondas": rondas, "incompleto": incompleto,
            "costo_corrida": (base["segundos"] + cand["segundos"]) / corridas if corridas else None}


def chequear_proveedores(modelos):
    """Corre verbo.py --chequear sobre todos los modelos que va a usar la
    corrida. Devuelve {modelo: estado}."""
    cmd = [sys.executable, str(ARCHIVO_VERBO), "--chequear",
           "-m", modelos[0], "--fallback", ",".join(modelos[1:])]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                       timeout=600, encoding="utf-8", errors="replace")
    estados = {}
    for linea in (r.stdout or "").splitlines():
        partes = linea.split()
        if len(partes) >= 3 and partes[0] == "[chequeo]":
            estados[partes[2]] = partes[1]
            print("  " + linea)
        elif linea.startswith("[modelos]"):
            print("  " + linea)
    if r.returncode not in (0, 1) or not estados:
        print("  " + (r.stderr or "").strip().replace("\n", "\n  "))
    return estados


def utilizables(cadena, estados):
    """Saca los modelos que no van a responder hoy. LIMITE se queda: el cupo
    vuelve solo y verbo.py ya sabe esperarlo."""
    return [m for m in cadena if estados.get(m, "OK") in ("OK", "LIMITE")]


def extraer_genoma(fuente):
    """(antes, bloque, después) del genoma, o None si las marcas no están
    exactamente una vez cada una."""
    fuente = fuente.replace("\r\n", "\n")
    if fuente.count(MARCA_INICIO) != 1 or fuente.count(MARCA_FIN) != 1:
        return None
    i = fuente.index(MARCA_INICIO) + len(MARCA_INICIO)
    j = fuente.index(MARCA_FIN)
    if j < i:
        return None
    return fuente[:i], fuente[i:j], fuente[j:]


def validar_genoma(fuente_vieja, fuente_nueva):
    """None si el genoma sigue siendo válido; si no, el motivo. El código de
    alrededor ya se puede cambiar: lo cuida contrato()."""
    import ast
    vieja, nueva = extraer_genoma(fuente_vieja), extraer_genoma(fuente_nueva)
    if nueva is None:
        return "las marcas del genoma no están (o están repetidas)"
    try:
        arbol = ast.parse(nueva[1])
    except SyntaxError as e:
        return f"el genoma no parsea (línea {e.lineno})"
    if (len(arbol.body) != 1 or not isinstance(arbol.body[0], ast.Assign)
            or [getattr(t, "id", None) for t in arbol.body[0].targets] != ["GENOMA"]):
        return "el genoma tiene que ser una sola asignación GENOMA = {...}"
    try:
        genoma = ast.literal_eval(arbol.body[0].value)
    except ValueError:
        return "el genoma no es un literal puro (nada de llamadas ni variables)"
    original = ast.literal_eval(ast.parse(vieja[1]).body[0].value)
    # Se pueden AGREGAR claves (para código nuevo que las use), no sacar.
    if not isinstance(genoma, dict) or not set(original) <= set(genoma):
        return f"el genoma tiene que conservar las claves {sorted(original)}"
    for clave, (minimo, maximo) in LIMITES_GENOMA.items():
        valor = genoma[clave]
        if type(valor) is not type(original[clave]) or not minimo <= valor <= maximo:
            return f"'{clave}' tiene que ser {type(original[clave]).__name__} entre {minimo} y {maximo}"
    reglas, herramientas, cierre = genoma["reglas"], genoma["herramientas"], genoma["cierre"]
    if not (isinstance(reglas, list) and reglas and all(isinstance(r, str) and r.strip() for r in reglas)):
        return "'reglas' tiene que ser una lista de strings no vacíos"
    if not (isinstance(herramientas, dict) and set(original["herramientas"]) <= set(herramientas)
            and all(isinstance(d, str) and d.strip() for d in herramientas.values())):
        return "'herramientas' tiene que seguir describiendo las herramientas, con texto"
    if not isinstance(cierre, str):
        return "'cierre' tiene que ser un string"
    texto = sum(map(len, reglas)) + sum(map(len, herramientas.values())) + len(cierre)
    if texto > MAX_CHARS_TEXTO_GENOMA:
        return f"el genoma pesa {texto} chars de texto (máximo {MAX_CHARS_TEXTO_GENOMA})"
    return None


def por_tarea_de(base):
    """Resultados por tarea del baseline. Los fitness viejos no los guardaban:
    se reconstruyen de la lista de fallas (sin tokens por tarea)."""
    if base.get("por_tarea"):
        return base["por_tarea"]
    tareas = sorted(t.name for t in (AQUI / "tareas").iterdir() if t.is_dir())
    corridas = max(1, base["total"] // max(1, len(tareas)))
    fallas = [f["tarea"] for f in base.get("fallas", [])]
    return {t: {"aciertos": corridas - fallas.count(t), "corridas": corridas, "tokens": 0}
            for t in tareas}


def tareas_del_filtro(base):
    """Las tareas que el baseline pasa a lo sumo un tercio de las veces: ahí
    un acierto del candidato es señal y no suerte. Si no hay ninguna tan dura,
    todas las que alguna vez fallaron."""
    previas = por_tarea_de(base)
    duras = [t for t, r in previas.items() if r["aciertos"] * 3 <= r["corridas"]]
    flojas = [t for t, r in previas.items() if r["aciertos"] < r["corridas"]]
    return sorted(set((duras or flojas) + [CANARIO]))


def pasa_el_filtro(m):
    """El candidato tiene que mantener vivo el canario y además ganarle al
    baseline medido HOY en las mismas tareas (antes se lo comparaba contra el
    fitness cacheado, de agosto), o gastar claramente menos sin perder nada."""
    cand, base = m["cand"], m["base"]
    if CANARIO in cand["por_tarea"] and cand["por_tarea"][CANARIO]["aciertos"] == 0:
        return False, "rompió el canario"
    ganados, perdidos = contar(m["pares"])
    if ganados > perdidos:
        return True, f"ganó {ganados} pares y perdió {perdidos}"
    if perdidos == 0 and ahorra(cand, base):
        return True, f"gastó {cand['tokens']} tokens contra {base['tokens']}"
    return False, (f"ganó {ganados} pares y perdió {perdidos}, sin ahorro claro "
                   f"({cand['tokens']} contra {base['tokens']} tokens)")


def mutar_con_verbo(modelo_mutador, base, cadena_mutador, quem, intentos, rechazos_hoy):
    """VERBO se edita a sí mismo, en un taller fuera del repo (no ve los tests
    ni nada más que su propio código). Devuelve (razón, vencido, error,
    ruta del candidato)."""
    fuente = ARCHIVO_VERBO.read_text(encoding="utf-8")
    taller = Path(tempfile.mkdtemp(prefix="verbo-mutador-"))
    candidato = taller / "verbo.py"
    candidato.write_text(fuente, encoding="utf-8")

    reporte = f"aciertos: {base['aciertos']}/{base['total']} · tokens totales: {base['tokens']}\n"
    fallas = reporte_de_fallas(base)
    reporte += ("FALLAS OBSERVADAS (con la traza de lo que hiciste):\n" + fallas) if fallas else \
        "Sin fallas: el objetivo es reducir el consumo de tokens sin romper nada."

    memoria = leer_memoria()
    bloque_memoria = (
        "INTENTOS ANTERIORES (tu memoria; lo descartado ya se probó y no funcionó, "
        "no lo repitas ni lo deshagas):\n\n" + memoria + "\n\n") if memoria else ""
    por_zona = fracasos_por_zona(intentos)
    zonas_txt = ", ".join(f"{z} x{n}" for z, n in por_zona.most_common(10))
    bloque_zonas = (f"ZONAS YA PROBADAS SIN ÉXITO: {zonas_txt}.\n"
                    + (f"PROHIBIDO tocar solo estas perillas: {', '.join(sorted(quem))}.\n" if quem else "")
                    ) if zonas_txt else ""
    bloque_hoy = ("HOY YA SE RECHAZARON: " + " | ".join(rechazos_hoy) + "\n") if rechazos_hoy else ""
    genoma = extraer_genoma(fuente)[1]

    prompt = (
        "Estás mejorando TU PROPIO código: verbo.py, en el directorio actual, es el agente "
        "que sos. Podés cambiar cualquier parte: el genoma (reglas, descripciones de "
        "herramientas, presupuestos y el mensaje de 'cierre'), y también el motor: el loop "
        "agéntico, cómo se compacta el historial, cómo se arma el prompt, las herramientas, "
        "cómo se esperan los límites de tasa. Las fallas por tiempo suelen venir de esperar "
        "cupo de tokens por minuto: mandar menos contexto por llamada es una palanca real.\n\n"
        f"Este es tu genoma actual:\n{genoma}\n"
        f"Mapa de verbo.py (líneas: qué hay):\n{mapa_codigo(fuente)}\n\n"
        f"Reporte de tu última evaluación:\n{reporte}\n\n"
        f"{bloque_memoria}{bloque_zonas}{bloque_hoy}\n"
        "Aplicá UNA mejora coherente (puede ser más de una edición) que ataque la causa "
        "general de las fallas, o que reduzca tokens si no hay fallas. Se acepta solo si "
        "le gana al código actual en tareas que no ves, con significancia estadística.\n"
        "PROHIBIDO hacer trampa: nada específico de las tareas que fallaron. Tiene que valer "
        "para tareas que nunca viste.\n"
        "CONTRATO (si lo rompés se descarta sin medir): la CLI conserva -p, -m, --auto, "
        "--fallback, --herramientas, --chequear y --tiempo; se sigue imprimiendo la línea "
        "[verbo-stats]; GENOMA sigue siendo un literal de Python con las mismas claves; "
        "prompt_sistema() y HERRAMIENTAS siguen existiendo y juntos pesan menos de "
        f"{MAX_CHARS_PROMPT} caracteres; nada de red, ni os.environ, ni exec/eval nuevos.\n"
        "Cómo trabajar: leé con 'leer' (usando desde/hasta, NO el archivo entero) solo lo que "
        "vas a cambiar, y editá con 'editar' copiando EXACTO el texto a reemplazar. Al final "
        "explicá la mejora en una línea."
    )
    limite = TIMEOUT_MUTADOR
    if HASTA:
        limite = max(60, min(TIMEOUT_MUTADOR, int(HASTA - time.time())))
    # -u: con el stdout bufferado, matarlo por timeout se llevaba todo lo que
    # no había flusheado (run 38: sección del mutador vacía). --tiempo un poco
    # antes del timeout duro para que corte prolijo y explique.
    cmd = [sys.executable, "-u", str(ARCHIVO_VERBO), "--auto", "-m", modelo_mutador,
           "--fallback", ",".join(cadena_mutador), "--herramientas", "leer,editar,buscar",
           "--tiempo", str(max(30, limite - 30)), "-p", prompt]
    vencido = False
    error = None
    errores = ""
    try:
        r = subprocess.run(cmd, cwd=taller, capture_output=True, text=True,
                           timeout=limite, encoding="utf-8", errors="replace")
        salida = (r.stdout or "").strip()
        # El stderr se tiraba: del 18 de agosto al 16 de octubre de 2026 el
        # mutador murió todos los días con un traceback que nadie vio.
        errores = (r.stderr or "").strip()
        if r.returncode == 3:
            vencido = True
        elif r.returncode != 0:
            ultima = errores.splitlines()[-1].strip() if errores else "sin stderr"
            error = f"exit {r.returncode}: {ultima[:160]}"
    except subprocess.TimeoutExpired as e:
        # Quedarse esperando cupo es un resultado posible, no un error del harness.
        vencido = True
        parcial = e.stdout or ""
        if isinstance(parcial, bytes):
            parcial = parcial.decode("utf-8", "replace")
        salida = parcial.strip()
        print(f"  [mutador] se venció el timeout de {limite}s")
    salida, errores = tapar_secretos(salida), tapar_secretos(errores)
    print("  --- mutador (salida completa) ---")
    print("  " + "\n  ".join(salida.splitlines()))
    print("  --- fin mutador ---")
    if errores:
        print("  --- mutador (stderr) ---")
        print("  " + "\n  ".join(errores.splitlines()))
        print("  --- fin stderr ---")
    ruido = ("→", "←", "- buscar:", "- reemplazar:", "[verbo-stats]",
             "[límite", "[tool call", "[VERBO", "VERBO ·", "[toda la cadena", "[contexto")
    lineas = [l.strip() for l in salida.splitlines()
              if l.strip() and not l.strip().startswith(ruido)]
    return (lineas[-1][:100] if lineas else "sin explicación del mutador"), vencido, error, candidato


def compila(ruta):
    r = subprocess.run([sys.executable, "-m", "py_compile", str(ruta)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def contar(pares):
    """(ganados, perdidos): pares en que solo el candidato pasó, y al revés.
    Los empates no dicen nada de cuál es mejor."""
    return (sum(1 for c, b in pares if c and not b),
            sum(1 for c, b in pares if b and not c))


def p_signos(ganados, perdidos):
    """Test de signos de una cola: probabilidad de ganar al menos `ganados` de
    los pares discordantes si candidato y baseline fueran iguales."""
    from math import comb
    n = ganados + perdidos
    if n == 0:
        return 1.0
    return sum(comb(n, k) for k in range(ganados, n + 1)) / 2 ** n


def ahorra(cand, base):
    """Ahorro de tokens que cuenta: más de 10%, sin colgarse ni quedarse sin
    tiempo más que el baseline (las corridas matadas no suman tokens)."""
    return (base["tokens"] > 0 and cand["tokens"] < base["tokens"] * 0.9
            and cand["matados"] <= base["matados"]
            and cand["sin_tiempo"] <= base["sin_tiempo"])


# Nivel de significancia del test de signos sobre la suite: con 0 pares
# perdidos hacen falta 5 ganados; con 1 perdido, 7.
ALFA = 0.05


def decidir(m):
    """¿Se acepta el candidato? Reemplaza al viejo "2 aciertos de ventaja por
    repetición": con -r 3 la suite no entra en el día (2 x 13 x 3 corridas) y
    con menos rondas esa vara pedía algo imposible o algo regalado. El test de
    signos sobre los pares discordantes escala con lo que se haya podido medir
    y nunca acepta por ruido con más de 5% de chance. Solo cuentan los pares de
    la suite: los del filtro están sesgados a favor (por algo pasó)."""
    ganados, perdidos = contar(m["pares"])
    p = p_signos(ganados, perdidos)
    if p <= ALFA:
        return True, f"ganó {ganados} pares y perdió {perdidos} (p={p:.3f})"
    if ganados >= perdidos and ahorra(m["cand"], m["base"]):
        return True, f"mismos aciertos y {m['cand']['tokens']} tokens contra {m['base']['tokens']}"
    return False, f"ganó {ganados} pares y perdió {perdidos} (p={p:.2f}, hace falta ≤{ALFA})"


def nodos_top(fuente):
    """[(nombre, desde, hasta)] de lo que hay al nivel del módulo. El genoma
    se parte por clave: 'GENOMA:max_turnos', 'GENOMA:reglas', etc."""
    nodos = []
    for n in ast.parse(fuente).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            desde = min([n.lineno] + [d.lineno for d in n.decorator_list])
            nodos.append((n.name, desde, n.end_lineno))
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            nombre = n.targets[0].id
            if nombre == "GENOMA" and isinstance(n.value, ast.Dict):
                for k, v in zip(n.value.keys, n.value.values):
                    if isinstance(k, ast.Constant):
                        nodos.append((f"GENOMA:{k.value}", k.lineno, v.end_lineno))
            else:
                nodos.append((nombre, n.lineno, n.end_lineno))
    return nodos


def zonas_tocadas(viejo, nuevo):
    """Nombres de las funciones, constantes o claves del genoma que cambió."""
    import difflib
    try:
        nodos = nodos_top(viejo)
    except SyntaxError:
        return ["módulo"]
    a, b = viejo.splitlines(), nuevo.splitlines()
    zonas = set()
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        for linea in range(i1 + 1, max(i1 + 1, i2) + 1):
            zonas.add(next((nom for nom, d, h in nodos if d <= linea <= h), "módulo"))
    return sorted(zonas)


def diff_texto(viejo, nuevo):
    import difflib
    return "".join(difflib.unified_diff(viejo.splitlines(True), nuevo.splitlines(True),
                                        "a/verbo.py", "b/verbo.py", n=2))


def lineas_agregadas(diff):
    return frozenset(l[1:].strip() for l in diff.splitlines()
                     if l.startswith("+") and not l.startswith("+++") and l[1:].strip())


def intentos_pasados():
    """Todos los intentos de la bitácora: veredicto, zonas y líneas agregadas.
    Los viejos no anotaban zonas: se deducen de las claves del genoma del diff."""
    if not MEMORIA.is_file():
        return []
    intentos = []
    for e in MEMORIA.read_text(encoding="utf-8").split("\n## ")[1:]:
        veredicto = e.splitlines()[0].split("·", 1)[-1].strip()
        diff = e.split("```diff", 1)[1] if "```diff" in e else ""
        m = re.search(r"\*\*Zonas:\*\* (.+)", e)
        if m:
            zonas = [z.strip() for z in m.group(1).split(",") if z.strip()]
        else:
            zonas = sorted({f"GENOMA:{k}" for k in re.findall(r'^\+\s*"(\w+)":', diff, re.M)})
        intentos.append({"veredicto": veredicto, "zonas": zonas,
                         "agregadas": lineas_agregadas(diff)})
    return intentos


# Perillas numéricas: probar otro valor de la misma es barato de proponer y
# casi nunca mueve nada. Del 5 al 24 de octubre de 2026 el mutador movió
# max_turnos y max_contexto_chars una y otra vez, todos descartados.
PERILLAS = {f"GENOMA:{k}" for k in ("max_turnos", "max_salida_herramienta",
                                     "max_contexto_chars", "temperatura")}


MAX_INTENTOS_PERILLA = 3


def fracasos_por_zona(intentos):
    from collections import Counter
    return Counter(z for i in intentos if not i["veredicto"].startswith("ACEPTADA")
                   and i["agregadas"] for z in i["zonas"])


def quemadas(intentos):
    return {z for z, n in fracasos_por_zona(intentos).items()
            if z in PERILLAS and n >= MAX_INTENTOS_PERILLA}


def es_repetida(diff, zonas, intentos, quem):
    """Motivo para no gastar una medición en el candidato, o None."""
    if zonas and set(zonas) <= quem:
        return f"solo toca perillas ya agotadas ({', '.join(zonas)})"
    agregadas = lineas_agregadas(diff)
    if agregadas and any(agregadas == i["agregadas"] for i in intentos
                         if not i["veredicto"].startswith("ACEPTADA")):
        return "repite exactamente un intento anterior"
    return None


# Contrato del candidato con los evals. Fuera de esto puede cambiar lo que
# quiera de verbo.py.
FLAGS_CONTRATO = ("--prompt", "--modelo", "--auto", "--fallback", "--herramientas",
                  "--chequear", "--tiempo")


# Lo que un candidato NO puede agregar (contar más veces que el baseline): leer
# los tests, salir a la red, tocar el entorno (donde están las keys) o
# ejecutar código armado en runtime. Es lo que convertiría "mejorar" en
# "hacer trampa" o en filtrar una key a un repo público.
VIGILADOS = (r"verificar\.py", r"evals[/\\]", r"tareas[/\\]", r"environ", r"getenv",
             r"API_KEY", r"GITHUB", r"https?://", r"\bsocket\b", r"\burllib\b",
             r"\brequests\b", r"\bbase64\b", r"\bexec\(", r"(?<![\w.])eval\(",
             r"__import__", r"\bimportlib\b")


MAX_CHARS_PROMPT = 6000   # prompt de sistema + esquema de herramientas (~1.6k tokens)


def contrato(candidato, fuente_vieja):
    """None si el candidato respeta el contrato; si no, el motivo."""
    nueva = candidato.read_text(encoding="utf-8")
    for patron in VIGILADOS:
        if len(re.findall(patron, nueva)) > len(re.findall(patron, fuente_vieja)):
            return f"agrega '{patron}' (vigilado: tests, red, entorno o código dinámico)"
    if "[verbo-stats]" not in nueva:
        return "ya no imprime la línea [verbo-stats] que leen los evals"

    def correr(cmd):
        try:
            return subprocess.run(cmd, cwd=candidato.parent, capture_output=True, text=True,
                                  timeout=60, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return None
    r = correr([sys.executable, str(candidato), "--help"])
    if r is None or r.returncode != 0:
        return "--help no responde"
    faltan = [f for f in FLAGS_CONTRATO if f not in r.stdout]
    if faltan:
        return f"la CLI perdió {', '.join(faltan)}"
    medir = ("import sys, json; sys.path.insert(0, sys.argv[1]); import verbo; "
             "print(len(verbo.prompt_sistema()) + len(json.dumps(verbo.HERRAMIENTAS, ensure_ascii=False)))")
    r = correr([sys.executable, "-c", medir, str(candidato.parent)])
    try:
        tam = int(r.stdout.strip().splitlines()[-1])
    except (AttributeError, ValueError, IndexError):
        return "no se pudo medir el prompt (prompt_sistema() y HERRAMIENTAS tienen que existir)"
    if tam > MAX_CHARS_PROMPT:
        return f"prompt + herramientas pesan {tam} chars (máximo {MAX_CHARS_PROMPT})"
    return None


def mapa_codigo(fuente):
    """Índice de verbo.py para el mutador: qué hay en cada rango de líneas.
    El archivo entero no entra en los 8k tokens por minuto de Groq gratis; con
    esto sabe qué leer con leer(desde, hasta) en vez de leerlo todo."""
    lineas = []
    constantes = []
    arbol = ast.parse(fuente)
    for n in arbol.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = (ast.get_docstring(n) or "").strip().splitlines()
            lineas.append(f"  {n.lineno}-{n.end_lineno} {n.name}: {doc[0][:90] if doc else ''}")
        elif isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            constantes.append(f"{n.targets[0].id}({n.lineno})")
    return "  constantes: " + ", ".join(constantes) + "\n" + "\n".join(lineas)


def reporte_de_fallas(base):
    """Una entrada por tarea con la última línea del error y la traza de lo
    que hizo el agente: sin la traza, una falla por tiempo decía solo
    "[timeout del agente]" y no había de dónde aprender."""
    fallas = base.get("fallas_recientes") or base["fallas"]
    por_tarea = {}
    for f in fallas:
        por_tarea.setdefault(f["tarea"], []).append(f)
    partes = []
    for tarea, fs in sorted(por_tarea.items()):
        ultima = [l for l in fs[-1]["detalle"].splitlines() if l.strip()][-1:] or [""]
        traza = fs[-1].get("traza", "")
        traza = "\n".join("      " + l for l in traza.splitlines()[-8:])
        partes.append(f"- [{tarea}] x{len(fs)}: {ultima[0].strip()[:150]}"
                      + (f"\n{traza}" if traza else ""))
    texto = ""
    for p in partes:
        if len(texto) + len(p) > 3000:
            break
        texto += p + "\n"
    return texto.strip()


def guardar_fallas_recientes(base, fallas):
    """Las fallas del baseline medidas hoy en el filtro: son del código actual,
    con traza, y le dan al próximo mutador algo más fresco que el fitness de
    la última suite completa. Lo commitea registrar()."""
    from datetime import datetime
    base["fallas_recientes"] = fallas
    datos = leer_fitness() or {}
    datos["fallas_recientes"] = fallas
    datos["fallas_recientes_medidas"] = f"{datetime.now():%Y-%m-%d}"
    FITNESS.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def copia_baseline(fuente):
    """El baseline es verbo.py tal como está commiteado, en una carpeta aparte:
    así baseline y candidato corren intercalados y los dos lejos de los tests."""
    ruta = Path(tempfile.mkdtemp(prefix="verbo-baseline-")) / "verbo.py"
    ruta.write_text(fuente, encoding="utf-8")
    return ruta


# Lo que se reserva para una iteración antes de arrancarla, si todavía no se
# midió ningún filtro en esta corrida (el del 24/10/2026 tardó 34 min).
ESTIMADO_ITERACION = 40 * 60


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteraciones", type=int, default=1,
                        help="Máximo de candidatos por corrida; corta antes si no queda tiempo")
    parser.add_argument("--modelo-agente", default=None,
                        help="Modelo que usa VERBO en los evals (default: el de verbo.py)")
    parser.add_argument("--modelo-mutador", default=MODELO_MUTADOR_DEFAULT,
                        help="Modelo con el que VERBO edita su código")
    parser.add_argument("-r", "--repeticiones", type=int, default=1,
                        help="Rondas máximas de la suite completa (entran las que da el tiempo)")
    parser.add_argument("--pausa", type=int, default=15)
    parser.add_argument("--minutos", type=int, default=MINUTOS_DEFAULT,
                        help="Presupuesto total de la corrida; lo que no entra queda SIN TIEMPO")
    args = parser.parse_args()
    global HASTA
    HASTA = time.time() + args.minutos * 60

    sucios = [l for l in git("status", "--porcelain").stdout.splitlines()
              if not l[3:].strip().startswith(("evals/resultados-", "evals/evolucion.log"))]
    if sucios:
        raise SystemExit(f"el repo tiene cambios sin commitear: {sucios}")

    from datetime import datetime
    print(f"\n===== evolución {datetime.now():%Y-%m-%d %H:%M:%S} · "
          f"agente={args.modelo_agente or '(default)'} · mutador={args.modelo_mutador} · "
          f"presupuesto={args.minutos} min · hasta {args.iteraciones} candidatos =====")

    # Antes de gastar nada: quién responde hoy. Una llamada mínima por modelo
    # convierte "dos meses de SIN MUTACIÓN" en una línea roja el primer día.
    global CADENA_EVALS
    cadena_mutador = [args.modelo_mutador] + [m for m in CADENA_MUTADOR.split(",")
                                              if m and m != args.modelo_mutador]
    suite = [args.modelo_agente or MODELO_SUITE] + CADENA_EVALS.split(",")
    print("[evolucion] chequeo de proveedores:")
    estados = chequear_proveedores(list(dict.fromkeys(cadena_mutador + suite)))
    cadena_mutador = utilizables(cadena_mutador, estados)
    CADENA_EVALS = ",".join(utilizables(CADENA_EVALS.split(","), estados))
    if not cadena_mutador or not utilizables(suite, estados):
        caidos = ", ".join(f"{m}={e}" for m, e in estados.items() if e not in ("OK", "LIMITE"))
        quien = "el mutador" if not cadena_mutador else "la suite"
        registrar("SIN PROVEEDORES", f"{quien} no tiene ningún modelo que responda ({caidos})", "")
        sys.exit(f"[evolucion] {quien} no tiene ningún modelo disponible: {caidos}")
    # Se muta PRIMERO y la suite se paga sólo si hubo mutación. El reporte de
    # fallas que guía al mutador sale del fitness cacheado (y de las fallas
    # que dejó el último filtro); el juicio no se ablanda: baseline y
    # candidato se miden los dos en esta misma corrida.
    base = leer_fitness()
    if base is None:
        print("[evolucion] no hay fitness cacheado: se mide el baseline una vez")
        base = correr_suite(args.modelo_agente, args.repeticiones, args.pausa)
        guardar_fitness(base)
    print(f"[evolucion] fitness de referencia: {base['aciertos']}/{base['total']} · "
          f"{base['tokens']} tokens (medido {base.get('medido', 'recién')})")
    sin_cupo = sin_tiempo = fallo_el_mutador = False
    costo_iteracion = None
    rechazos_hoy = []
    ultimo = False

    for i in range(1, args.iteraciones + 1):
        if ultimo:
            print("\n[evolucion] el mutador se quedó sin cupo: no se arrancan más candidatos")
            break
        restante = HASTA - time.time()
        reserva = costo_iteracion or ESTIMADO_ITERACION
        if restante < reserva:
            print(f"\n[evolucion] quedan {restante / 60:.0f} min y una iteración se lleva "
                  f"~{reserva / 60:.0f}: no se arranca otra")
            break
        inicio_iteracion = time.time()
        fuente_base = ARCHIVO_VERBO.read_text(encoding="utf-8")
        intentos = intentos_pasados()
        quem = quemadas(intentos)
        print(f"\n[evolucion] iteración {i}: VERBO se auto-edita con {cadena_mutador[0]}"
              + (f" (perillas agotadas: {', '.join(sorted(quem))})" if quem else ""))
        razon, vencido, error, candidato = mutar_con_verbo(
            cadena_mutador[0], base, cadena_mutador[1:], quem, intentos, rechazos_hoy)
        nuevo = candidato.read_text(encoding="utf-8")
        diff = diff_texto(fuente_base, nuevo)
        zonas = zonas_tocadas(fuente_base, nuevo) if diff else []

        if vencido:
            # Casi siempre es cupo: el 24/10/2026 los cuatro mutadores de la
            # corrida pasaron sus 20 min esperando enfriamientos de 20-40 min.
            # Otro candidato chocaría contra la misma pared: es el último.
            ultimo = True
            if not diff:
                print("[evolucion] el mutador se quedó sin tiempo sin editar nada; no se "
                      "arrancan más candidatos")
                registrar("SIN MUTACIÓN (timeout del mutador)", razon, "")
                break
            # Lo que alcanzó a editar se mide igual: compilar, el contrato y
            # la medición lo juzgan. Antes se tiraba y ese trabajo se perdía.
            print("[evolucion] el mutador se quedó sin tiempo, pero editó: se evalúa lo que dejó")
            razon = f"{razon} [cortado por tiempo]"
        if error:
            # Un crash no es "no se le ocurrió nada": se anota con su causa y
            # la Action queda en rojo, para que no pase otros dos meses callado.
            print(f"[evolucion] el mutador falló ({error})")
            registrar("FALLÓ EL MUTADOR", error, diff, zonas=zonas)
            fallo_el_mutador = True
            continue
        if not diff:
            print("[evolucion] el mutador no produjo ninguna edición; no hay candidato que evaluar")
            registrar("SIN MUTACIÓN", razon, "")
            continue
        print(f"[evolucion] zonas tocadas: {', '.join(zonas)}")

        ok, err_compilacion = compila(candidato)
        if not ok:
            print(f"[evolucion] el candidato no compila. {err_compilacion.strip()[:200]}")
            registrar("REVERTIDA (no compila)", f"{razon} [{err_compilacion.strip()[:120]}]",
                      diff, zonas=zonas)
            rechazos_hoy.append(f"{razon[:60]} (no compilaba)")
            continue
        motivo = validar_genoma(fuente_base, nuevo) or contrato(candidato, fuente_base)
        if motivo:
            print(f"[evolucion] mutación inválida ({motivo})")
            registrar("REVERTIDA (rompe el contrato)", f"{razon} [{motivo}]", diff, zonas=zonas)
            rechazos_hoy.append(f"{razon[:60]} ({motivo[:60]})")
            continue
        repetida = es_repetida(diff, zonas, intentos, quem)
        if repetida:
            # Sin diff en la bitácora: no es un intento nuevo, y no debe pesar
            # como si lo fuera la próxima vez que se cuenten las zonas.
            print(f"[evolucion] candidato repetido ({repetida}); no se gasta una medición")
            registrar("REPETIDA", f"{razon} [{repetida}]", "", zonas=zonas)
            rechazos_hoy.append(f"{razon[:60]} ({repetida})")
            continue

        referencia = copia_baseline(fuente_base)
        # Filtro barato: una ronda intercalada sobre lo que el baseline venía
        # fallando más el canario. La gran mayoría de las mutaciones no mueve
        # nada, y descubrirlo con la suite completa costaba el día entero.
        tareas = tareas_del_filtro(base)
        print(f"[evolucion] filtro barato: {len(tareas)} tareas x1, intercalado "
              f"({', '.join(tareas)})")
        f = comparar_suite(args.modelo_agente, 1, args.pausa, referencia, candidato, tareas)
        guardar_fallas_recientes(base, f["base"]["fallas"])
        if f["incompleto"]:
            print("[evolucion] el filtro no entró en el presupuesto; no se decide")
            registrar("SIN TIEMPO PARA MEDIR", f"{razon} [filtro incompleto]", diff, zonas=zonas)
            sin_tiempo = True
            continue
        if f["valida"] < MIN_FRACCION_VALIDA:
            print(f"[evolucion] filtro sin cupo ({f['valida']:.0%} de pares válidos); no se decide")
            registrar("SIN CUPO PARA MEDIR", f"{razon} [filtro: {f['valida']:.0%} de pares válidos]",
                      diff, zonas=zonas)
            sin_cupo = True
            continue
        paso, detalle = pasa_el_filtro(f)
        print(f"[evolucion] filtro: {'PASA' if paso else 'NO PASA'} — {detalle} "
              f"(candidato {f['cand']['aciertos']}/{f['cand']['total']} · {f['cand']['tokens']} tok, "
              f"baseline {f['base']['aciertos']}/{f['base']['total']} · {f['base']['tokens']} tok)")
        if not paso:
            registrar("DESCARTADA EN EL FILTRO", f"{razon} [{detalle}]", diff,
                      f["base"], f["cand"], zonas=zonas)
            rechazos_hoy.append(f"{razon[:60]} (filtro: {detalle[:50]})")
            costo_iteracion = time.time() - inicio_iteracion
            continue

        print("[evolucion] suite completa, intercalada por rondas...")
        s = comparar_suite(args.modelo_agente, args.repeticiones, args.pausa,
                           referencia, candidato, costo=f["costo_corrida"])
        print(f"[evolucion] candidato: {s['cand']['aciertos']}/{s['cand']['total']} · "
              f"{s['cand']['tokens']} tokens (baseline: {s['base']['aciertos']}/{s['base']['total']} · "
              f"{s['base']['tokens']}) · {s['rondas']} rondas · {s['valida']:.0%} de pares válidos")
        if s["rondas"] == 0:
            print("[evolucion] no entró ni una ronda de la suite; no se decide")
            registrar("SIN TIEMPO PARA MEDIR", f"{razon} [pasó el filtro; la suite no entró]",
                      diff, f["base"], f["cand"], zonas=zonas)
            sin_tiempo = True
            continue
        if s["valida"] < MIN_FRACCION_VALIDA:
            registrar("SIN CUPO PARA MEDIR", f"{razon} [suite: {s['valida']:.0%} de pares válidos]",
                      diff, s["base"], s["cand"], zonas=zonas)
            sin_cupo = True
            continue
        acepta, detalle = decidir(s)
        guardar_fitness({**s["base"], "fallas_recientes": base.get("fallas_recientes", [])})
        if acepta:
            ARCHIVO_VERBO.write_text(nuevo, encoding="utf-8")
            git("add", "verbo.py")
            git_commit(
                f"auto-iteración: {razon}\n\n"
                f"Zonas: {', '.join(zonas)}\n"
                f"Fitness: {s['base']['aciertos']}/{s['base']['total']} ({s['base']['tokens']} tok) -> "
                f"{s['cand']['aciertos']}/{s['cand']['total']} ({s['cand']['tokens']} tok); {detalle}")
            print(f"[evolucion] MEJORA ACEPTADA ({detalle}) — commit hecho")
            # Antes de registrar: registrar() es quien commitea el fitness.
            guardar_fitness(s["cand"])
            registrar("ACEPTADA", f"{razon} [{detalle}]", diff, s["base"], s["cand"], zonas=zonas)
            base = s["cand"]
        else:
            print(f"[evolucion] sin mejora ({detalle})")
            registrar("REVERTIDA (no superó al baseline)", f"{razon} [{detalle}]", diff,
                      s["base"], s["cand"], zonas=zonas)
            rechazos_hoy.append(f"{razon[:60]} (suite: {detalle[:50]})")
            base = s["base"]
        costo_iteracion = time.time() - inicio_iteracion

    print(f"\n[evolucion] FIN · fitness final: {base['aciertos']}/{base['total']} · {base['tokens']} tokens")
    if fallo_el_mutador:
        sys.exit("[evolucion] el mutador falló: ver su stderr arriba")
    if sin_tiempo:
        # En rojo también: si la medición no entra en el presupuesto hay que
        # achicarla (menos rondas o menos tareas), no esperar a que un día entre.
        sys.exit("[evolucion] la medición no entró en el presupuesto de tiempo")
    if sin_cupo:
        # En rojo a propósito: un día sin cupo para medir es un problema de
        # capacidad (sumar proveedores), no un veredicto sobre el agente.
        sys.exit("[evolucion] no hubo cupo para medir: hacen falta más proveedores")


if __name__ == "__main__":
    main()
