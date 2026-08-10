# Bitácora de evolución

Memoria del mutador: cada intento de auto-mejora con su resultado.
La lee antes de mutar para no repetir ideas ya descartadas.

## 2026-07-21 · REVERTIDA (deriva por ruido, anulada el 2026-08-07)
- **Intento:** agregar un manejador global de excepciones (`sys.excepthook`) "para evitar crashes en evaluaciones"
- **Por qué NO sirve:** se traga los tracebacks y los reemplaza por una línea sin contexto. Los tracebacks son la principal herramienta de diagnóstico del proyecto. Además no arregla ninguna falla de la suite: las fallas son de razonamiento del modelo, no crashes del proceso.
- **Diff:**
```diff
-MAX_TURNOS = 20                 # iteraciones del loop agéntico por pedido
+MAX_TURNOS = 20
+def _handle_exception(exc_type, exc, tb):
+    print(f"Error inesperado: {exc}")
+    sys.exit(1)
+sys.excepthook = _handle_exception
```

## 2026-07-31 · REVERTIDA (deriva por ruido, anulada el 2026-08-07)
- **Intento:** comentar la línea `sys.excepthook = _handle_exception` agregada el 21-jul
- **Por qué NO sirve:** deshacer a medias el intento anterior. Dejó código muerto (la función `_handle_exception` sin uso) y no cambió ningún acierto.

## 2026-08-06 · REVERTIDA (deriva por ruido, anulada el 2026-08-07)
- **Intento:** descomentar `sys.excepthook = _handle_exception` (tercera vez sobre la misma línea)
- **Por qué NO sirve:** se aceptó midiendo ruido (baseline 7/13 → candidato 9/13 con una sola corrida, cuando la misma versión oscila ±2 tareas). No hay relación causal entre un excepthook y pasar tareas de BigCodeBench. **Lección: tocar esta línea ya se probó tres veces en las dos direcciones y nunca aportó nada.**

## 2026-08-07 · NOTA DEL MANTENIMIENTO (no es un intento del mutador)
- Se revirtió el excepthook y se subió la vara del fitness: ahora una mejora de aciertos necesita superar la varianza medida (2 tareas-equivalente escaladas por repeticiones, con mínimo de 2 corridas).
- **Dónde está el margen real de mejora:** las fallas vivas son de BigCodeBench-Hard y son de *precisión*: devolver el tipo exacto que pide la spec (tuplas vs listas), cubrir casos borde, respetar redondeos. Un cambio de harness que ataque eso —forzar una verificación contra la spec antes de declarar la tarea terminada, o escribir un test propio antes de responder— tiene chance real de sumar 2 tareas. Los retoques cosméticos no.

## 2026-08-07 · INTENTO DESCARTADO EN PRUEBA (no llegó a commitearse)
- **Intento:** agregar al prompt de sistema la regla "cuando la respuesta sea una colección, devolvela como tupla y eliminá los números negativos", y cambiar un `return []` por `return ()` dentro de verbo.py.
- **Por qué NO sirve:** es hacer trampa contra la propia evaluación. Esas dos frases son las respuestas puntuales de las tareas 21 y 25; meterlas en el prompt sube el puntaje sin mejorar al agente y lo empeora para cualquier otro trabajo. **La mejora tiene que ser general: valer para tareas que nunca se vieron.** Además el `return []` que quiso tocar es código interno de VERBO, no una respuesta al usuario.
- **Nota de comportamiento:** en esa corrida el modelo, tras un rate limit, empezó a emitir tool calls como texto plano y después afirmó haber editado archivos que nunca tocó. El guardrail lo registró correctamente como "sin mutación": **no hay que creerle al resumen del mutador, solo al diff**.

## 2026-08-07 · SIN MUTACIÓN
- **Intento:** **Resumen:** ahora el agente crea los directorios inexistentes al encontrarse con el error correspon

## 2026-08-08 · REVERTIDA (no superó el fitness)
- **Intento:** Se incrementó el número máximo de turnos del bucle agente de 20 a 30 (`MAX_TURNOS = 30`). Esto permi
- **Medición:** aciertos 26/39 → 27/39 · tokens 278175 → 292840
- **Diff:**
```diff
diff --git a/verbo.py b/verbo.py
index ac75d33..1d5c92f 100644
--- a/verbo.py
+++ b/verbo.py
@@ -99,7 +99,7 @@ MAX_ESPERA_GLOBAL = 120  # si el próximo cupo tarda más que esto, abandonar
 
 MAX_SALIDA_HERRAMIENTA = 6000   # chars que se devuelven al modelo por herramienta
 MAX_CONTEXTO_CHARS = 60000      # umbral para compactar historial
-MAX_TURNOS = 20                 # iteraciones del loop agéntico por pedido
+MAX_TURNOS = 30                 # iteraciones del loop agéntico por pedido
 
 HERRAMIENTAS = [
     {"type": "function", "function": {
```

## 2026-08-10 · SIN MUTACIÓN
- **Intento:** mejora automática
