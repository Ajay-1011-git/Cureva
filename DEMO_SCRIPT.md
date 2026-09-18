# Cureva Stage 1 — demo script

End-to-end run-through: exactly what to click, what to say, and what should
happen. Roughly **6 minutes** at a normal pace.

Everything below uses the real practice study. Nothing is staged — the subject
ids, lab values and findings are all really in `hackathon-data/`.

---

## Before you start (2 minutes, off-camera)

```bash
./run_stage1.sh doctor     # everything should be green
./run_stage1.sh serve      # backend :8000 + frontend :5173
```

Open **http://localhost:5173/atlas** and leave it on screen.

Two things worth checking before an audience sees it:

- **The graph panel is already full** (≈190 findings). If it is empty, the
  backend did not seed — check `/tmp` logs or restart `serve`.
- **Sound works.** Send one throwaway message and confirm you hear a female
  voice. Browsers block autoplay until the page has been interacted with, so
  this first click also unlocks audio for the rest of the demo.
- **The mic needs `localhost` or HTTPS.** It works on `localhost:5173`. If you
  demo from another machine's IP, the browser will silently refuse microphone
  access and you will be stuck typing.

Have a second terminal ready for the closing harness run.

---

## Act 0 — "What is already in the data" (45 seconds)

**Point at the right-hand panel before touching anything.**

> "This is every finding Atlas can derive from the study as it stands — 189 of
> them across 241 subjects, from eleven detectors. Nobody typed these in;
> they came out of the nine CSVs."

**Click the `hys law candidate 3` chip in the legend.**

> "Three subjects show the liver-injury pattern. One of them" — hover the red
> node — "is 042-S07-001."

**Click `all` to bring the rest back. Point at the two dense clusters.**

> "The clusters are real relationships, not decoration. This purple group is
> nine subjects on the same prohibited drug class. This yellow one is
> eligibility violations — inclusion and exclusion findings linked because
> they come from the same part of the protocol."

---

## Act 1 — "Who are we talking to" (30 seconds)

**Click the subject picker.**

> "The avatar interviews a real enrolled participant. 241 of them — filterable
> by site, arm, country."

**Type `S07` in the filter, pick `042-S07-001`.**

> "This is the man with the liver signal. 51, placebo arm, site S07 — and site
> S07 is the one whose local lab reports in different units, which matters in
> a moment."

---

## Act 2 — the conversation (2.5 minutes)

### Turn 1 — press **Speak** and say (or type):

> **"I've had a bad headache since yesterday and I've been taking ibuprofen for it."**

**What to point out while it answers:**

- The transcript of what it heard appears next to 🎤 — *"it shows you what it
  heard, not a placeholder; a mis-hearing has to be visible."*
- She moves while she speaks — head, hands, torso — and keeps breathing when
  she stops.
- She asks **one focused follow-up** (onset or severity), not "tell me more".
- Two new blue nodes appear on the right, and the footer ticks to
  **added this session (2)**.

> "Two things got recorded: a symptom and a concomitant medication. Both carry
> the patient's exact words — we never write a record without the quote it
> came from."

### Turn 2 — the one that lands:

> **"My eyes have been looking a bit yellow for two days."**

**Point at the graph as it updates.**

> "Watch where that node lands. It links straight to his existing Hy's law
> finding — because it is the same person, and yellowing eyes is exactly the
> symptom you would expect alongside that lab pattern. The system didn't
> diagnose anything. It put the patient's own words next to the lab signal
> that was already there, and made the connection visible."

### Turn 3 — show the guardrail:

> **"Should I stop taking the trial medication?"**

> "It won't answer that. It says it can't advise and offers to tell the study
> doctor. It never diagnoses, never interprets a lab, never tells anyone to
> change a medication."

### Turn 4 (optional, if you have time) — escalation:

> **"I've had chest pain since this morning and I'm short of breath."**

> "That one escalates — it says plainly this needs the study doctor now. And
> it still records both symptoms. An urgent symptom is the last one that
> should go unrecorded."

---

## Act 3 — "None of this touches the grade" (1 minute)

**Switch to the terminal.**

```bash
./run_stage1.sh harness
```

> "100 out of 100 on the public set. Gate needs 60. Clean evidence 100%, needs
> 90. Both traps answered honestly."

**Then the part that matters:**

```bash
.venv/bin/python tests/test_t1_22_zero_pro.py
```

> "Everything you just watched — the avatar, the patient records, the graph —
> is additive. This test runs every public question twice: once against a graph
> that has never seen the intake layer, once with a patient record injected.
> It diffs every answer. The diff is empty. The hidden studies carry zero
> patient-reported records, and the graded path doesn't care either way."

---

## Act 4 — the honest close (45 seconds)

```bash
./run_stage1.sh demo
```

Shows the load, the eleven detectors, and a worked Hy's law answer with the
unit conversion visible.

> "One thing worth showing: 042-S07-001's ALT reads 3.995 in the file. Against
> the central range that looks normal. It's reported in µkat/L because site S07
> uses a local lab — it's actually 239.7 U/L, four times the upper limit.
> Getting that wrong doesn't look like an error. It looks like a healthy
> patient."

And if asked what's weak, the honest answer is in `README.md` — the duplicate-
subject heuristic can't tell a genuine duplicate from two people who share
initials, a birth date and a sex.

---

## Things that can go wrong, and what to do

| Symptom | Cause | Do this |
|---|---|---|
| Amber "voice service degraded" banner | Sarvam rate limit or key issue | Keep going — it still transcribes and records, just doesn't speak. Say so; the degraded path is deliberate |
| Reply is "Could you say that again?" | Groq free tier (30 req/min) tripped | Wait ~30s and repeat the turn. Don't hammer it |
| Mic button missing | Not on `localhost`/HTTPS, or permission denied | Type instead — every turn works typed |
| Graph panel empty on load | Backend didn't seed | Restart `./run_stage1.sh serve` |
| No audio at all | Browser autoplay block | Click anywhere on the page once, resend |

**Insurance:** record a 3-minute screen capture of this exact run beforehand.
If the venue network is bad, Groq and Sarvam are the two things you don't
control.

---

## The five inputs, if you just want the list

1. `I've had a bad headache since yesterday and I've been taking ibuprofen for it.`
2. `My eyes have been looking a bit yellow for two days.`
3. `Should I stop taking the trial medication?`
4. `I've had chest pain since this morning and I'm short of breath.`
5. *(subject picker)* filter `S07` → `042-S07-001`
