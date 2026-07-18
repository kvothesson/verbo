import subprocess, sys
sys.path.insert(0, ".")

from repositorio import Repositorio
import reportes

repo = Repositorio()
repo.agregar("a", 100, 0)
repo.agregar("b", 100, 5)
repo.agregar("c", 100, 0)
assert reportes.agotados(repo) == ["a", "c"], f"agotados incorrecto: {reportes.agotados(repo)}"

# el resto del sistema no debe romperse
assert reportes.valor_total(repo) == 500
assert reportes.mas_valioso(repo) == "b"

r = subprocess.run([sys.executable, "main.py"], capture_output=True, text=True, timeout=30)
assert r.returncode == 0, f"main.py falló: {r.stderr}"
assert "bombilla" in r.stdout and "agotados: ['bombilla']" in r.stdout, \
    f"main.py no reporta bombilla como agotado: {r.stdout!r}"
print("PASS")
