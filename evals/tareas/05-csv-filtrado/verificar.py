from pathlib import Path
contenido = Path("caros.txt").read_text(encoding="utf-8").strip().splitlines()
contenido = [l.strip() for l in contenido if l.strip()]
assert contenido == ["mate imperial", "termo acero", "pava electrica"], \
    f"contenido incorrecto: {contenido}"
print("PASS")
