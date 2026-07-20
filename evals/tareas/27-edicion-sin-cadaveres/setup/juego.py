FORMAS = [
    [[1, 1, 1, 1]],           # I
    [[1, 1, 1], [0, 1, 0]],   # T
]


class Pieza:
    def __init__(self, forma):
        self.forma = forma
        self.rotacion = 0

    def imagen(self):
        matriz = self.forma
        for _ in range(self.rotacion % 4):
            matriz = [list(fila) for fila in zip(*matriz[::-1])]
        return matriz

    def rotar(self):
        self.rotacion = (self.rotacion + 1) % len(self.forma)
        self.rotacion = (self.rotacion + 1) % len(self.forma)
