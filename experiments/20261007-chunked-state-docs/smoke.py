import argparse, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import campaignlib
from campaignlib import client_from_args, stream_api

print(campaignlib.__file__)
a = argparse.Namespace(backend="dgx", endpoint="http://192.168.1.147:8001/v1", model="qwen3.8-flash-next")
c = client_from_args(a)
t = time.time()
print(repr(stream_api(c, "You are terse.", "Reply with exactly: OK", "qwen3.8-flash-next", max_tokens=50, silent=True)), round(time.time() - t, 1))
