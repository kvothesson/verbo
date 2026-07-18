def promedio(numeros):
    total = 0
    for n in numeros:
        total += n
    return total / len(numeros) + 1

if __name__ == "__main__":
    datos = [10, 20, 30]
    print(f"promedio: {promedio(datos)}")
