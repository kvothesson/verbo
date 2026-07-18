import sys
sys.path.insert(0, ".")
from procesar import procesar_ventas

registros = [
    {"producto": "yerba", "precio": 100, "cantidad": 2},       # válido: 200
    {"producto": "mate", "precio": 50, "cantidad": "3"},        # inválido: cantidad es string
    {"producto": "bombilla", "precio": -10, "cantidad": 1},     # inválido: precio negativo
    {"producto": "termo", "cantidad": 1},                       # inválido: falta precio
    {"producto": "azucar", "precio": 20},                        # inválido: falta cantidad
    {"producto": "pava", "precio": 300, "cantidad": 0},          # válido: 0 (cantidad 0 está OK)
    {"producto": "alfajor", "precio": 0, "cantidad": 5},         # inválido: precio 0
    {"producto": "gaseosa", "precio": 150, "cantidad": -2},      # inválido: cantidad negativa
    {"producto": "galletitas", "precio": 80.5, "cantidad": 3},   # válido: 241.5
]

total, invalidos = procesar_ventas(registros)

assert total == 441.5, f"total incorrecto: {total} (esperado 441.5)"
assert invalidos == ["mate", "bombilla", "termo", "azucar", "alfajor", "gaseosa"], \
    f"invalidos incorrecto: {invalidos}"

# Caso borde extra: lista vacía no debe romper
total_vacio, invalidos_vacio = procesar_ventas([])
assert total_vacio == 0, f"total con lista vacía debería ser 0, dio {total_vacio}"
assert invalidos_vacio == [], f"invalidos con lista vacía debería ser [], dio {invalidos_vacio}"

print("PASS")
