---
jupyter:
  jupytext:
    formats: ipynb,md
    text_representation:
      extension: .md
      format_name: markdown
      format_version: '1.2'
      jupytext_version: 1.6.0
  kernelspec:
    display_name: Python 3
    language: python
    name: python3
---

```python
# Latency test for synthetic size distribution

from collections import defaultdict
import math
import random
import umash_bench
import umash_traces
from exact_test import *
import plotly.express as px
```

```python
INPUT_SIZES=[513] * 10000  # Worst case for I$ misses with an implementation that special cases <= 512 bytes

random.shuffle(INPUT_SIZES)

def size_bucket(size):
    return size
```

```python
# Gather the raw data for the two revisions we want to compare
TEST = "WIP"  # Or an actual commit ref
BASELINE = "HEAD"  # Or any other commit ref
CFLAGS = None
CC = None
FLUSH_LEVEL = 3  # 3: fully flush out the code out of cache
results = umash_bench.compare_inputs(INPUT_SIZES,
                                     current=TEST,
                                     baseline=BASELINE,
                                     cflags=CFLAGS,
                                     cc=CC,
                                     min_count=20000 * len(set(INPUT_SIZES)),
                                     options={'flush_code': FLUSH_LEVEL})

TEST, BASELINE = results.keys()  # Convert to the actual keys: HEAD etc. are normalised to SHAs

regrouped = dict()
for k, results in results.items():
    regrouped_results = defaultdict(list)
    regrouped[k] = regrouped_results
    for size, timings in results.items():
        regrouped_results[size_bucket(size)] += timings

regrouped_keys = sorted(regrouped[TEST].keys())
```

```python
# Summarise the range of latencies (in RDTSC cycles) for the two revisions and input size classes
for label, values in regrouped.items():
    print(label)
    for i in regrouped_keys:
        total = len(values[i])
        kept = sum(x < 100 for x in values[i])
        print("\t%s: %i %i %f (%i %i)" % (i, total, kept, kept / total, min(values[i]), max(values[i])))
```

```python
# Visualise the two latency distributions for each input size
for sz in regrouped_keys:
    test = list(regrouped[TEST][sz])
    baseline = list(regrouped[BASELINE][sz])
    random.shuffle(test)
    random.shuffle(baseline)
    test = test[:5000]
    baseline = baseline[:5000]
    fig = px.histogram(dict(Test=test, Baseline=baseline),
                       title="Latency for input size = %s" % sz,
                       histnorm='probability density',
                       nbins=max(test + baseline),
                       barmode="overlay",
                       opacity=0.5,
                       marginal="box")
    fig.update_xaxes(range=(0, 100 + min(test + baseline) + 50 * (sz // 100)))
    fig.show()
```

```python
# Run an exact permutation test for each input size to see if any difference is worth looking at.
stats = [(i,
          exact_test(a=regrouped[TEST][i][:20000],  # We don't need too too many data points
                     b=regrouped[BASELINE][i][:20000],
                     eps=1e-4,
                     statistics=[
                         mean("mean", .5e-3),
                         lte_prob("lte"),
                         q99("q99"),
                         q99("q99_sa", a_offset=5)  # Compare against q99 w/ A 5 cycles slower than B
                     ])
         ) for i in regrouped_keys]
```

```python
stats
```
