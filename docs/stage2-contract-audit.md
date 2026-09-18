# T2.0 — Starter-code contract audit

Everything below is copied verbatim from the organiser's own files in this
repository. Nothing here is inferred, and nothing downstream in Stage 2 may
assume a shape that does not appear on this page.

Sources: `schemas.py` (organiser header intact, never edited), `study.py`.

---

## 1. `ReviewReport` — present in `schemas.py`

It exists. Stage 2 does **not** need a Cureva-defined wrapper type.

```python
class ReviewReport(BaseModel):
    cut: int
    protocol_version: int
    findings: list[Finding]
    escalations: list[EscalationOut]
    queries: list[QueryOut]
    deviations: list[Finding]
    trace: list[dict]
    tokens_used: int = 0
    duration_ms: int = 0
```

Three consequences the build documents did not anticipate:

* **`trace` is `list[dict]`, not `list[TraceEntry]`.** `TraceEntry` is a
  Cureva-owned model; it is dumped with `.model_dump(mode="json")` on the way
  into the report. The typed object is what gets written to the JSONL file.
* **`deviations` is `list[Finding]`.** TRD T2.7 offers "a Cureva-defined
  `Deviation` model if none exists there" — that branch is dead. A deviation is
  a `Finding` carrying the `protocol_version` it was checked against.
* **`tokens_used` and `duration_ms` default to 0**, so reporting an honest zero
  costs nothing and omitting them is never necessary.

### Supporting types it references

```python
class EscalationOut(BaseModel):
    id: str
    code: str
    usubjid: str | None
    site: str | None
    summary: str
    decision: str | None
    reason: str | None


class QueryOut(BaseModel):
    id: str
    usubjid: str
    domain: str
    seq: int | None
    text: str
    status: str
    response: str | None = None
```

`Finding` carries no `id` field. Stage 2 therefore derives a stable
`finding_id` from the organiser's own `Finding.fingerprint()`, which is
`f"{code}|{usubjid}|{site}|{first two evidence seqs}"`. Deriving it rather
than counting findings is what makes the id identical across two runs of the
same cut — the foundation of the idempotency requirement.

---

## 2. `study.escalate()` — present in `study.py`

```python
def escalate(self, code: str, usubjid_or_site: str) -> tuple[str, str]:
    """What the medical monitor says. APPROVED, REJECTED or CLARIFY.

    On CLARIFY you are expected to answer from your own data and resubmit;
    a resubmission is APPROVED."""
    hit = self._decisions["decisions"].get(f"{code}|{usubjid_or_site}")
    return tuple(hit) if hit else ("APPROVED", "Noted.")
```

* **Parameters:** exactly two positional strings — a `FindingCode` and a
  subject *or* site identifier. There is no evidence parameter; the monitor is
  keyed on `code|subject` alone.
* **Return:** `(decision, reason)`, synchronous. **No escalation id is
  returned**, so Stage 2 generates its own — deterministically, from the
  finding fingerprint, so it is stable across cycles.
* **Response literals:** `APPROVED`, `REJECTED`, `CLARIFY` — the casing in
  `cureva-stage2-overview.md` is correct. Confirmed against the real
  `monitor_decisions.json`, whose decision values are drawn from exactly these
  three.

### The consequence for `PENDING` — a genuine contradiction with the PRD

`escalate()` **always answers immediately.** There is no "no response" case:
an unknown `code|subject` key falls through to `("APPROVED", "Noted.")`. PRD
FR-12 and G4 ("an unanswered escalation stays `PENDING` forever, never
silently approved") therefore describe a state this call can never produce.

Resolved, per the builder's decision, in favour of what the starter code
actually models:

* The **graded path** uses `escalate()`'s real inline decision. An escalation
  raised inside `run_cycle()` is `APPROVED`, `REJECTED`, or routed through the
  `CLARIFY` resubmission path, in the same cycle.
* `PENDING` is a real state reached two ways: an escalation awaiting a human
  click on `/monitor`'s human-gate screen, and an `escalate()` call that raised
  an exception (NFR-2 — the finding stays tracked rather than being lost).
* A `PENDING` escalation is **never** advanced by the mere passage of a cycle.
  That half of FR-12 is implemented literally and is what T2.8 verifies.

The rejected alternative was to treat the `("APPROVED", "Noted.")` fallback as
silence. That invents a distinction the organiser's code does not make, and on
a hidden study — where most `code|subject` pairs will miss the decisions table
— it would leave nearly every escalation permanently `PENDING`.

---

## 3. `study.query_site()` — present in `study.py`

```python
def query_site(self, domain: str, usubjid: str, seq: Any) -> tuple[str, str]:
    """What the hospital says when you query a record."""
    key = f"{domain}|{usubjid}|{'' if seq in (None, '') else seq}"
    status, text = self._replies["replies"].get(key, self._replies["_default"])
    return status, text
```

* **Parameters:** exactly three — `domain`, `usubjid`, `seq`. It is keyed on
  the record, not on a field within it.
* **Return:** `(status, text)`, synchronous, and **no query id**, so Stage 2
  generates one the same way it does for escalations.

### The consequence for the memory key

TRD §6 specifies `queries_raised` entries as `"domain:usubjid:seq:field"`.
**There is no `field`.** `query_site()` has no such parameter and `RecordRef`
has no such attribute — a `RecordRef` is `(domain, usubjid, seq, document,
section)`. A key carrying a `field` component could only ever hold a constant
there, which would not change dedup behaviour but would misrepresent what is
being deduplicated.

Stage 2 keys `queries_raised` on `"domain:usubjid:seq"` — exactly the three
values `query_site()` itself keys on. This makes the dedup guarantee align
precisely with the call it is protecting: one query per record, ever.

---

## 4. `protocol_version_at()` — present on both `Study` and `StudyGraph`

```python
# study.py
def protocol_version_at(self, cut: int) -> int: ...
# stage1/atlas.py — StudyGraph, built in T1.20
def protocol_version_at(self, cut: int | None) -> int: ...
```

T2.7 requires Stage 1's. `COMPLIANCE` calls
`atlas.graph.protocol_version_at(cut)` — the version that already drives every
Stage 1 detector's protocol-dependent behaviour, so a deviation is tagged with
the same version the detector that produced it was reasoning under.

---

## 5. `FindingCode` — 17 values, not the 16 the build document predicts

```python
FindingCode = Literal[
    "HYS_LAW_CANDIDATE", "SAE_UNESCALATED", "SAE_MISCODED", "LAB_UNIT_MISMATCH",
    "DUPLICATE_SUBJECT", "VISIT_OUT_OF_WINDOW", "AE_BEFORE_FIRST_DOSE",
    "MISSING_EXPOSURE_RECORD", "INCLUSION_VIOLATION", "EXCLUSION_VIOLATION",
    "PROHIBITED_CONMED", "DOSING_ERROR", "IMPLAUSIBLE_SITE_PATTERN",
    "LATE_DATA_ENTRY", "LAB_UNIT_CORRUPTION", "DOCUMENT_TAMPERED", "NO_FINDING"]
```

§B.3 of the build instructions accounts for 16 across the three stages and says
to stop and flag a 17th. Flagged here: the 17th is **`NO_FINDING`**, a sentinel
for an honestly-empty answer rather than a detector any stage owns. No stage
assignment changes. The 11 + 1 + 4 split stands.

Stage 1's live detector registry was read directly and confirms the 11:

```
HYS_LAW_CANDIDATE, SAE_MISCODED, AE_BEFORE_FIRST_DOSE, DUPLICATE_SUBJECT,
VISIT_OUT_OF_WINDOW, INCLUSION_VIOLATION, EXCLUSION_VIOLATION,
PROHIBITED_CONMED, DOSING_ERROR, MISSING_EXPOSURE_RECORD, LAB_UNIT_MISMATCH
```

---

## 6. `Question` — two required fields the build document's example omits

```python
class Question(BaseModel):
    id: str
    kind: Literal["count", "lookup", "finding", "trap"]
    text: str
    params: dict[str, Any] = Field(default_factory=dict)
    cut: int | None = None
```

T2.3's prompt writes `Question(kind="finding", params={"code": code})`. That
raises `ValidationError`: `id` and `text` are required and have no defaults.
`DETECT` constructs the full object, and sets `cut` so the sweep is scoped to
the cycle's cut rather than to whatever cut the graph was last built at.

---

## 7. `Study` construction

```python
def __init__(self, data_dir: str | Path = "hackathon-data"):
    ...
    if not (self.root / "data").exists():
        raise SystemExit(f"{self.root}/data not found — pass --data <folder>")
```

`ReviewCrew(data_dir, atlas)` builds its own `Study(data_dir)` for the two
response channels (`escalate`, `query_site`) and nothing else. This does not
violate FR-1: FR-1 forbids re-deriving the *graph*, and every finding and every
value still comes through the `Atlas` that was passed in. `Study` is used only
as the organiser's monitor/site reply transport, which `Atlas` does not expose.
