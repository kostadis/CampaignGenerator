"""Fake-endpoint check of run_pool: shared queue, slow box takes fewer items, errors surface."""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chunked_state as cs  # noqa: E402

clients = {"fast": 0.01, "slow": 0.05}  # the "client" is just its per-item latency


def fn(delay, item):
    time.sleep(delay)
    return item * 2


got = list(cs.run_pool(list(range(40)), fn, clients, 2))
assert sorted(r for _, _, r in got) == [i * 2 for i in range(40)], "every item exactly once"
per = Counter(ep for ep, _, _ in got)
print("items per endpoint:", dict(per))
assert per["fast"] > per["slow"], "the slow box should take fewer items"


def boom(delay, item):
    if item == 3:
        raise RuntimeError("endpoint down")
    return item


try:
    list(cs.run_pool(list(range(6)), boom, clients, 2))
    raise AssertionError("error was swallowed")
except RuntimeError as e:
    print("error surfaced:", e)
print("ok")
