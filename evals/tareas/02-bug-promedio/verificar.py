import sys
sys.path.insert(0, ".")
from stats import promedio
assert promedio([10, 20, 30]) == 20, "promedio([10,20,30]) != 20"
assert promedio([2, 4, 6]) == 4, "promedio([2,4,6]) != 4"
assert promedio([5]) == 5, "promedio([5]) != 5"
print("PASS")
