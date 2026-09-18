"""PROExtraction -> PRORecord, written into StudyGraph's PRO index.

Act 1 only, never imported by stage1/atlas.py.
"""
from __future__ import annotations

from .models import PRORecord, PROExtraction


def write_extractions(graph, usubjid: str, extractions: list[PROExtraction],
                      transcript_ref: str, cut_available: int = 1) -> list[PRORecord]:
    """Write each usable extraction as a PRORecord, appended to `graph` in place.

    An extraction with an empty/missing raw_quote is discarded, not written
    with a placeholder — PRD FR-19 is a hard rule: a PRO record with no real
    quote behind it would be indistinguishable from a fabricated one, and this
    is the one point in the whole pipeline where that could slip through
    unnoticed. `seq` increments per-subject within PRO, the same convention
    every other domain follows (StudyGraph.next_pro_seq).

    Returns the PRORecord objects actually written (possibly fewer than
    len(extractions), if any were discarded).
    """
    written: list[PRORecord] = []
    for extraction in extractions:
        quote = (extraction.raw_quote or "").strip()
        if not quote:
            continue                     # FR-19 — never write a placeholder

        record = PRORecord(
            usubjid=usubjid,
            seq=graph.next_pro_seq(usubjid),
            pro_type=extraction.pro_type,
            term=extraction.term,
            raw_quote=quote,
            reported_date=extraction.reported_date,
            transcript_ref=transcript_ref,
            cut_available=cut_available,
        )
        graph.append_pro_record(record.model_dump(mode="json") | {"USUBJID": usubjid})
        written.append(record)
    return written
