import sys
sys.path.insert(0, ".")
from fizzbuzz import fizzbuzz
esperado = ["1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8", "Fizz", "Buzz",
            "11", "Fizz", "13", "14", "FizzBuzz"]
assert fizzbuzz(15) == esperado, f"fizzbuzz(15) incorrecto: {fizzbuzz(15)}"
assert fizzbuzz(1) == ["1"], "fizzbuzz(1) incorrecto"
print("PASS")
