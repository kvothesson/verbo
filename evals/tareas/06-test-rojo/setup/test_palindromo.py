from palindromo import es_palindromo

assert es_palindromo("neuquen") is True
assert es_palindromo("Neuquen") is True
assert es_palindromo("anita lava la tina") is True
assert es_palindromo("La ruta natural") is True
assert es_palindromo("buenos aires") is False
assert es_palindromo("") is True
print("todos los tests pasaron")
