from catalogo import precio
from descuentos import porcentaje_volumen

IVA = 21


def redondear(valor):
    """Al centavo más cercano; las mitades redondean hacia arriba (62.5 -> 63)."""
    return round(valor)


def neto_linea(producto, cantidad):
    """Precio de la línea menos su descuento por volumen, en centavos."""
    bruto = precio(producto) * cantidad
    descuento = redondear(bruto * porcentaje_volumen(cantidad) / 100)
    return bruto - descuento


def total(pedido):
    """Suma de los netos de las líneas más el IVA. El IVA se calcula una sola
    vez, sobre el neto de todo el pedido, y se redondea al final."""
    neto = 0
    iva = 0
    for producto, cantidad in pedido.lineas:
        neto += neto_linea(producto, cantidad)
        iva += redondear(precio(producto) * cantidad * IVA / 100)
    return neto + iva
