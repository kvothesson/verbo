import subprocess, sys
from pathlib import Path

calc = Path("calculadora.py").read_text(encoding="utf-8")
main = Path("main.py").read_text(encoding="utf-8")
assert "suma_nums" not in calc, "quedó suma_nums en calculadora.py"
assert "suma_nums" not in main, "quedó suma_nums en main.py"
assert "def sumar(" in calc, "no existe def sumar en calculadora.py"

r = subprocess.run([sys.executable, "main.py"], capture_output=True, text=True, timeout=30)
assert r.returncode == 0, f"main.py falló: {r.stderr}"
assert r.stdout.strip() == "total=15 diferencia=12", f"salida incorrecta: {r.stdout!r}"
print("PASS")
