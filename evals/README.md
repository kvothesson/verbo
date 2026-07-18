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
```

Cada corrida guarda un `resultados-<fecha>.json` con pass/fail, segundos,
tokens y llamadas por tarea — para comparar modelos con números.

## Las tareas

| # | Tarea | Qué mide |
|---|---|---|
| 01 | crear-script | Crear un archivo y verificar su salida exacta |
| 02 | bug-promedio | Diagnosticar un bug y arreglarlo con edición mínima |
| 03 | fizzbuzz | Implementar lógica con spec precisa (función + main) |
| 04 | refactor | Cambio coordinado en múltiples archivos sin romper nada |
| 05 | csv-filtrado | Procesar datos y producir un archivo con formato exacto |
| 06 | test-rojo | Arreglar código para que pase un test — **con detector de trampa**: si el agente modifica el test en vez del código, FAIL |

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
