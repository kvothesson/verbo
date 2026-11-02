import sys

sys.path.insert(0, ".")
from solucion import leer_config


def igual(texto, esperado, regla):
    obtenido = leer_config(texto)
    assert obtenido == esperado, f"{regla}: {obtenido!r} != {esperado!r}"
    for seccion in esperado:
        for clave, valor in esperado[seccion].items():
            assert type(obtenido[seccion][clave]) is type(valor), f"{regla}: tipo de {seccion}.{clave}"


def falla(texto, regla, contiene=None):
    try:
        leer_config(texto)
    except ValueError as e:
        if contiene:
            assert contiene in str(e), f"{regla}: el mensaje no dice {contiene!r}: {e}"
        return
    raise AssertionError(f"{regla}: tenía que lanzar ValueError")


igual("", {}, "vacío")
igual("\n   \n# nada\n  ; tampoco\n", {}, "1: comentarios y blancos")
igual("a = x\n[s]\nb = y\n", {"general": {"a": "x"}, "s": {"b": "y"}}, "2: sección general")
igual("[s]\n", {"s": {}}, "2: sección vacía")
igual("[s]\na = 1\n[t]\nz = 2\n[s]\nb = 3\n", {"s": {"a": 1, "b": 3}, "t": {"z": 2}}, "2: sección repetida")
igual("[s]\n  CLAVE  =  a=b  \n", {"s": {"clave": "a=b"}}, "3: primer = y minúsculas")
igual("[s]\na = x\nA = y\n", {"s": {"a": "y"}}, "3: gana la última")
igual('[s]\na = "  hola # no es comentario "\n', {"s": {"a": "  hola # no es comentario "}}, "4: comillas")
igual("[s]\na = hola # comentario\nb = color#rojo\n", {"s": {"a": "hola", "b": "color#rojo"}}, "4: comentario inline")
igual("[s]\na =\n", {"s": {"a": ""}}, "4: valor vacío")
igual("[h : m]\nb = 2\n[m]\na = 1\nb = 9\n", {"h": {"a": 1, "b": 2}, "m": {"a": 1, "b": 9}}, "5: madre más abajo")
igual("[c:b]\n[b:a]\ny = 2\n[a]\nx = 1\n", {"a": {"x": 1}, "b": {"x": 1, "y": 2}, "c": {"x": 1, "y": 2}}, "5: en cadena")
igual("[s]\na = hola\nb = ${a} mundo\n", {"s": {"a": "hola", "b": "hola mundo"}}, "6: misma sección")
igual('[s]\na = hola\nb = "${a}!"\n', {"s": {"a": "hola", "b": "hola!"}}, "6: entre comillas")
igual("[o]\nv = uno\n[s]\na = ${o.v}\n", {"o": {"v": "uno"}, "s": {"a": "uno"}}, "6: otra sección")
igual("[s]\na = ${b}\nb = ${c}\nc = fin\n", {"s": {"a": "fin", "b": "fin", "c": "fin"}}, "6: encadenada")
igual("[m]\nhost = local\nurl = http://${host}\n[h : m]\nhost = prod\n",
      {"m": {"host": "local", "url": "http://local"}, "h": {"host": "prod", "url": "http://prod"}},
      "6: la heredada se resuelve en la hija")
igual("[s]\na = TRUE\nb = false\nc = -12\nd = +7\ne = 1.5\nf = truee\n",
      {"s": {"a": True, "b": False, "c": -12, "d": 7, "e": "1.5", "f": "truee"}}, "7: tipos")
igual('[s]\na = "true"\nb = "12"\n', {"s": {"a": "true", "b": "12"}}, "7: comillas quedan str")
igual('[s]\na = 80\nb = ${a}\nc = "${a}"\nd = ${a}${a}\ne = "12"\nf = ${e}\n',
      {"s": {"a": 80, "b": 80, "c": "80", "d": 8080, "e": "12", "f": 12}}, "7: se convierte después de resolver")
igual("[o]\nv = True\n[s]\na = ${o.v}\nb = x${o.v}\n", {"o": {"v": True}, "s": {"a": True, "b": "xTrue"}},
      "7: la referencia inserta el texto del valor")
falla("[s]\na = 1\nesto no vale\n", "8: línea inválida", "línea 3")
falla("[s\n", "8: sección sin cerrar", "línea 1")
falla("[h : nadie]\n", "8: madre inexistente")
falla("[a : b]\n[b : a]\n", "8: ciclo de herencia")
falla("[a : a]\n", "8: se hereda a sí misma")
falla("[s]\na = ${nada}\n", "8: referencia inexistente")
falla("[s]\na = ${o.b}\n", "8: sección inexistente")
falla("[s]\na = ${b}\nb = ${a}\n", "8: ciclo de referencias")
falla("[s]\na = ${a}\n", "8: se refiere a sí misma")
print("PASS")
