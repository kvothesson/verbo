class Pedido:
    """Las líneas de un pedido son solo suyas."""

    def __init__(self, cliente, lineas=[]):
        self.cliente = cliente
        self.lineas = lineas

    def agregar(self, producto, cantidad):
        self.lineas.append((producto, cantidad))
