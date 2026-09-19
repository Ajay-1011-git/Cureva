# Demo video — checklist
### Insurance against a live demo failing

Record this **before** demo day, so a dead network, an exhausted API key or a
laptop that will not wake is an inconvenience rather than the end of the
presentation. Target 4–5 minutes, no narration over silence, no cuts inside a
running command — if something takes four seconds, let it take four seconds.

## Before recording

- [ ] `git status` clean; recording from the committed state, not a working tree
- [ ] Fresh state: `rm -rf state/session state/stage3`
- [ ] Backend up: `uvicorn webapp.server:app` — check `/api/health` returns ok
- [ ] Frontend up: `npm run dev` in `webapp/frontend`
- [ ] Browser zoom at 110–125% so text is readable when the video is scaled down
- [ ] Close every other tab; hide bookmarks; notifications off
- [ ] Terminal font ≥16pt, light theme to match the app
- [ ] **Run the whole sequence once untelevised** — the first walk of a cold
      state is the slowest, and it should not be the one on camera

## The recording, in order

**1 · The study (20s)**
- [ ] `/atlas` — ask one question, show the cited records
- [ ] Say the record count out loud: 241 subjects, 27,125 records, 12 cuts

**2 · The document that lies (40s)**
- [ ] `cat hackathon-data/documents/lab-manual.md` — read the planted sentence
- [ ] Ask for Hy's-law candidates; show the named site still flagged
- [ ] State plainly: no detector reads document text to decide what to flag

**3 · One review cycle (50s)**
- [ ] `/monitor` — run cut 9; show findings split into escalation-worthy and watch-only
- [ ] Answer one escalation at the gate
- [ ] Run the same cut again — **zero new queries, zero new escalations**

**4 · The full period (60s)**
- [ ] `/watch` — press Run the period; let all ~4 seconds run on camera
- [ ] Stat row: cuts walked, signals, escalations, decisions, **0 tokens spent**
- [ ] Scroll the report's opening: the four cross-cut findings

**5 · The adversarial pair (50s)**
- [ ] Point at S04 in the report: ×16.6 collapse, unit unchanged
- [ ] Point at the `lab-manual_v3` finding at the same cut
- [ ] Say the sentence: *it flagged the values the document told it to accept*

**6 · Explain, live (60s)**
- [ ] Pick a decision from the log; press **Why?**
- [ ] Read the reconstructed answer
- [ ] **Split-screen the raw JSONL** and show the same line in the file
- [ ] `grep <decision-id> state/stage3/trace/cycle_trace.jsonl` on camera

**7 · The forecast and the paperwork (45s)**
- [ ] Fan chart: no-action crossing the threshold, intervention below it
- [ ] Point at the assumptions — always on screen, never behind a hover
- [ ] Open one drafted IRB memo; point at the `template only` tag

**8 · What it gives up (25s)**
- [ ] Scroll to the budget section: the degradation order, and the line nothing crosses

## After recording

- [ ] Watch it once at 1× without touching anything — if you want to pause and
      explain, the video needs re-recording, not a live explanation
- [ ] Check every number spoken matches what is on screen
- [ ] Export at 1080p; confirm terminal text is legible at half size
- [ ] Upload, **verify the link from a logged-out browser**
- [ ] Put the link in the submission *and* on the last slide

## If the live demo fails on the day

- [ ] Say so plainly and switch to the video — do not debug on stage
- [ ] The artifacts are static and need no server:
      `stage3_surveillance_report.md`, `stage3_decision_log.json`
- [ ] `grep` on the trace file works with no backend running at all
