from repositorio import Repositorio
import reportes

repo = Repositorio()
repo.agregar("yerba 1kg", 8000, 12)
repo.agregar("bombilla", 4500, 2)
repo.agregar("termo acero", 60000, 3)

repo.descontar_stock("bombilla", 2)

print(f"valor total: {reportes.valor_total(repo)}")
print(f"agotados: {reportes.agotados(repo)}")
print(f"mas valioso: {reportes.mas_valioso(repo)}")
