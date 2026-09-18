"""Act 2 — turn accumulated Finding objects from Atlas.answer() calls into a
relationship graph. Backend-only, session-scoped, never imported by stage1/.

networkx is used here deliberately, unlike StudyGraph itself: this graph is
genuinely small (tens of findings accumulated in one demo session, not tens of
thousands of records), so connected_components/pagerank in a few lines beats
hand-rolled union-find — the opposite trade-off from StudyGraph, and for the
opposite reason (TRD §3).
"""
from __future__ import annotations

import networkx as nx

from schemas import Finding, RecordRef
from study import parse_date

from .models import FindingEdge, FindingNode

#: Which protocol TOPIC a finding code's rule belongs to. Two codes sharing a
#: topic get a SHARED_PROTOCOL_SECTION edge — this is deliberately a topic
#: grouping, not a literal section number: the build brief's own example pairs
#: INCLUSION_VIOLATION (§2) with EXCLUSION_VIOLATION (§3), two DIFFERENT
#: numbered sections that are the same eligibility topic. None means the code
#: is a data-quality signal with no protocol-rule topic behind it.
#:
#: Restricted to DIFFERENT codes sharing a topic (never the same code to
#: itself) — same-code-to-same-code would connect every subject who happens to
#: share one common finding into a single dense clique (confirmed: 150
#: VISIT_OUT_OF_WINDOW findings under that reading produced 11,254 edges),
#: which shows nothing about which PROBLEMS share a root cause and defeats the
#: entire point of the graph (PRD G6).
PROTOCOL_SECTION = {
    "HYS_LAW_CANDIDATE": "liver_safety", "SAE_MISCODED": "safety_reporting",
    "VISIT_OUT_OF_WINDOW": "visit_schedule",
    "INCLUSION_VIOLATION": "eligibility", "EXCLUSION_VIOLATION": "eligibility",
    "PROHIBITED_CONMED": "conmeds", "DOSING_ERROR": "dosing",
    "AE_BEFORE_FIRST_DOSE": None, "DUPLICATE_SUBJECT": None,
    "MISSING_EXPOSURE_RECORD": None, "LAB_UNIT_MISMATCH": None,
}

#: Findings within this many days of each other, for the same subject,
#: get a TEMPORAL_PROXIMITY edge — same window Hy's law itself uses.
TEMPORAL_PROXIMITY_DAYS = 14


class FindingGraph:
    """Session-scoped store: every Finding seen so far this demo session,
    deduplicated by (code, usubjid), plus the edges between them.

    `study_graph` is used only to resolve evidence RecordRefs back to real
    records (their CMCLAS, their date) when building edges — this module never
    calls into Atlas or re-runs a detector; it only observes findings it's
    handed.
    """

    def __init__(self, study_graph):
        self.study_graph = study_graph
        self.nodes: dict[str, FindingNode] = {}      # finding_id -> node
        self._fingerprints: set[str] = set()           # (code, usubjid) seen
        self.edges: list[FindingEdge] = []
        self._graph = nx.Graph()

    # ------------------------------------------------------------- ingest
    def observe(self, finding: Finding, cut: int | None) -> FindingNode | None:
        """Add one Finding, if it isn't a duplicate of one already seen.

        Deduplicated by (code, usubjid) — the same subject flagged twice for
        the same code across two Atlas.answer() calls in one session is one
        node, not two.
        """
        key = f"{finding.code}|{finding.usubjid or ''}"
        if key in self._fingerprints:
            return None
        self._fingerprints.add(key)

        derived_from = sorted({e.domain for e in finding.evidence if e.domain != "DOC"})
        node = FindingNode(
            finding_id=key, code=finding.code, usubjid=finding.usubjid,
            site=finding.site, evidence=list(finding.evidence),
            derived_from=derived_from, cut_available=cut or 1,
        )
        self.nodes[key] = node
        self._graph.add_node(key)
        self._connect(node)
        return node

    def observe_all(self, findings: list[Finding], cut: int | None) -> list[FindingNode]:
        return [n for f in findings if (n := self.observe(f, cut)) is not None]

    #: Node code for something the patient said, as opposed to something a
    #: detector found. Deliberately NOT one of schemas.FindingCode: this is
    #: Cureva's own Act-2 node type, and labelling patient-reported data with a
    #: graded finding code would blur the one distinction that matters here —
    #: a detector's conclusion versus a person's own words.
    PATIENT_REPORTED = "PATIENT_REPORTED"

    def observe_pro_record(self, record, cut: int | None) -> FindingNode | None:
        """Add one patient-reported record to the graph.

        This is what makes a conversation visible: the study's existing
        findings are seeded at startup, so a turn about an already-known
        subject would otherwise change nothing on screen. What genuinely IS
        new is what the patient just said, so that is what gets a node —
        carrying the verbatim quote, and linked to that subject's existing
        findings so it lands beside them rather than floating alone.
        """
        usubjid = record.get("usubjid") or record.get("USUBJID")
        seq = record.get("seq")
        if not usubjid:
            return None
        key = f"{self.PATIENT_REPORTED}|{usubjid}|{seq}"
        if key in self._fingerprints:
            return None
        self._fingerprints.add(key)

        node = FindingNode(
            finding_id=key,
            code=self.PATIENT_REPORTED,
            usubjid=usubjid,
            site=self.study_graph.site_for(usubjid),
            evidence=[RecordRef(domain="PRO", usubjid=usubjid, seq=seq)],
            derived_from=["PRO"],
            cut_available=cut or 1,
        )
        self.nodes[key] = node
        self._graph.add_node(key)

        # Link it to everything already standing against this subject. A
        # symptom the patient reports is, by construction, about the same
        # person as their existing findings — that is the connection the
        # demo is showing.
        for other_id, other in list(self.nodes.items()):
            if other_id == key or other.usubjid != usubjid:
                continue
            self._add_edge(key, other_id, "TEMPORAL_PROXIMITY", 0.9)
        return node

    # -------------------------------------------------------------- edges
    def _record_date(self, ref):
        if ref.domain == "DOC" or ref.seq is None:
            return None
        rec = self.study_graph.by_key.get((ref.domain, ref.usubjid, ref.seq))
        return self.study_graph.record_date(rec, None) if rec else None

    def _cmclas_of(self, node: FindingNode) -> set[str]:
        out = set()
        for ref in node.evidence:
            if ref.domain != "CM" or ref.seq is None:
                continue
            rec = self.study_graph.by_key.get(("CM", ref.usubjid, ref.seq))
            if rec:
                out.add((rec.get("CMCLAS") or "").strip().upper())
        return out - {""}

    def _earliest_date(self, node: FindingNode):
        dates = [d for ref in node.evidence if (d := self._record_date(ref))]
        return min(dates) if dates else None

    def _connect(self, new_node: FindingNode) -> None:
        """Build every applicable edge between `new_node` and existing nodes."""
        new_section = PROTOCOL_SECTION.get(new_node.code)
        new_classes = self._cmclas_of(new_node)
        new_date = self._earliest_date(new_node)

        for other_id, other in self.nodes.items():
            if other_id == new_node.finding_id:
                continue

            if (new_section and other.code != new_node.code
                    and PROTOCOL_SECTION.get(other.code) == new_section):
                self._add_edge(new_node.finding_id, other_id, "SHARED_PROTOCOL_SECTION", 0.6)

            shared_classes = new_classes & self._cmclas_of(other)
            if shared_classes:
                self._add_edge(new_node.finding_id, other_id, "SAME_DRUG_CLASS", 0.7)

            if (new_node.usubjid and new_node.usubjid == other.usubjid
                    and new_date is not None):
                other_date = self._earliest_date(other)
                if other_date is not None and abs((new_date - other_date).days) <= TEMPORAL_PROXIMITY_DAYS:
                    self._add_edge(new_node.finding_id, other_id, "TEMPORAL_PROXIMITY", 0.8)

    def _add_edge(self, a: str, b: str, relation: str, weight: float) -> None:
        # One relation per pair is enough; a pair already connected by this
        # relation isn't duplicated.
        if self._graph.has_edge(a, b) and relation in self._graph[a][b].get("relations", set()):
            return
        self.edges.append(FindingEdge(from_finding_id=a, to_finding_id=b,
                                      relation=relation, weight=weight))
        if self._graph.has_edge(a, b):
            self._graph[a][b]["relations"].add(relation)
            self._graph[a][b]["weight"] = max(self._graph[a][b]["weight"], weight)
        else:
            self._graph.add_edge(a, b, relations={relation}, weight=weight)

    # ---------------------------------------------------------- clustering
    def clusters(self) -> list[list[str]]:
        """Connected components of the finding graph, as lists of finding_ids.

        Never raises on an empty graph — networkx's own connected_components
        handles zero nodes cleanly, but the caller (webapp) still gets an
        explicit [] rather than depending on that (TRD §8: /finding-graph
        returns empty lists, never a 500, on any clustering edge case).
        """
        try:
            return [sorted(c) for c in nx.connected_components(self._graph)]
        except Exception:
            return [[n] for n in self.nodes]     # degrade to singletons, never crash

    def centrality(self) -> dict[str, float]:
        """Hub score per finding_id — pagerank, falling back to plain degree
        if pagerank is unstable on a tiny/disconnected graph (per TRD's own
        stated fallback)."""
        if not self.nodes:
            return {}
        try:
            return {k: round(v, 4) for k, v in nx.pagerank(self._graph, weight="weight").items()}
        except Exception:
            n = max(1, self._graph.number_of_nodes() - 1)
            return {k: round(self._graph.degree(k) / n, 4) for k in self.nodes}

    def snapshot(self) -> dict:
        """The shape GET /api/atlas/finding-graph returns."""
        return {
            "nodes": [n.model_dump(mode="json") for n in self.nodes.values()],
            "edges": [e.model_dump(mode="json") for e in self.edges],
            "clusters": self.clusters(),
            "centrality": self.centrality(),
        }
