"""Load the study from the data folder. A working starting point.

What this gives you: every file loaded, cut filtering, and the lookups for the
scripted site and monitor replies.

What it deliberately does NOT give you: parsing of dates, units and non-numeric
laboratory values. Those are the problem, not the plumbing. The TODOs at the
bottom mark where your work starts.

    python study.py --data hackathon-data        # prints what it loaded
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

DOMAINS = ("DM", "AE", "LB", "VS", "EX", "CM", "DS", "MH", "EG")
SEQ_COL = {"AE": "AESEQ", "LB": "LBSEQ", "VS": "VSSEQ", "EX": "EXSEQ",
           "CM": "CMSEQ", "DS": "DSSEQ", "MH": "MHSEQ", "EG": "EGSEQ"}


class Study:
    """Everything in the data folder, loaded once."""

    def __init__(self, data_dir: str | Path = "hackathon-data"):
        self.root = Path(data_dir)
        if not (self.root / "data").exists():
            raise SystemExit(f"{self.root}/data not found — pass --data <folder>")
        self.domains: dict[str, list[dict]] = {}
        for d in DOMAINS:
            self.domains[d] = self._read(self.root / "data" / f"{d}.csv")
        self.ranges = self._read(self.root / "data" / "reference_ranges.csv")
        self.corrections = self._read(self.root / "data" / "corrections.csv")
        self.cuts = self._read(self.root / "data" / "cuts.csv")
        self._replies = json.loads((self.root / "responses" / "site_replies.json").read_text())
        self._decisions = json.loads((self.root / "responses" / "monitor_decisions.json").read_text())
        self._docs: dict[str, str] = {}
        for f in (self.root / "documents").glob("*.md"):
            self._docs[f.stem] = f.read_text()

    @staticmethod
    def _read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        with path.open(newline="") as fh:
            return list(csv.DictReader(fh))

    # ----------------------------------------------------------- records
    def records(self, domain: str, cut: int | None = None, site: str | None = None,
                usubjid: str | None = None, visit: str | None = None) -> list[dict]:
        """Rows from one domain. `cut` filters to what was visible at that cut."""
        out = []
        for r in self.domains[domain.upper()]:
            if cut is not None and int(r.get("cut_available") or 1) > cut:
                continue
            if usubjid and r["USUBJID"] != usubjid:
                continue
            if site and not r["USUBJID"].startswith(f"042-{site}-"):
                continue
            if visit and r.get("VISIT") != visit:
                continue
            out.append(r)
        return out

    def subjects(self, cut: int | None = None) -> list[dict]:
        return self.records("DM", cut=cut)

    def sites(self) -> list[str]:
        return sorted({r["USUBJID"].split("-")[1] for r in self.domains["DM"]})

    def document(self, name: str) -> str:
        """e.g. 'protocol_v1', 'lab-manual', 'sap'. Re-read it when it changes."""
        if name not in self._docs:
            # the folder may have gained a file since we loaded
            f = self.root / "documents" / f"{name}.md"
            if f.exists():
                self._docs[name] = f.read_text()
        if name not in self._docs:
            raise KeyError(f"{name} — have: {sorted(self._docs)}")
        return self._docs[name]

    def reload_documents(self) -> list[str]:
        """Call this when the organisers announce a change."""
        before = set(self._docs)
        self._docs = {f.stem: f.read_text() for f in (self.root / "documents").glob("*.md")}
        return sorted(set(self._docs) - before)

    def protocol_version_at(self, cut: int) -> int:
        for r in self.cuts:
            if int(r["cut"]) == cut:
                return int(r["protocol_version"])
        return 1

    # ------------------------------------------- asking questions of the study
    def query_site(self, domain: str, usubjid: str, seq: Any) -> tuple[str, str]:
        """What the hospital says when you query a record."""
        key = f"{domain}|{usubjid}|{'' if seq in (None, '') else seq}"
        status, text = self._replies["replies"].get(key, self._replies["_default"])
        return status, text

    def escalate(self, code: str, usubjid_or_site: str) -> tuple[str, str]:
        """What the medical monitor says. APPROVED, REJECTED or CLARIFY.

        On CLARIFY you are expected to answer from your own data and resubmit;
        a resubmission is APPROVED."""
        hit = self._decisions["decisions"].get(f"{code}|{usubjid_or_site}")
        return tuple(hit) if hit else ("APPROVED", "Noted.")

    def summary(self) -> dict:
        return {d: len(v) for d, v in self.domains.items()} | {
            "reference_ranges": len(self.ranges), "corrections": len(self.corrections),
            "documents": sorted(self._docs)}


# ===================================================================== TODO
# Everything below is a stub. This is where Problem 1 is won or lost.

def parse_date(value: Any):
    """TODO: the study uses more than one date format. Return a date object, or
    None when the value is missing. Do not assume ISO."""
    raise NotImplementedError


def to_number(value: Any) -> float | None:
    """TODO: laboratory values are not always numbers.
    '<5' means below the detection limit — which is NOT zero.
    'ND' means not done. '12,4' is a decimal comma. '' is missing.
    Return a float, or None when there is no usable number."""
    raise NotImplementedError


def standardise_lab(testcd: str, value: Any, unit: str | None, ranges: list[dict]):
    """TODO: the most important function you will write today.

    Not every site reports in the central laboratory's unit. Use `ranges` — which
    carries a LAB column — to work out which range applies, and convert where
    needed, BEFORE comparing anything to anything.

    Return (value_in_central_unit, central_unit, was_converted)."""
    raise NotImplementedError


# ------------------------------------------------------------------ check
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="hackathon-data")
    a = ap.parse_args()
    s = Study(a.data)
    print(f"loaded {a.data}")
    for k, v in s.summary().items():
        print(f"  {k:<18} {v}")
    labs = {r["LAB"] for r in s.ranges}
    print(f"\n  laboratories in reference_ranges.csv: {sorted(labs)}")
    if len(labs) > 1:
        print("  ^ more than one. Read that file before comparing any value to any range.")
    print(f"\n  at cut 3 : {len(s.records('LB', cut=3)):>6} of {len(s.domains['LB']):>6} laboratory rows")
    print(f"  at cut 12: {len(s.records('LB', cut=12)):>6} of {len(s.domains['LB']):>6}")
    print(f"\n  site reply to AE|042-S11-005|1 -> {s.query_site('AE', '042-S11-005', 1)[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
