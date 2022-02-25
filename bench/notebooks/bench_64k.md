---
jupyter:
  jupytext:
    formats: ipynb,md
    text_representation:
      extension: .md
      format_name: markdown
      format_version: '1.3'
      jupytext_version: 1.13.7
  kernelspec:
    display_name: Python 3 (ipykernel)
    language: python
    name: python3
---

```python
# Latency test for input sizes = 64 KB.

from collections import defaultdict
import math
import random
import umash_bench
from exact_test import *
import plotly.express as px

```

```python
# Gather the raw data for the two revisions we want to compare
TEST = "WIP"  # Or an actual commit ref
BASELINE = "HEAD"  # Or any other commit ref
CFLAGS = None
CC = None
results = umash_bench.compare_inputs([1 << 16] * 1000,
                                     current=TEST,
                                     baseline=BASELINE,
                                     cflags=CFLAGS,
                                     cc=CC,
                                     min_count=1000000)

TEST, BASELINE = results.keys()  # Convert to the actual keys: HEAD etc. are normalised to SHAs

regrouped = dict()
for k, results in results.items():
    regrouped_results = defaultdict(list)
    regrouped[k] = regrouped_results
    for size, timings in results.items():
        regrouped_results[size] += timings

regrouped_keys = sorted(regrouped[TEST].keys())
```

```python
# Summarise the range of latencies (in RDTSC cycles) for the two revisions and input size classes
for label, values in regrouped.items():
    print(label)
    for i in regrouped_keys:
        total = len(values[i])
        kept = sum(x < 100000 for x in values[i])
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
                       nbins=max(test + baseline) // 5,
                       barmode="overlay",
                       opacity=0.5,
                       marginal="box")
    fig.update_xaxes(range=(4000, 12000))
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
