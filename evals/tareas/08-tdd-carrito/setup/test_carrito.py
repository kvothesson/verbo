from carrito import Carrito

c = Carrito()
c.agregar("yerba", 1500, 2)
c.agregar("mate", 8000, 1)
assert c.total() == 11000

c.agregar("yerba", 1500, 1)
assert c.total() == 12500, "agregar un producto existente debe sumar cantidades"

c.quitar("mate")
assert c.total() == 4500

try:
    c.quitar("inexistente")
    assert False, "quitar algo inexistente debe lanzar KeyError"
except KeyError:
    pass

c2 = Carrito()
c2.agregar("termo", 20000, 1)
assert c2.total_con_descuento(10) == 18000
assert c2.total_con_descuento(0) == 20000

try:
    c2.total_con_descuento(150)
    assert False, "descuento fuera de 0-100 debe lanzar ValueError"
except ValueError:
    pass

try:
    c2.total_con_descuento(-5)
    assert False, "descuento negativo debe lanzar ValueError"
except ValueError:
    pass

print("todos los tests pasaron")
