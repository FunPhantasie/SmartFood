import math
r=3.5E-2
B = lambda I, r: (4 * math.pi * 1e-7 * I) / (2 * math.pi * r)

B = lambda I, r: (1.2566e-6 * I) / (2 * math.pi * r)*2
print(B(150000,r))