# Evals de VERBO

Mini-suite de evaluación al estilo SWE-bench: tareas reales con **verificación
automática**. El agente trabaja en un sandbox temporal; un script que él nunca
ve decide PASS/FAIL comprobando el resultado concreto (archivos, salidas,
comportamiento). Nada de "me parece que respondió bien" — o el código funciona
o no funciona.

## Correr

```bash
cd evals
python correr_evals.py                                  # modelo default (Groq gratis)
python correr_evals.py -m gemini/gemini-2.5-flash       # otro modelo
python correr_evals.py -m groq/openai/gpt-oss-120b -m groq/llama-3.3-70b-versatile   # comparar
python correr_evals.py --tarea 06-test-rojo             # una sola tarea
python correr_evals.py --pausa 30                       # más espera entre tareas (límites TPM)
python correr_evals.py -r 3                             # 3 corridas por tarea (varianza)
```

Los agentes **no son deterministas**: la misma tarea puede salir bien o mal
según el humor del sampling. Una corrida única es anécdota; `-r 3` da un pass
rate honesto. El reporte muestra `PPF 2/3` — cada letra es una corrida.

Cada corrida guarda un `resultados-<fecha>.json` con pass/fail, segundos,
tokens y llamadas por tarea — para comparar modelos con números.

## Las tareas

| # | Tarea | Qué mide |
|---|---|---|
| 01 | crear-script | Canario barato (~2k tokens): si esto falla, el loop agéntico está roto |
| 02 | bug-promedio | Diagnosticar un bug y arreglarlo con edición mínima |
| 04 | refactor | Cambio coordinado en múltiples archivos sin romper nada |
| 06 | test-rojo | Arreglar código para que pase un test — **con detector de trampa**: si el agente modifica el test en vez del código, FAIL |
| 07 | codebase-bug | Bug enterrado en una codebase de 4 archivos: solo se da el síntoma, el agente debe navegar el código y localizarlo |
| 08 | tdd-carrito | TDD puro: los tests existen, la clase no. Implementar desde la spec implícita en los tests, sin tocarlos (hash-check anti-trampa) |
| 21-26 | bigcodebench-* | 6 problemas de [BigCodeBench-Hard](https://github.com/bigcode-project/bigcodebench) (Apache 2.0), el benchmark 2024 donde los mejores modelos rondan 30-40%: specs largas con varias librerías stdlib y casos borde traicioneros. El agente no ve los tests |

La suite se poda con datos: las tareas que ningún modelo de la cadena fallaba
(fizzbuzz, csv, casos-borde y todo HumanEval — incluso sus 6 problemas más
duros terminaron 11/11) fueron retiradas para no gastar tokens en mediciones
sin información. Historial completo en git.

## Importar más de HumanEval

`evals/humaneval/subset.json` tiene solo los 5 problemas elegidos (no las
164 del dataset completo, para no inflar el repo). Para sumar otro:

```bash
# 1. Bajar el dataset completo (una vez, no se commitea)
curl -sL https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz | gunzip > /tmp/HumanEval.jsonl

# 2. Elegir un task_id (ej HumanEval/53) y agregarlo a evals/humaneval/subset.json
# 3. Regenerar
python importar_humaneval.py

# 4. SIEMPRE validar antes de confiar en la tarea nueva: la solución canónica
#    debe dar PASS, un stub vacío debe dar FAIL (ver el proceso en el historial
#    de commits — importar_humaneval.py no lo automatiza todavía)
```

## Agregar una tarea

```
tareas/07-mi-tarea/
    prompt.txt      # el pedido, como lo escribiría un usuario
    setup/          # (opcional) archivos de partida
    verificar.py    # asserts sobre el resultado; exit 0 = PASS
```

Reglas de oro: el prompt no debe filtrar la solución, y `verificar.py` debe
chequear el **comportamiento** (ejecutar el código, comparar salidas), no la
forma exacta del texto — hay muchas maneras válidas de escribir la solución.

## Qué mirar en los resultados

- **Pass rate**: la métrica principal. Compará modelos con la misma suite.
- **Tokens por tarea**: costo real — importa en tiers gratis con límites TPM.
- **Llamadas**: cuántas iteraciones necesitó; menos llamadas = más eficiente.
- **Modo de falla**: el campo `detalle` del JSON dice *por qué* falló — un
  agente que falla por límite de tasa no es lo mismo que uno que hace trampa.
