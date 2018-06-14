def mean(x):
  x = list(x)
  return sum(x) / len(x) if x else 0

def median(x):
  x = sorted(list(x))
  quot, rem = divmod(len(x), 2)
  if rem:
    return x[quot]
  return sum(x[quot - 1:quot + 1]) / 2.
