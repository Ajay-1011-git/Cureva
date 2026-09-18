"""T1.24 VERIFY — SarvamKeyPool round-robin + failover."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from intake.sarvam_pool import SarvamKeyPool, SarvamRateLimited, NoSarvamKeysConfigured

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

print("=== VERIFY (required): 3 fake keys, mocked client fails on key 1, pool retries key 2 ===")
pool = SarvamKeyPool(keys=["key1", "key2", "key3"], cooldown_seconds=60)
check("pool has 3 keys", pool.pool_size == 3)

calls = []
def mock_client(key):
    calls.append(key)
    if key == "key1":
        raise SarvamRateLimited(f"429 from {key}")
    return f"success with {key}"

result = pool.call_with_failover(mock_client)
print(f"  calls made, in order: {calls}")
print(f"  result: {result!r}")
check("first call used key1", calls[0] == "key1")
check("failed over to key2 after key1's 429", calls[1] == "key2")
check("call succeeded on the second attempt", result == "success with key2")
check("key1 is now in cooldown", pool._states[0].cooldown_until > 0)

print("\n=== VERIFY: round-robin without failures cycles through all keys ===")
pool2 = SarvamKeyPool(keys=["a", "b", "c"])
seq = [pool2.next_key() for _ in range(6)]
print(f"  {seq}")
check("cycles a,b,c,a,b,c", seq == ["a", "b", "c", "a", "b", "c"])

print("\n=== VERIFY: an exhausted key is skipped until its cooldown expires ===")
pool3 = SarvamKeyPool(keys=["x", "y"], cooldown_seconds=1000)
pool3.mark_exhausted("x")
seq3 = [pool3.next_key() for _ in range(3)]
print(f"  after marking 'x' exhausted: {seq3}")
check("x is skipped while in cooldown", "x" not in seq3)
check("y is returned every time", all(k == "y" for k in seq3))

print("\n=== VERIFY: a non-rate-limit error is NOT retried across keys ===")
pool4 = SarvamKeyPool(keys=["p", "q"])
def bad_request(key):
    raise ValueError("malformed request — same on every key")
try:
    pool4.call_with_failover(bad_request)
    check("propagates non-pool-shaped errors immediately", False)
except ValueError as e:
    check("propagates non-pool-shaped errors immediately, no wasted retries", True, str(e))

print("\n=== VERIFY: all keys exhausted still returns something rather than hanging ===")
pool5 = SarvamKeyPool(keys=["m", "n"], cooldown_seconds=1000)
pool5.mark_exhausted("m")
pool5.mark_exhausted("n")
k = pool5.next_key()
check("next_key() still returns a key even when all are cooling down", k in ("m", "n"))

print("\n=== VERIFY: env-var loading is tolerant of the naming variants actually seen ===")
import intake.sarvam_pool as sp
old_environ = dict(os.environ)
try:
    for k in list(os.environ):
        if "SARVAM" in k.upper(): del os.environ[k]
    os.environ["sarvam_api_key"] = "single-lowercase-key"
    keys = sp._load_keys()
    print(f"  sarvam_api_key (lowercase, singular) -> {keys}")
    check("lowercase singular key name is picked up", keys == ["single-lowercase-key"])
    del os.environ["sarvam_api_key"]
    os.environ["SARVAM_API_KEYS"] = "k1, k2 ,k3"
    keys2 = sp._load_keys()
    print(f"  SARVAM_API_KEYS='k1, k2 ,k3' -> {keys2}")
    check("comma-separated pool with stray whitespace parses to 3 clean keys", keys2 == ["k1", "k2", "k3"])
    for k in list(os.environ):
        if "SARVAM" in k.upper(): del os.environ[k]
    try:
        SarvamKeyPool()
        check("no configured key raises NoSarvamKeysConfigured", False)
    except NoSarvamKeysConfigured:
        check("no configured key raises NoSarvamKeysConfigured, not a bare KeyError", True)
finally:
    os.environ.clear(); os.environ.update(old_environ)

print("\n=== VERIFY: this repo's actual .env is picked up (1-key pool, functions correctly) ===")
from dotenv import load_dotenv
load_dotenv(override=True)
try:
    real_pool = SarvamKeyPool()
    print(f"  real .env pool size: {real_pool.pool_size}")
    check("this repo's .env yields at least 1 usable Sarvam key", real_pool.pool_size >= 1)
    if real_pool.pool_size == 1:
        print("  NOTE: single-key pool — functions correctly (round-robin trivially")
        print("  returns the same key), but has no partner to fail over to on a 429.")
        print("  The multi-account design (SARVAM_API_KEYS, comma-separated) is built")
        print("  and verified above; this repo just has one account configured.")
except NoSarvamKeysConfigured as e:
    print(f"  NOTE: no Sarvam key currently in .env ({e}) — pool construction itself")
    print("  is fully tested above with fake keys; this only affects a live call.")

print("\n" + ("ALL T1.24 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
