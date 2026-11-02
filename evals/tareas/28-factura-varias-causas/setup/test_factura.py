from descuentos import porcentaje_volumen
from factura import neto_linea, total
from pedido import Pedido

assert porcentaje_volumen(9) == 0
assert porcentaje_volumen(10) == 5
assert porcentaje_volumen(50) == 10

a = Pedido("ana")
a.agregar("tuerca", 1)
b = Pedido("beto")
assert b.lineas == []

assert neto_linea("tornillo", 10) == 1187

c = Pedido("carla")
c.agregar("tornillo", 10)
assert total(c) == 1436
print("todos los tests pasaron")
