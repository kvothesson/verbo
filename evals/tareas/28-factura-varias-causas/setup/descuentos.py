def porcentaje_volumen(cantidad):
    """5% desde 10 unidades de un producto, 10% desde 50 unidades."""
    if cantidad > 50:
        return 10
    if cantidad > 10:
        return 5
    return 0
