from productos import Producto


class Repositorio:
    def __init__(self):
        self._items = []

    def agregar(self, nombre, precio, stock):
        self._items.append(Producto(nombre, precio, stock))

    def todos(self):
        return list(self._items)

    def buscar(self, nombre):
        for p in self._items:
            if p.nombre == nombre:
                return p
        return None

    def descontar_stock(self, nombre, cantidad):
        p = self.buscar(nombre)
        if p is None:
            raise KeyError(nombre)
        if cantidad > p.stock:
            raise ValueError(f"stock insuficiente de {nombre}")
        p.stock -= cantidad
