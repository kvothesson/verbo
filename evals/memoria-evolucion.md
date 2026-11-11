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

## 2026-08-11 · REVERTIDA (no superó el fitness)
- **Intento:** mejora automática
- **Medición:** aciertos 28/39 → 27/39 · tokens 314439 → 326527
- **Diff:**
```diff
diff --git a/verbo.py b/verbo.py
index ac75d33..efc5ba3 100644
--- a/verbo.py
+++ b/verbo.py
@@ -440,7 +440,18 @@ def turno(estado, mensajes, auto):
         msg = respuesta.choices[0].message
 
         if not msg.tool_calls:
-            print(f"\n{msg.content or '(sin respuesta)'}")
+            # Intentar normalizar la salida si es una literal Python
+            try:
+                import ast
+                literal = ast.literal_eval(msg.content or "")
+                if isinstance(literal, list):
+                    literal = tuple(literal)
+                    msg_content = str(literal)
+                else:
+                    msg_content = msg.content
+            except Exception:
+                msg_content = msg.content
+            print(f"\n{msg_content or '(sin respuesta)'}")
             mensajes.append({"role": "assistant", "content": msg.content or ""})
       
```

## 2026-08-12 · SIN MUTACIÓN
- **Intento:** mejora automática

## 2026-08-13 · SIN MUTACIÓN
- **Intento:** mejora automática

## 2026-08-14 · SIN MUTACIÓN
- **Intento:** mejora automática

## 2026-08-16 · NOTA DEL MANTENIMIENTO (no es un intento del mutador)
- **Los cinco "SIN MUTACIÓN" del 10 al 14 de agosto no fueron falta de ideas, fue falta de cupo.** La suite corría primero y se comía ~295k tokens del día contra los mismos modelos que después necesitaba el mutador. En el log del 14 se ve entero: el mutador arranca, groq ya está enfriando 1286s, cae a cerebras, también enfriando, y abandona porque `MAX_ESPERA_GLOBAL` son 120s. Alcanzó a leer verbo.py y nada más.
- **Las corridas del 15 y del 16 fallaron en rojo por lo mismo**, pero en vez de rendirse rápido el mutador esperó cupo hasta chocar el timeout de 600s. Ese `TimeoutExpired` no estaba capturado: mataba el script y esos dos días no dejaron ni entrada acá.
- **Qué cambió:** (1) se muta ANTES de medir y la suite se paga sólo si hubo mutación, así un día sin candidato no quema nada; (2) el timeout del mutador es un veredicto anotado, no un crash; (3) el mutador usa cerebras y la suite se queda con groq/openrouter, así dejan de competir por el mismo cupo. El fitness de referencia queda cacheado en `evals/fitness-actual.json`, commiteado, porque el runner es efímero.
- **Lo que NO se ablandó:** cuando hay candidato, baseline y candidato se siguen midiendo los dos en la misma corrida. El cacheado sólo alimenta el reporte de fallas del prompt, nunca el juicio.

## 2026-08-16 · SIN MUTACIÓN (timeout del mutador)
- **Intento:** sin explicación del mutador
- **Diff:**
```diff
diff --git a/verbo.py b/verbo.py
index ac75d33..52d4cc8 100644
--- a/verbo.py
+++ b/verbo.py
@@ -99,7 +99,7 @@ MAX_ESPERA_GLOBAL = 120  # si el próximo cupo tarda más que esto, abandonar
 
 MAX_SALIDA_HERRAMIENTA = 6000   # chars que se devuelven al modelo por herramienta
 MAX_CONTEXTO_CHARS = 60000      # umbral para compactar historial
-MAX_TURNOS = 20                 # iteraciones del loop agéntico por pedido
+MAX_TURNOS = 30                 # iteraciones del loop agéntico por pedido
 
 HERRAMIENTAS = [
     {"type": "function", "function": {
@@ -440,6 +440,10 @@ def turno(estado, mensajes, auto):
         msg = respuesta.choices[0].message
 
         if not msg.tool_calls:
+            # Si la respuesta contiene código Python con la función esperada y aún no existe 'solucion.py', crearla.
+            if 'def task_func' in (msg.content or '') and not Path('solucion.py').exists():
+  
```

## 2026-08-16 · NOTA DEL MANTENIMIENTO (run 38, disparado a mano)
- Primera corrida con el orden nuevo: verde, baseline 26/39 con 300116 tokens, fitness cacheado. El timeout quedó anotado como veredicto en vez de tirar la corrida abajo, que era la mitad del arreglo.
- **Pero el mutador volvió a agotar el tiempo, ahora trabajando de verdad.** Los 600s eran de cuando arrancaba sin cupo y moría rápido: servían de corte de pérdidas, no de presupuesto. Con cerebras propio no le alcanzan para leer verbo.py, decidir y editar. Van a 2400s, que entran holgados en los 180 min del workflow.
- La sección del mutador salió VACÍA, que es la peor evidencia posible justo en el caso a diagnosticar: el stdout del hijo estaba bufferado y matarlo se llevó todo lo que no había flusheado. Se lanza con `python -u`. Verificado: sin `-u` se rescata `''`, con `-u` se rescatan las líneas.

## 2026-08-17 · SIN MUTACIÓN
- **Intento:** We'll fetch full content, then apply Python replace.{"ruta":"verbo.py","desde":1,"hasta":600}(large 

## 2026-08-18 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-19 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-20 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-21 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-22 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-23 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-24 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-25 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-26 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-27 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-28 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-29 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-30 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-08-31 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-01 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-02 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-03 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-04 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-05 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-06 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-07 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-08 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-09 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-10 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-11 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-12 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-13 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-14 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-15 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-16 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-17 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-18 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-19 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-20 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-21 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-22 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-23 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-24 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-25 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-26 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-27 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-28 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-29 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-09-30 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-01 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-02 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-03 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-04 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-05 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-06 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-07 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-08 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-09 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-10 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-11 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-12 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-13 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-14 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-15 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-16 · SIN MUTACIÓN
- **Intento:** sin explicación del mutador

## 2026-10-17 · FALLÓ EL MUTADOR
- **Intento:** exit 1: openai.APIStatusError: Error code: 402 - {'message': 'Payment required to access this resource. Visit your billing tab.', 'type': 'payment_required_error', 'par

## 2026-10-17 · FALLÓ EL MUTADOR
- **Intento:** exit 1: openai.APIStatusError: Error code: 413 - {'error': {'message': 'Request too large for model `openai/gpt-oss-120b` in organization `org_01hvytmbmnf5xt0qesbqps6av

## 2026-10-17 · FALLÓ EL MUTADOR
- **Intento:** exit 1: ERROR: ningún modelo de la cadena está disponible (sin key o rechazado por el proveedor; ver arriba).

## 2026-10-17 · DESCARTADA EN EL FILTRO
- **Intento:** Se incrementó **MAX_TURNOS** de 20 a 30 en el genoma para permitir más iteraciones del bucle agente  [no resolvió ninguna tarea que fallaba ni ahorró tokens]
- **Diff:**
```diff
diff --git a/verbo.py b/verbo.py
index ca418eb..b9bfe66 100644
--- a/verbo.py
+++ b/verbo.py
@@ -122,7 +122,7 @@ GENOMA = {
         "ejecutar": "Ejecuta un comando de shell en el directorio de trabajo y devuelve stdout+stderr y el código de salida.",
         "buscar": "Busca texto literal en los archivos de un directorio (recursivo) y devuelve coincidencias como archivo:línea. Útil para encontrar referencias antes de editar o renombrar.",
     },
-    "max_turnos": 20,                  # iteraciones del loop agéntico por pedido
+    "max_turnos": 30,                  # iteraciones del loop agéntico por pedido
     "max_salida_herramienta": 6000,    # chars que se devuelven al modelo por herramienta
     "max_contexto_chars": 60000,       # umbral para compactar historial
     "temperatura": 0.2,
```

## 2026-10-19 · DESCARTADA EN EL FILTRO
- **Intento:** Se añadió un mensaje predeterminado al campo **cierre** del genoma (`"cierre": "Verifica y corrige s [no resolvió ninguna tarea que fallaba ni ahorró tokens]
- **Medición:** aciertos 2/5 → 1/5 · tokens 23418 → 50400
- **Diff:**
```diff
diff --git a/verbo.py b/verbo.py
index bf9514a..6a2bb8c 100644
--- a/verbo.py
+++ b/verbo.py
@@ -133,7 +133,7 @@ GENOMA = {
     "temperatura": 0.2,
     # Si no está vacío, se le manda al modelo la primera vez que quiere dar la
     # tarea por terminada, y tiene una vuelta más para verificar o corregir.
-    "cierre": "",
+    "cierre": "Verifica y corrige si es necesario.",
 }
 # <<< GENOMA
```

## 2026-10-21 · DESCARTADA EN EL FILTRO
- **Intento:** Se aumentó `max_turnos` a 30 y se redujo `max_contexto_chars` a 40000 para permitir más iteraciones  [no resolvió ninguna tarea que fallaba ni ahorró tokens]
- **Medición:** aciertos 2/5 → 1/5 · tokens 11738 → 41892
- **Diff:**
```diff
diff --git a/verbo.py b/verbo.py
index bf9514a..bf9b065 100644
--- a/verbo.py
+++ b/verbo.py
@@ -127,9 +127,9 @@ GENOMA = {
         "ejecutar": "Ejecuta un comando de shell en el directorio de trabajo y devuelve stdout+stderr y el código de salida.",
         "buscar": "Busca texto literal en los archivos de un directorio (recursivo) y devuelve coincidencias como archivo:línea. Útil para encontrar referencias antes de editar o renombrar.",
     },
-    "max_turnos": 20,                  # iteraciones del loop agéntico por pedido
+    "max_turnos": 30,                  # iteraciones del loop agéntico por pedido
     "max_salida_herramienta": 6000,    # chars que se devuelven al modelo por herramienta
-    "max_contexto_chars": 60000,       # umbral para compactar historial
+    "max_contexto_chars": 40000,       # umbral para compactar historial
     "temperatura": 0.2,
     # Si no está
```

## 2026-10-23 · DESCARTADA EN EL FILTRO
- **Intento:** Se redujo **max_contexto_chars** de 60000 a 54000 para limitar la cantidad de historial que se manti [no resolvió ninguna tarea que fallaba ni ahorró tokens]
- **Medición:** aciertos 1/5 → 1/5 · tokens 25050 → 33244
- **Diff:**
```diff
diff --git a/verbo.py b/verbo.py
index bf9514a..cc3628b 100644
--- a/verbo.py
+++ b/verbo.py
@@ -129,7 +129,7 @@ GENOMA = {
     },
     "max_turnos": 20,                  # iteraciones del loop agéntico por pedido
     "max_salida_herramienta": 6000,    # chars que se devuelven al modelo por herramienta
-    "max_contexto_chars": 60000,       # umbral para compactar historial
+    "max_contexto_chars": 54000,       # umbral para compactar historial
     "temperatura": 0.2,
     # Si no está vacío, se le manda al modelo la primera vez que quiere dar la
     # tarea por terminada, y tiene una vuelta más para verificar o corregir.
```

## 2026-10-24 · DESCARTADA EN EL FILTRO
- **Intento:** Se redujo `max_contexto_chars` a 50000 para limitar el historial y ahorrar más del 10 % de tokens, m [no resolvió ninguna tarea que fallaba ni ahorró tokens]
- **Medición:** aciertos 1/5 → 1/5 · tokens 8759 → 9725
- **Diff:**
```diff
diff --git a/verbo.py b/verbo.py
index bf9514a..b738c96 100644
--- a/verbo.py
+++ b/verbo.py
@@ -129,7 +129,7 @@ GENOMA = {
     },
     "max_turnos": 20,                  # iteraciones del loop agéntico por pedido
     "max_salida_herramienta": 6000,    # chars que se devuelven al modelo por herramienta
-    "max_contexto_chars": 60000,       # umbral para compactar historial
+    "max_contexto_chars": 50000,       # umbral para compactar historial
     "temperatura": 0.2,
     # Si no está vacío, se le manda al modelo la primera vez que quiere dar la
     # tarea por terminada, y tiene una vuelta más para verificar o corregir.
```

## 2026-10-24 · SIN MUTACIÓN (timeout del mutador)
- **Intento:** sin explicación del mutador

## 2026-10-24 · SIN MUTACIÓN (timeout del mutador)
- **Intento:** sin explicación del mutador

## 2026-10-24 · SIN MUTACIÓN (timeout del mutador)
- **Intento:** Voy a analizar las fallas. La mayoría son `ModuleNotFoundError: No module named 'solucion'` — el age

## 2026-10-25 · SIN MUTACIÓN (timeout del mutador)
- **Intento:** sin explicación del mutador

## 2026-10-25 · REVERTIDA (no superó al baseline)
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [ganó 0 pares y perdió 1 (p=1.00, hace falta ≤0.05)]
- **Zonas:** GENOMA:temperatura, MAX_CONTEXTO_CHARS, compactar, ejecutar_herramienta
- **Medición:** aciertos 9/13 → 8/13 · tokens 163142 → 188910
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -136,4 +136,5 @@
     "max_salida_herramienta": 6000,    # chars que se devuelven al modelo por herramienta
     "max_contexto_chars": 60000,       # umbral para compactar historial
+    "max_resultado_herramienta": 4000, # chars que se devuelven al modelo por herramienta
     "temperatura": 0.2,
     # Si no está vacío, se le manda al modelo la primera vez que quiere dar la
@@ -144,4 +145,5 @@
 
 MAX_SALIDA_HERRAMIENTA = GENOMA["max_salida_herramienta"]
+MAX_RESULTADO_HERRAMIENTA = GENOMA.get("max_resultado_herramienta", MAX_SALIDA_HERRAMIENTA)
 MAX_CONTEXTO_CHARS = GENOMA["max_contexto_chars"]
 MAX_TURNOS = GENOMA["max_turnos"]
@@ -275,10 +277,10 @@
             texto = "\n".join(f"{i}\t{l}" for i, l in
                               enumerate(lineas[desde - 1:hasta], desde))
-            if len(texto) <= MAX_SALIDA_HERRAMIENTA:
+            if len(text
```

## 2026-10-26 · DESCARTADA EN EL FILTRO
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [ganó 0 pares y perdió 0, sin ahorro claro (39594 contra 14520 tokens)]
- **Zonas:** compactar
- **Medición:** aciertos 1/5 → 1/5 · tokens 14520 → 39594
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,11 +384,17 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos.
+    Ahora descarta *todos* los resultados de herramientas anteriores al último bloque reciente,
+    no solo los que superan 200 caracteres. Esto reduce drásticamente el contexto y evita
+    sobrecargar el límite de tokens.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
-            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
+    # Mantener los últimos 6 mensajes (incluye intera
```

## 2026-10-26 · REVERTIDA (no superó al baseline)
- **Intento:** Se modificó la función **compactar** para que, cuando el historial supera el límite de tokens, elimi [ganó 0 pares y perdió 1 (p=1.00, hace falta ≤0.05)]
- **Zonas:** compactar
- **Medición:** aciertos 10/13 → 9/13 · tokens 209053 → 203592
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,10 +384,14 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos.
+    Ahora descarta *todos* los resultados de herramientas anteriores al último bloque reciente,
+    sin importar su longitud, para reducir drásticamente el contexto y evitar sobrecargar el límite de tokens.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
+    # Mantener los últimos 6 mensajes (incluye interacciones y resultados recientes)
+    for m in mensajes[:-6]:
+        if m.get("role") == "tool":
  
```

## 2026-10-27 · REVERTIDA (no superó al baseline)
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [ganó 0 pares y perdió 1 (p=1.00, hace falta ≤0.05)]
- **Zonas:** compactar
- **Medición:** aciertos 9/13 → 8/13 · tokens 272005 → 216695
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,14 +384,22 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Si el historial supera el límite, descarta contenido antiguo para ahorrar contexto.
+    Mantiene los últimos 12 mensajes sin cambios; los anteriores se reemplazan por un marcador.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
-            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
-            total = sum(len(str(x.get("content") or "")) for x in mensajes)
-            if total <= MAX_CONTEXTO_CHARS:
-                break
+    # Mantener los últimos 12 mens
```

## 2026-10-28 · REVERTIDA (no superó al baseline)
- **Intento:** Se mejoró la función **compactar** para que, cuando el historial supera el límite de tokens, descart [ganó 0 pares y perdió 3 (p=1.00, hace falta ≤0.05)]
- **Zonas:** compactar
- **Medición:** aciertos 19/26 → 16/26 · tokens 252283 → 312264
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,11 +384,15 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Si el historial supera el límite, descarta contenidos antiguos para ahorrar contexto.
+    Preserva los últimos 12 mensajes y cualquier mensaje de rol "system"; los demás se reemplazan por un marcador.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
-            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
+    preservar = 12
+    # Conservar los últimos 'preservar' mensajes y todos los de rol 'system'
+    for m in mensajes[:-preservar]:
+        if m.get("role"
```

## 2026-10-29 · DESCARTADA EN EL FILTRO
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [ganó 0 pares y perdió 0, sin ahorro claro (36444 contra 23383 tokens)]
- **Zonas:** compactar
- **Medición:** aciertos 1/4 → 1/4 · tokens 23383 → 36444
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,4 +384,8 @@
 
 def compactar(mensajes):
+    """Si el historial supera el límite, descarta contenido antiguo para ahorrar contexto.
+    Conserva los últimos 12 mensajes y cualquier mensaje de rol "system"; los demás se reemplazan
+    por un marcador genérico. Esto reduce drásticamente el número de tokens enviados al modelo.
+    """
     """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
```

## 2026-10-29 · DESCARTADA EN EL FILTRO
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [ganó 0 pares y perdió 0, sin ahorro claro (80724 contra 94509 tokens)]
- **Zonas:** compactar
- **Medición:** aciertos 1/4 → 1/4 · tokens 94509 → 80724
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,14 +384,26 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Reduce el historial cuando supera MAX_CONTEXTO_CHARS.
+    Conserva todos los mensajes de rol "system" y los últimos 12 mensajes.
+    Los mensajes más antiguos se reemplazan por un marcador genérico para ahorrar tokens.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
-            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
-            total = sum(len(str(x.get("content") or "")) for x in mensajes)
-            if total <= MAX_CONTEXTO_CHARS:
-                b
```

## 2026-10-29 · SIN TIEMPO PARA MEDIR
- **Intento:** [groq/openai/gpt-oss-20b rechazó la llamada (413); probando el siguiente] [pasó el filtro; la suite no entró]
- **Zonas:** compactar, módulo
- **Medición:** aciertos 1/4 → 1/4 · tokens 70568 → 22856
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,14 +384,22 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Reduce el historial cuando supera MAX_CONTEXTO_CHARS.
+    Conserva los mensajes de rol "system" y los últimos 12 mensajes.
+    Los mensajes más antiguos se eliminan completamente para ahorrar tokens.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
-            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
-            total = sum(len(str(x.get("content") or "")) for x in mensajes)
-            if total <= MAX_CONTEXTO_CHARS:
+    # Mantener los últimos 12 mensaj
```

## 2026-10-30 · REVERTIDA (no superó al baseline)
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [ganó 1 pares y perdió 3 (p=0.94, hace falta ≤0.05)]
- **Zonas:** HERRAMIENTAS, compactar
- **Medición:** aciertos 16/26 → 14/26 · tokens 290813 → 231635
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -152,7 +152,7 @@
         "description": GENOMA["herramientas"]["leer"],
         "parameters": {"type": "object", "properties": {
-            "ruta": {"type": "string", "description": "Ruta del archivo, relativa o absoluta"},
-            "desde": {"type": "integer", "description": "Opcional: primera línea a leer (1 = principio)"},
-            "hasta": {"type": "integer", "description": "Opcional: última línea a leer"}},
+            "ruta": {"type": "string", "description": "Ruta del archivo"},
+            "desde": {"type": "integer", "description": "Opcional: primera línea (1 = inicio)"},
+            "hasta": {"type": "integer", "description": "Opcional: última línea"}},
             "required": ["ruta"]}}},
     {"type": "function", "function": {
@@ -182,6 +182,6 @@
         "parameters": {"type": "object", "properties": {
             "texto": {"
```

## 2026-10-31 · DESCARTADA EN EL FILTRO
- **Intento:** Se reemplazó la función **compactar** por una versión que, cuando el historial supera `MAX_CONTEXTO_ [ganó 0 pares y perdió 1, sin ahorro claro (27661 contra 48624 tokens)]
- **Zonas:** compactar, módulo
- **Medición:** aciertos 2/5 → 1/5 · tokens 48624 → 27661
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,14 +384,31 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Reduce el historial cuando supera MAX_CONTEXTO_CHARS.
+    Conserva los mensajes de rol "system" y los últimos 12 mensajes.
+    Los mensajes más antiguos se eliminan completamente para ahorrar tokens.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
-            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
-            total = sum(len(str(x.get("content") or "")) for x in mensajes)
-            if total <= MAX_CONTEXTO_CHARS:
+    # Mantener siempre los mensajes 
```

## 2026-10-31 · FALLÓ EL MUTADOR
- **Intento:** exit 1: ERROR: todos los modelos de la cadena agotaron su límite de tasa y el próximo cupo tarda 9 min. Esperá o agregá otro proveedor con --fallback.
- **Zonas:** compactar
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,14 +384,29 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Reduce el historial cuando supera MAX_CONTEXTO_CHARS.
+    Conserva los mensajes de rol "system" y los últimos 12 mensajes.
+    Los mensajes más antiguos se reemplazan por un marcador o se descartan.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
-            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
-            total = sum(len(str(x.get("content") or "")) for x in mensajes)
-            if total <= MAX_CONTEXTO_CHARS:
-                break
+    # Índice a
```

## 2026-10-31 · FALLÓ EL MUTADOR
- **Intento:** exit 1: ERROR: todos los modelos de la cadena agotaron su límite de tasa y el próximo cupo tarda 23 min. Esperá o agregá otro proveedor con --fallback.

## 2026-10-31 · FALLÓ EL MUTADOR
- **Intento:** exit 1: ERROR: todos los modelos de la cadena agotaron su límite de tasa y el próximo cupo tarda 32 min. Esperá o agregá otro proveedor con --fallback.

## 2026-11-01 · DESCARTADA EN EL FILTRO
- **Intento:** Se mejoró la función **compactar** para que, cuando el historial supera `MAX_CONTEXTO_CHARS`, conser [ganó 0 pares y perdió 0, sin ahorro claro (51454 contra 25203 tokens)]
- **Zonas:** compactar
- **Medición:** aciertos 1/5 → 1/5 · tokens 25203 → 51454
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,14 +384,20 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Reduce el historial cuando supera MAX_CONTEXTO_CHARS.
+    Conserva los mensajes de rol "system" y los últimos 12 mensajes de cualquier tipo.
+    Los mensajes más antiguos se eliminan completamente para ahorrar tokens.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
-            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
-            total = sum(len(str(x.get("content") or "")) for x in mensajes)
-            if total <= MAX_CONTEXTO_CHARS:
-                br
```

## 2026-11-01 · DESCARTADA EN EL FILTRO
- **Intento:** Se mejoró `compactar` para que, cuando el historial supera `MAX_CONTEXTO_CHARS`, conserve los mensaj [ganó 0 pares y perdió 0, sin ahorro claro (60854 contra 59341 tokens)]
- **Zonas:** compactar
- **Medición:** aciertos 1/5 → 1/5 · tokens 59341 → 60854
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,14 +384,28 @@
 
 def compactar(mensajes):
-    """Si el historial pesa demasiado, vacía los resultados de herramientas más viejos."""
+    """Reduce el historial cuando supera MAX_CONTEXTO_CHARS.
+    Conserva los mensajes de rol "system" y los últimos 12 mensajes de cualquier tipo.
+    Los mensajes más antiguos se reemplazan por un marcador para ahorrar tokens.
+    """
     total = sum(len(str(m.get("content") or "")) for m in mensajes)
     if total <= MAX_CONTEXTO_CHARS:
         return
-    for m in mensajes[:-8]:  # nunca tocar los últimos mensajes
-        if m.get("role") == "tool" and len(str(m.get("content") or "")) > 200:
-            m["content"] = "[resultado antiguo descartado para ahorrar contexto]"
-            total = sum(len(str(x.get("content") or "")) for x in mensajes)
-            if total <= MAX_CONTEXTO_CHARS:
-              
```

## 2026-11-01 · SIN TIEMPO PARA MEDIR
- **Intento:** (sin respuesta) [pasó el filtro; la suite no entró]
- **Zonas:** compactar
- **Medición:** aciertos 1/5 → 2/5 · tokens 79577 → 78165
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -384,4 +384,21 @@
 
 def compactar(mensajes):
+    """Reduce el historial cuando supera MAX_CONTEXTO_CHARS.
+    Conserva los mensajes de rol "system" y los últimos 8 mensajes.
+    Los mensajes más antiguos se reemplazan por un marcador para ahorrar tokens.
+    """
+    total = sum(len(str(m.get("content") or "")) for m in mensajes)
+    if total <= MAX_CONTEXTO_CHARS:
+        return
+    # Reemplazar mensajes antiguos (excepto system) por marcador
+    for i, m in enumerate(mensajes[:-8]):
+        if m.get("role") != "system":
+            m["content"] = "[historial truncado]"
+    # Recalcular
+    total = sum(len(str(m.get("content") or "")) for m in mensajes)
+    if total > MAX_CONTEXTO_CHARS:
+        # Si sigue sin caber, eliminar mensajes antiguos por completo
+        mensajes[:] = [m for m in mensajes if m.get("role") == "system" or m in men
```

## 2026-11-02 · REPETIDA
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [cortado por tiempo] [solo toca zonas ya agotadas (compactar)]
- **Zonas:** compactar

## 2026-11-03 · REVERTIDA (rompe el contrato)
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [cortado por tiempo] [agrega '\brequests\b' (vigilado: tests, red, entorno o código dinámico)]
- **Zonas:** turno
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -524,4 +524,39 @@
                 print(f"  [tool call inválido del modelo; corrigiendo... ({motivo})]")
                 time.sleep(2)
+                # Eliminar el mensaje del asistente que contenía la llamada inválida
+                if mensajes and mensajes[-1].get("role") == "assistant":
+                    mensajes.pop()
+                nombres = [h["function"]["name"]
+                           for h in estado.get("herramientas", HERRAMIENTAS)]
+                mensajes.append({"role": "user", "content":
+                    "[sistema] Tu llamada a herramienta fue inválida. Las únicas herramientas "
+                    f"disponibles son: {', '.join(nombres)}. Reintentá."})
+                continue
+            raise
+        msg = respuesta.choices[0].message
+
+        if not msg.tool_calls:
+            mensajes.append({"role": "assistant
```

## 2026-11-04 · DESCARTADA EN EL FILTRO
- **Intento:** **Resumen:** Se arregló la herramienta `buscar` para aceptar archivos como parámetro `ruta` (usa su  [ganó 1 pares y perdió 1]
- **Zonas:** ejecutar_herramienta
- **Medición:** aciertos 4/7 → 4/7 · tokens 112343 → 82595
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -336,4 +336,6 @@
             ext = args.get("extension") or ""
             base = Path(args.get("ruta") or ".")
+            if base.is_file():
+                base = base.parent
             if not base.is_dir():
                 return f"ERROR: no existe el directorio {base}"
```

## 2026-11-05 · SIN CUPO PARA MEDIR
- **Intento:** Ahora se valida y re-serializa cada `arguments` antes de agregarlo al historial: si es JSON válido s [suite: 69% de pares válidos]
- **Zonas:** turno
- **Medición:** aciertos 8/9 → 8/9 · tokens 63471 → 64812
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -546,11 +546,21 @@
             print(f"  {msg.content.strip()[:300]}")
 
+        # Sanitizar tool_calls: el modelo a veces devuelve JSON inválido en arguments.
+        # Si lo guardamos tal cual, la próxima llamada a la API falla con 400.
+        tool_calls_sanitizados = []
+        for tc in msg.tool_calls:
+            try:
+                args = json.loads(tc.function.arguments or "{}")
+                args_json = json.dumps(args, ensure_ascii=False)
+            except json.JSONDecodeError:
+                args_json = "{}"
+            tool_calls_sanitizados.append({
+                "id": tc.id, "type": "function",
+                "function": {"name": tc.function.name, "arguments": args_json},
+            })
         mensajes.append({
             "role": "assistant",
             "content": msg.content or "",
-            "tool_calls": [{
-
```

## 2026-11-05 · SIN CUPO PARA MUTAR
- **Intento:** exit 1: ERROR: todos los modelos de la cadena agotaron su límite de tasa y el próximo cupo tarda 276 min. Esperá o agregá otro proveedor con --fallback.
- **Zonas:** ejecutar_herramienta
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -336,7 +336,10 @@
             ext = args.get("extension") or ""
             base = Path(args.get("ruta") or ".")
+            if base.is_file():
+                base = base.parent
             if not base.is_dir():
                 return f"ERROR: no existe el directorio {base}"
             coincidencias = []
+
             for archivo in sorted(base.rglob("*")):
                 if set(archivo.parts) & {".git", "__pycache__", "node_modules", ".venv", "venv"}:
```

## 2026-11-06 · SIN CUPO PARA MEDIR
- **Intento:** " [suite: 54% de pares válidos]
- **Zonas:** ejecutar_herramienta
- **Medición:** aciertos 12/14 → 14/14 · tokens 201244 → 166650
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -290,4 +290,14 @@
         if nombre == "escribir":
             ruta = Path(args["ruta"])
+            # Si el archivo ya existe y su contenido es idéntico, no lo sobrescribimos
+            if ruta.is_file() and ruta.read_text(encoding="utf-8", errors="replace") == args["contenido"]:
+                return f"OK: ya está escrito {ruta} ({len(args['contenido'])} caracteres)"
+            # Si es código Python, validar sintaxis antes de sobrescribir
+            if ruta.suffix == ".py":
+                try:
+                    compile(args["contenido"], str(ruta), "exec")
+                except SyntaxError as e:
+                    return (f"ERROR: el contenido a escribir tiene error de sintaxis "
+                            f"(línea {e.lineno}: {e.msg}). NO se aplicó.")
             ruta.parent.mkdir(parents=True, exist_ok=True)
             ruta.wr
```

## 2026-11-07 · DESCARTADA EN EL FILTRO
- **Intento:** 2. **Detección de bucles de herramienta repetida (líneas 515, 566-570)**: Agrega `last_tool_call` qu [ganó 0 pares y perdió 1]
- **Zonas:** ejecutar_herramienta, turno
- **Medición:** aciertos 4/7 → 3/7 · tokens 101307 → 57413
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -323,5 +323,9 @@
                     nuevos = _cadaveres(nuevo)
                     if len(nuevos) > len(_cadaveres(contenido)):
-                        return (f"ERROR: esta edición dejaría {nuevos[0]}. NO se "
+                        if nuevos:
+                            detalle = nuevos[0]
+                        else:
+                            detalle = 'código muerto'
+                        return (f"ERROR: esta edición dejaría {detalle}. NO se "
                                 "aplicó. Probablemente insertaste la versión nueva "
                                 "sin borrar la vieja: incluí el bloque viejo "
@@ -509,4 +513,5 @@
     """Un pedido del usuario: itera hasta que el modelo deja de pedir herramientas."""
     cierre_pendiente = bool(GENOMA["cierre"])
+    last_tool_call = None
     for _ in range(MAX_TURNOS):
         if LIMITE
```

## 2026-11-07 · SIN CUPO PARA MEDIR
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [suite: 31% de pares válidos]
- **Zonas:** turno
- **Medición:** aciertos 4/4 → 4/4 · tokens 8834 → 12872
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -524,4 +524,20 @@
                 print(f"  [tool call inválido del modelo; corrigiendo... ({motivo})]")
                 time.sleep(2)
+                # Sanitizar tool_calls ya presentes en el historial (asistente
+                # previo) para que el próximo intento no falle por JSON inválido.
+                for m in mensajes:
+                    if m.get("role") == "assistant" and m.get("tool_calls"):
+                        tool_calls_sanitizados = []
+                        for tc in m["tool_calls"]:
+                            try:
+                                args = json.loads(tc["function"]["arguments"] or "{}")
+                                args_json = json.dumps(args, ensure_ascii=False)
+                            except json.JSONDecodeError:
+                                args_json = "{}"
+                            tool_ca
```

## 2026-11-08 · DESCARTADA EN EL FILTRO
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [ganó 0 pares y perdió 1]
- **Zonas:** turno
- **Medición:** aciertos 4/7 → 3/7 · tokens 65020 → 68951
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -509,4 +509,5 @@
     """Un pedido del usuario: itera hasta que el modelo deja de pedir herramientas."""
     cierre_pendiente = bool(GENOMA["cierre"])
+    invalid_attempts = 0  # contador de intentos de tool call inválidos en este turno
     for _ in range(MAX_TURNOS):
         if LIMITE and time.time() > LIMITE:
@@ -517,15 +518,20 @@
         except BadRequestError as e:
             # Algunos proveedores (Groq) devuelven 400 si el modelo alucina una
-            # herramienta inexistente o genera un tool call malformado;
-            # se lo devolvemos para que se corrija. El sleep evita ráfagas de
-            # 400+429 retroalimentándose contra el límite de requests/minuto.
+            # herramienta inexistente o genera un tool call malformado; manejamos
+            # el error para evitar bucles infinitos.
             if "tool" in str(e).lower() 
```

## 2026-11-08 · SIN CUPO PARA MEDIR
- **Intento:** La edición se aplicó correctamente. La nueva regla 10 en el genoma ataca directamente la causa raíz  [suite: 15% de pares válidos]
- **Zonas:** GENOMA:reglas
- **Medición:** aciertos 2/2 → 2/2 · tokens 4267 → 4055
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -128,4 +128,5 @@
         "Tras renombrar algo o cambiar una interfaz, usá 'buscar' para encontrar todas las referencias restantes antes de dar por terminado.",
         "Al reemplazar un bloque de código, incluí en 'buscar' el bloque viejo COMPLETO: si solo insertás la versión nueva, la vieja queda como código muerto.",
+        "No leas el mismo archivo dos veces seguidas sin hacer una edición o búsqueda en el medio; si necesitás más contexto, usá 'desde' y 'hasta'.",
     ],
     "herramientas": {
```

## 2026-11-10 · SIN CUPO PARA MEDIR
- **Intento:** Listo. El cambio activa el mecanismo de "cierre" existente (líneas 537-540) con un mensaje que ataca [suite: 62% de pares válidos]
- **Zonas:** GENOMA:cierre
- **Medición:** aciertos 14/16 → 13/16 · tokens 149737 → 274840
- **Diff:**
```diff
--- a/verbo.py
+++ b/verbo.py
@@ -142,5 +142,5 @@
     # Si no está vacío, se le manda al modelo la primera vez que quiere dar la
     # tarea por terminada, y tiene una vuelta más para verificar o corregir.
-    "cierre": "",
+    "cierre": "Antes de terminar: ejecutá los tests o verificá que tu solución funciona. No leas archivos que ya leíste; si necesitás más contexto, usá 'desde'/'hasta'. Las únicas herramientas válidas son: leer, escribir, editar, ejecutar, buscar. Si tu último tool call falló, corregilo ahora.",
 }
 # <<< GENOMA
```

## 2026-11-10 · REPETIDA
- **Intento:** [groq/qwen/qwen3.8-27b rechazó la llamada (413); probando el siguiente] [cortado por tiempo] [solo toca zonas ya agotadas (turno)]
- **Zonas:** turno

## 2026-11-11 · SIN MUTACIÓN
- **Intento:** (sin respuesta)

## 2026-11-11 · SIN MUTACIÓN
- **Intento:** (sin respuesta)
