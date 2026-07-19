#!/usr/bin/env python3
"""
Genera tareas de evals a partir de un subconjunto curado de HumanEval
(OpenAI, MIT license: https://github.com/openai/human-eval).

HumanEval ya trae, por problema: firma+docstring (el enunciado), una
solución canónica (para validar el verificador) y un check(candidate)
con asserts (el verificador). Es exactamente el formato que necesita
nuestra suite, y es un benchmark real y reconocido — no algo inventado
a mano como las tareas 01-09.

evals/humaneval/subset.json contiene solo los 5 problemas elegidos (no
las 164 del dataset completo), extraídos una vez y commiteados: la
suite no depende de internet para correr.

NOTA (2026-07-19): las tareas HumanEval fueron RETIRADAS de la suite — la
cadena default pasó 11/11 incluyendo los 6 problemas con peor pass rate
histórico. HumanEval (2021) está saturado para los modelos actuales; la
dificultad real ahora viene de BigCodeBench (ver importar_bigcodebench.py).
Este script y su subset quedan como registro y por si sirven para evaluar
modelos más chicos.

Uso: python importar_humaneval.py
Idempotente: pisa las carpetas 10-humaneval-* si ya existen.
"""
import json
from pathlib import Path

AQUI = Path(__file__).parent
SUBSET = AQUI / "humaneval" / "subset.json"
TAREAS = AQUI / "tareas"
NUMERO_INICIAL = 10

PLANTILLA_PROMPT = """Implementá la siguiente función de HumanEval (benchmark público de OpenAI) en un archivo llamado {archivo}. Copiá la firma y los imports tal cual, y completá el cuerpo para que cumpla exactamente la especificación del docstring:

{spec}
"""


def slug(nombre):
    return nombre.replace("_", "-")


def generar():
    problemas = json.loads(SUBSET.read_text(encoding="utf-8"))
    for i, p in enumerate(problemas):
        n = NUMERO_INICIAL + i
        carpeta = TAREAS / f"{n:02d}-humaneval-{slug(p['entry_point'])}"
        carpeta.mkdir(parents=True, exist_ok=True)

        archivo = f"{p['entry_point']}.py"
        (carpeta / "prompt.txt").write_text(
            PLANTILLA_PROMPT.format(archivo=archivo, spec=p["prompt"].strip()),
            encoding="utf-8")

        # Import * (no solo entry_point): algunos problemas definen funciones
        # auxiliares (poly, encode_cyclic) que check() llama directamente.
        verificar = (
            f"import sys\n"
            f"sys.path.insert(0, \".\")\n"
            f"from {p['entry_point']} import *\n\n"
            f"{p['test']}\n\n"
            f"check({p['entry_point']})\n"
            f"print(\"PASS\")\n"
        )
        (carpeta / "verificar.py").write_text(verificar, encoding="utf-8")
        print(f"generado: {carpeta.relative_to(AQUI.parent)}")


if __name__ == "__main__":
    generar()
