def valor_total(repo):
    return sum(p.precio * p.stock for p in repo.todos())


def agotados(repo):
    """Nombres de productos sin stock, en orden de alta."""
    return [p.nombre for p in repo.todos() if p.stock < 0]


def mas_valioso(repo):
    productos = repo.todos()
    if not productos:
        return None
    return max(productos, key=lambda p: p.precio * p.stock).nombre
