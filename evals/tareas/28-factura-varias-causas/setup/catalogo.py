PRECIOS = {"tornillo": 125, "tuerca": 80, "arandela": 35, "taladro": 45999}


def precio(producto):
    """Precio unitario en centavos."""
    return PRECIOS[producto]
