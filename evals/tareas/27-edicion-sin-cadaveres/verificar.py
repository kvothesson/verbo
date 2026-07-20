import ast
import sys

sys.path.insert(0, ".")
from juego import Pieza, FORMAS

# 1. La rotación tiene que funcionar de verdad.
p = Pieza(FORMAS[0])
antes = str(p.imagen())
p.rotar()
assert str(p.imagen()) != antes, "rotar() no cambia la imagen (pieza I)"

p2 = Pieza(FORMAS[1])
imagenes = []
for _ in range(4):
    imagenes.append(str(p2.imagen()))
    p2.rotar()
assert len(set(imagenes)) == 4, \
    f"la pieza T debe tener 4 rotaciones distintas, tiene {len(set(imagenes))}"
assert str(p2.imagen()) == imagenes[0], "tras 4 rotaciones debe volver al origen"

# 2. El arreglo no puede dejar el archivo podrido: sin código inalcanzable
#    ni definiciones duplicadas (el modo de falla clásico es insertar la
#    versión nueva de una función sin borrar la vieja).
arbol = ast.parse(open("juego.py", encoding="utf-8").read())
for nodo in ast.walk(arbol):
    for attr in ("body", "orelse", "finalbody"):
        cuerpo = getattr(nodo, attr, None)
        if not isinstance(cuerpo, list):
            continue
        corta = False
        for stmt in cuerpo:
            assert not corta, f"código inalcanzable en línea {stmt.lineno}"
            if isinstance(stmt, (ast.Return, ast.Raise)):
                corta = True
        nombres = [s.name for s in cuerpo
                   if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert len(nombres) == len(set(nombres)), \
            f"definición duplicada: {sorted(n for n in nombres if nombres.count(n) > 1)}"

print("PASS")
