import subprocess, sys
r = subprocess.run([sys.executable, "saludo.py"], capture_output=True, text=True, timeout=30)
assert r.returncode == 0, f"saludo.py falló: {r.stderr}"
assert r.stdout.strip() == "hola austral", f"salida incorrecta: {r.stdout!r}"
print("PASS")
