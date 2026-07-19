#!/usr/bin/env python3
"""
Genera tareas de evals a partir de un subconjunto curado de BigCodeBench-Hard
(BigCode Project, Apache 2.0: https://github.com/bigcode-project/bigcodebench).

Por qué BigCodeBench y no más HumanEval: HumanEval (2021) está saturado —
la cadena default pasó 11/11 incluyendo los 6 problemas con peor pass rate
histórico. BigCodeBench-Hard (2024) combina varias librerías por problema y
specs largas con casos borde; los mejores modelos rondan 30-40% de pass rate.

El subset curado (evals/bigcodebench/subset.json) contiene solo problemas que:
  - usan únicamente stdlib (nada de pip install en el sandbox)
  - no tocan red ni recursos del sistema (sin ftplib/socket/subprocess/...)
  - validan localmente: solución canónica PASS, stub FAIL, tests < 15s

Uso: python importar_bigcodebench.py
Idempotente: pisa las carpetas 21-bigcodebench-* si ya existen.
"""
import json
from pathlib import Path

AQUI = Path(__file__).parent
SUBSET = AQUI / "bigcodebench" / "subset.json"
TAREAS = AQUI / "tareas"
NUMERO_INICIAL = 21

PLANTILLA_PROMPT = """Resolvé el siguiente problema de BigCodeBench (benchmark público del BigCode Project). Guardá tu implementación en un archivo llamado solucion.py. Tu código será verificado con tests que no ves: cubrí los casos borde de la especificación.

{spec}
"""

PLANTILLA_VERIFICAR = """import sys
import unittest
sys.path.insert(0, ".")
from solucion import *

{test}

if __name__ == "__main__":
    resultado = unittest.main(exit=False, verbosity=0).result
    if not resultado.wasSuccessful():
        raise SystemExit(1)
    print("PASS")
"""


def generar():
    problemas = json.loads(SUBSET.read_text(encoding="utf-8"))
    for i, p in enumerate(problemas):
        n = NUMERO_INICIAL + i
        numero = p["task_id"].split("/")[-1]
        carpeta = TAREAS / f"{n:02d}-bigcodebench-{numero}"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "prompt.txt").write_text(
            PLANTILLA_PROMPT.format(spec=p["instruct_prompt"].strip()),
            encoding="utf-8")
        (carpeta / "verificar.py").write_text(
            PLANTILLA_VERIFICAR.format(test=p["test"]), encoding="utf-8")
        print(f"generado: {carpeta.relative_to(AQUI.parent)}")


if __name__ == "__main__":
    generar()
