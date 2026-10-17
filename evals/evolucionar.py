#!/usr/bin/env python3
"""
Auto-iteración de VERBO: el agente mejora su propio código, con la suite
de evals como juez y git como red de seguridad.

El mutador ES el propio VERBO: se lanza una instancia del agente sobre su
propio repositorio con el texto exacto de su GENOMA (el bloque delimitado de
verbo.py con reglas, descripciones de herramientas y presupuestos) y la
instrucción de editarlo. No lee archivos: todo el pedido tiene que entrar en
los 8k tokens por minuto de Groq gratis.

Loop por corrida:
  0. chequeo de proveedores: una llamada mínima a cada modelo; los que
     rechazan quedan afuera y, si no queda ninguno, la corrida sale en rojo
  1. VERBO edita su genoma guiado por el fitness cacheado Y por su bitácora
  2. si no editó nada, se corta acá: sin candidato no se gasta un token
  3. guardrails: solo verbo.py, py_compile, y solo dentro del genoma (que
     tiene que seguir siendo un literal válido y con límites)
  4. filtro barato: una corrida sobre las tareas que el baseline fallaba más
     el canario; si no resuelve nada nuevo ni ahorra tokens, se descarta
  5. correr la suite dos veces, sin mutar y mutado (baseline y candidato)
  6. si el fitness mejora -> git commit; si no -> git checkout (revert)
  7. pase lo que pase, el intento queda anotado en la bitácora (commiteada)

Se muta ANTES de medir a propósito: la suite y el mutador comen del mismo
cupo gratis, y medir primero dejaba al mutador sin nada con qué trabajar.

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
import os
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
CADENA_EVALS = ("groq/qwen/qwen3.6-27b,groq/llama-3.3-70b-versatile,"
                "groq/openai/gpt-oss-20b,openrouter/openai/gpt-oss-20b:free")
# Cerebras era el primario hasta que su tier gratis empezó a devolver 402
# (2026-08-18). Ojo: groq/openai/gpt-oss-120b también es el modelo principal
# de la suite (el default de verbo.py), así que vuelven a compartir cupo. Lo
# que lo hace tolerable es el orden: se muta primero, el filtro gasta poco, y
# la suite completa solo corre si el candidato lo pasó; si el principal se
# agota, la suite sigue con CADENA_EVALS.
MODELO_MUTADOR_DEFAULT = "groq/openai/gpt-oss-120b"
CADENA_MUTADOR = "cerebras/gpt-oss-120b"   # si vuelve el cupo gratis; si no, se saltea
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
# 2026-08-16: se comió los 600s sin llegar a nada). El workflow corta a los 180
# min y el peor caso acá es mutador + dos suites, así que hay lugar de sobra.
TIMEOUT_MUTADOR = 2400     # segundos; agotarlo es un veredicto, no un crash


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
    # correr_evals.py hereda el entorno y verbo.py lee VERBO_FALLBACKS: la
    # suite usa su propia cadena, ya filtrada por el chequeo de proveedores.
    entorno = {**os.environ, "VERBO_FALLBACKS": CADENA_EVALS}
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", bufsize=1,
                          env=entorno) as p:
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
        # Por tarea, para que el filtro barato compare contra el baseline sin
        # volver a medirlo.
        "por_tarea": {t["tarea"]: {"aciertos": t["aciertos"],
                                   "corridas": len(t["corridas"]),
                                   "tokens": sum(c["tokens"] for c in t["corridas"])
                                   // max(1, len(t["corridas"]))}
                      for t in resultados},
    }


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
    """None si la mutación se quedó dentro del genoma y el genoma es válido;
    si no, el motivo del rechazo."""
    import ast
    vieja, nueva = extraer_genoma(fuente_vieja), extraer_genoma(fuente_nueva)
    if nueva is None:
        return "las marcas del genoma no están (o están repetidas)"
    if vieja is None or (vieja[0], vieja[2]) != (nueva[0], nueva[2]):
        return "editó código fuera del genoma"
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
    if not isinstance(genoma, dict) or set(genoma) != set(original):
        return f"el genoma tiene que tener exactamente las claves {sorted(original)}"
    for clave, (minimo, maximo) in LIMITES_GENOMA.items():
        valor = genoma[clave]
        if type(valor) is not type(original[clave]) or not minimo <= valor <= maximo:
            return f"'{clave}' tiene que ser {type(original[clave]).__name__} entre {minimo} y {maximo}"
    reglas, herramientas, cierre = genoma["reglas"], genoma["herramientas"], genoma["cierre"]
    if not (isinstance(reglas, list) and reglas and all(isinstance(r, str) and r.strip() for r in reglas)):
        return "'reglas' tiene que ser una lista de strings no vacíos"
    if not (isinstance(herramientas, dict) and set(herramientas) == set(original["herramientas"])
            and all(isinstance(d, str) and d.strip() for d in herramientas.values())):
        return "'herramientas' tiene que describir las mismas herramientas, con texto"
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


def pasa_el_filtro(cand, base):
    """El candidato tiene que mantener vivo el canario y además resolver algo
    que el baseline fallaba, o gastar claramente menos en esas mismas tareas."""
    por_tarea = cand["por_tarea"]
    if CANARIO in por_tarea and por_tarea[CANARIO]["aciertos"] == 0:
        return False, "rompió el canario"
    previas = por_tarea_de(base)
    ganadas = [t for t, r in por_tarea.items() if t != CANARIO and r["aciertos"] > 0
               and t in previas and previas[t]["aciertos"] < previas[t]["corridas"]]
    if ganadas:
        return True, f"resolvió {', '.join(ganadas)}"
    comunes = [t for t in por_tarea if t in previas]
    if comunes:
        antes = sum(previas[t]["tokens"] for t in comunes)
        ahora = sum(por_tarea[t]["tokens"] for t in comunes)
        if antes and ahora < antes * 0.9:
            return True, f"gastó {ahora} tokens contra {antes}"
    return False, "no resolvió ninguna tarea que fallaba ni ahorró tokens"


def mutar_con_verbo(modelo_mutador, base, cadena_mutador):
    """VERBO edita su genoma guiado por el reporte de la suite.

    Devuelve (razón, se_venció_el_timeout, error). `error` es None si el
    mutador terminó bien; si no, el exit code y la última línea de su stderr.
    """
    # Una línea por tarea con la última línea del error, que es la que dice
    # qué pasó: el traceback entero no entra en los 8k tokens por minuto de
    # Groq gratis (run 38992083589: 413 por pedir 8175).
    por_tarea = {}
    for f in base["fallas"]:
        ultima = [l for l in f["detalle"].splitlines() if l.strip()][-1:] or [""]
        por_tarea.setdefault(f["tarea"], []).append(ultima[0].strip()[:150])
    reporte = f"aciertos: {base['aciertos']}/{base['total']} · tokens totales: {base['tokens']}\n"
    if por_tarea:
        reporte += "FALLAS OBSERVADAS:\n" + "\n".join(
            f"- [{t}] x{len(ds)}: {ds[-1]}" for t, ds in sorted(por_tarea.items()))
    else:
        reporte += "Sin fallas: el objetivo es reducir el consumo de tokens sin romper nada."

    memoria = leer_memoria()
    bloque_memoria = (
        "INTENTOS ANTERIORES (tu memoria; lo REVERTIDO ya se probó y no funcionó, "
        "no lo repitas ni lo deshagas):\n\n" + memoria + "\n\n"
    ) if memoria else ""
    genoma = extraer_genoma(ARCHIVO_VERBO.read_text(encoding="utf-8"))[1]

    prompt = (
        "Estás mejorando TU PROPIO comportamiento. En verbo.py, entre las líneas "
        "'# >>> GENOMA' y '# <<< GENOMA', está tu genoma: tus reglas, cómo se te "
        "describen las herramientas, tus presupuestos y un mensaje de 'cierre' que, "
        "si no está vacío, recibís la primera vez que querés dar una tarea por "
        "terminada. Es lo ÚNICO que podés cambiar. Este es el texto exacto:\n\n"
        f"{genoma}\n"
        f"Reporte de tu última evaluación:\n{reporte}\n\n"
        f"{bloque_memoria}"
        "Aplicá UNA mejora al genoma que ataque la causa general de las fallas (o que "
        "reduzca tokens si no hay fallas). Para aceptarse tiene que hacer pasar al "
        "menos 2 tareas más de forma sostenida, o ahorrar más del 10% de tokens.\n"
        "PROHIBIDO hacer trampa: nada de respuestas específicas de las tareas que "
        "fallaron (del tipo 'devolvé tuplas' o 'filtrá los negativos'). La mejora "
        "tiene que valer para tareas que nunca viste.\n"
        "Cómo trabajar: NO leas ni busques archivos, ya tenés todo el texto arriba. "
        "Hacé UNA llamada a 'editar' sobre verbo.py, con 'buscar' copiado EXACTO de "
        "una parte del genoma (por ejemplo una regla entera, o la línea de 'cierre'). "
        "El genoma tiene que seguir siendo un literal de Python con las mismas claves. "
        "Si 'editar' devuelve error, corregí y reintentá. Al final explicá la mejora "
        "en una línea."
    )
    # -u a propósito: con el stdout del hijo bufferado, matarlo por timeout se
    # lleva puesto todo lo que escribió y no flusheó. En el run 38 eso dejó la
    # sección del mutador COMPLETAMENTE vacía, que es la peor evidencia posible
    # justo en el caso que hay que diagnosticar. Sin buffer, lo que alcanzó a
    # hacer queda en el log aunque lo corten a mitad.
    cmd = [sys.executable, "-u", str(ARCHIVO_VERBO), "--auto", "-m", modelo_mutador,
           "--fallback", ",".join(cadena_mutador), "-p", prompt]
    vencido = False
    error = None
    errores = ""
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                           timeout=TIMEOUT_MUTADOR, encoding="utf-8", errors="replace")
        salida = (r.stdout or "").strip()
        # El stderr se tiraba: del 18 de agosto al 16 de octubre de 2026 el
        # mutador murió todos los días a los pocos segundos con un traceback
        # que nadie vio, y la bitácora lo anotó como un "SIN MUTACIÓN" más.
        errores = (r.stderr or "").strip()
        if r.returncode != 0:
            ultima = errores.splitlines()[-1].strip() if errores else "sin stderr"
            error = f"exit {r.returncode}: {ultima[:160]}"
    except subprocess.TimeoutExpired as e:
        # Que el mutador se quede esperando cupo es un resultado posible, no un
        # error del harness. Sin este except la excepción mataba la corrida
        # entera: la Action quedaba en rojo y el día no dejaba ni una línea en
        # la bitácora (pasó el 15 y el 16 de agosto de 2026).
        vencido = True
        parcial = e.stdout or ""
        if isinstance(parcial, bytes):
            parcial = parcial.decode("utf-8", "replace")
        salida = parcial.strip()
        print(f"  [mutador] se venció el timeout de {TIMEOUT_MUTADOR}s")
    print("  --- mutador (salida completa) ---")
    print("  " + "\n  ".join(salida.splitlines()))
    print("  --- fin mutador ---")
    if errores:
        print("  --- mutador (stderr) ---")
        print("  " + "\n  ".join(errores.splitlines()))
        print("  --- fin stderr ---")
    # Se filtra por el texto YA sin sangría: VERBO imprime las herramientas
    # como "  → nombre", sus resultados como "    ← resumen" y los detalles de
    # edición como "    - buscar:". Filtrar por el string crudo dejaba pasar
    # esas líneas y la "razón" del commit terminaba siendo un output de tool.
    ruido = ("→", "←", "- buscar:", "- reemplazar:", "[verbo-stats]",
             "[límite", "[tool call", "[VERBO", "VERBO ·")
    lineas = [l.strip() for l in salida.splitlines()
              if l.strip() and not l.strip().startswith(ruido)]
    # "mejora automática" es el fallback cuando el mutador no llegó a explicar
    # nada: si murió por cupo o por timeout no hay última línea que rescatar.
    return (lineas[-1][:100] if lineas else "sin explicación del mutador"), vencido, error


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
    parser.add_argument("--modelo-mutador", default=MODELO_MUTADOR_DEFAULT,
                        help="Modelo con el que VERBO edita su genoma")
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
    # fallas que guía al mutador sale del fitness cacheado: no hace falta que
    # sea de hoy (las fallas vivas son las mismas hace semanas), y medirlo antes
    # de mutar costaba el cupo entero del día justo antes del único paso que
    # hace avanzar el proyecto. El juicio no se ablanda: cuando hay candidato,
    # baseline y candidato se miden los dos en esta misma corrida.
    base = leer_fitness()
    if base is None:
        print("[evolucion] no hay fitness cacheado: se mide el baseline una vez")
        base = correr_suite(args.modelo_agente, args.repeticiones, args.pausa)
        guardar_fitness(base)
    print(f"[evolucion] fitness de referencia: {base['aciertos']}/{base['total']} · "
          f"{base['tokens']} tokens (medido {base.get('medido', 'recién')})")
    medido_en_esta_corrida = False
    fallo_el_mutador = False

    for i in range(1, args.iteraciones + 1):
        print(f"\n[evolucion] iteración {i}: VERBO se auto-edita con {cadena_mutador[0]}")
        untracked_antes = archivos_sin_trackear()
        razon, vencido, error = mutar_con_verbo(cadena_mutador[0], base, cadena_mutador[1:])
        nuevos = archivos_sin_trackear() - untracked_antes

        cambiados = [f for f in git("diff", "--name-only").stdout.split() if f]
        intrusos = sorted(f for f in nuevos if not f.startswith("evals/resultados-"))
        # Se captura ANTES de revertir: es lo que hace que la memoria sirva
        # (saber qué línea se tocó, no solo la explicación del modelo).
        diff = git("diff", "--", "verbo.py").stdout
        if vencido:
            # Se revierte aunque haya alcanzado a editar: lo cortaron a mitad de
            # camino, no es un cambio que el mutador haya dado por terminado.
            print("[evolucion] el mutador se quedó sin tiempo; no hay candidato "
                  "que evaluar")
            revertir(nuevos)
            registrar("SIN MUTACIÓN (timeout del mutador)", razon, diff)
            continue
        if error:
            # Un crash no es "no se le ocurrió nada": se anota con su causa y
            # la Action queda en rojo, para que no pase otros dos meses callado.
            print(f"[evolucion] el mutador falló ({error}); revert")
            revertir(nuevos)
            registrar("FALLÓ EL MUTADOR", error, diff)
            fallo_el_mutador = True
            continue
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

        motivo = validar_genoma(git("show", "HEAD:verbo.py").stdout,
                                ARCHIVO_VERBO.read_text(encoding="utf-8"))
        if motivo:
            print(f"[evolucion] mutación inválida ({motivo}); revert")
            revertir(nuevos)
            registrar("REVERTIDA (genoma inválido)", f"{razon} [{motivo}]", diff)
            continue

        # Filtro barato: una corrida sobre lo que el baseline fallaba. La gran
        # mayoría de las mutaciones no mueve nada, y descubrirlo con la suite
        # completa costaba el cupo de un día entero.
        tareas = tareas_del_filtro(base)
        print(f"[evolucion] filtro barato: {len(tareas)} tareas x1 ({', '.join(tareas)})")
        filtro = correr_suite(args.modelo_agente, 1, args.pausa, tareas)
        paso, detalle = pasa_el_filtro(filtro, base)
        print(f"[evolucion] filtro: {'PASA' if paso else 'NO PASA'} — {detalle} "
              f"({filtro['aciertos']}/{filtro['total']} · {filtro['tokens']} tokens)")
        if not paso:
            git("checkout", "--", "verbo.py")
            registrar("DESCARTADA EN EL FILTRO", f"{razon} [{detalle}]", diff)
            continue

        # Hay candidato: recién ahora se gasta cupo en medir. El baseline se
        # mide con el código SIN mutar, así que la mutación se guarda aparte
        # y se repone después: comparar contra un número de otro día sería
        # medir la deriva del proveedor, no el efecto del cambio.
        if not medido_en_esta_corrida:
            fuente_candidato = ARCHIVO_VERBO.read_text(encoding="utf-8")
            git("checkout", "--", "verbo.py")
            print("[evolucion] midiendo baseline (verbo.py sin mutar)...")
            base = correr_suite(args.modelo_agente, args.repeticiones, args.pausa)
            print(f"[evolucion] baseline: {base['aciertos']}/{base['total']} · "
                  f"{base['tokens']} tokens")
            ARCHIVO_VERBO.write_text(fuente_candidato, encoding="utf-8")
            guardar_fitness(base)
            medido_en_esta_corrida = True

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
            # Antes de registrar: registrar() es quien commitea el fitness, y
            # todavía necesita el base viejo para anotar la medición del salto.
            guardar_fitness(cand)
            registrar("ACEPTADA", razon, diff, base, cand)
            base = cand
        else:
            git("checkout", "--", "verbo.py")
            print("[evolucion] sin mejora — revert")
            registrar("REVERTIDA (no superó el fitness)", razon, diff, base, cand)

    print(f"\n[evolucion] FIN · fitness final: {base['aciertos']}/{base['total']} · {base['tokens']} tokens")
    if fallo_el_mutador:
        sys.exit("[evolucion] el mutador falló: ver su stderr arriba")


if __name__ == "__main__":
    main()
