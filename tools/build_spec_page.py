"""Render docs/HOLLOW_BUILD_EVENT_SPEC.md into a standalone styled HTML page.

Run:  .venv/bin/python tools/build_spec_page.py
Out:  docs/hollow-build.html
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "HOLLOW_BUILD_EVENT_SPEC.md"
OUT = ROOT / "docs" / "hollow-build.html"

# Which top-level section gets which accent rail + eyebrow label.
SECTION_META = {
    "HOLLOW BUILD":                 ("brief",  "Brief"),
    "ROUND 1 — LEDGER":             ("r1",     "Round 1"),
    "ROUND 2 — QUARANTINE":         ("r2",     "Round 2"),
    "JUDGING SYSTEM":               ("judge",  "Judging"),
    "ORGANIZER DATASET GENERATION": ("org",    "Organiser"),
    "ORGANIZER SETUP":              ("org",    "Organiser"),
    "PARTICIPANT README TEMPLATE":  ("org",    "Organiser"),
    "FINAL QUALITY CHECK":          ("check",  "Verification"),
}


def slug(text: str) -> str:
    s = re.sub(r"`|\*", "", text).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "section"


def split_sections(md: str) -> list[tuple[str, list[str]]]:
    """Split on level-1 headings, ignoring anything inside a fenced code block."""
    sections: list[tuple[str, list[str]]] = []
    fence = False
    title, buf = None, []
    for line in md.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith("# "):
            if title is not None:
                sections.append((title, buf))
            title, buf = line[2:].strip(), []
            continue
        if title is not None:
            buf.append(line)
    if title is not None:
        sections.append((title, buf))
    return sections


def h2s(body: list[str]) -> list[str]:
    """Level-2 headings in order, skipping fenced code."""
    out, fence = [], False
    for line in body:
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence and line.startswith("## "):
            out.append(line[3:].strip())
    return out


def convert(body: list[str]) -> str:
    md_body = "\n".join(body).strip()
    md_body = re.sub(r"^---\s*$", "", md_body, flags=re.M)  # the --- rules become section breaks
    return markdown.markdown(
        md_body,
        extensions=["tables", "fenced_code", "sane_lists", "md_in_html"],
        output_format="html5",
    )


def inject_ids(htm: str, headings: list[str]) -> str:
    """Give each <h2> the id the nav links to, in document order."""
    it = iter(headings)

    def repl(m: re.Match) -> str:
        try:
            return f'<h2 id="{slug(next(it))}">{m.group(1)}</h2>'
        except StopIteration:
            return m.group(0)

    return re.sub(r"<h2>(.*?)</h2>", repl, htm, flags=re.S)


def wrap_tables(htm: str) -> str:
    return htm.replace("<table>", '<div class="scroller"><table>').replace("</table>", "</table></div>")


def build() -> str:
    md_text = SRC.read_text(encoding="utf-8")
    sections = split_sections(md_text)

    nav_parts, body_parts = [], []
    for title, body in sections:
        kind, eyebrow = SECTION_META.get(title, ("org", "Section"))
        sid = slug(title)
        heads = h2s(body)
        inner = wrap_tables(inject_ids(convert(body), heads))

        links = "".join(
            f'<a href="#{slug(h)}">{html.escape(h)}</a>' for h in heads
        )
        nav_parts.append(
            f'<div class="nav-group" data-kind="{kind}">'
            f'<a class="nav-top" href="#{sid}"><span class="eyebrow">{eyebrow}</span>'
            f'<span class="nav-title">{html.escape(title)}</span></a>'
            f'<div class="nav-links">{links}</div></div>'
        )

        hero = ' section--hero' if kind == "brief" else ""
        body_parts.append(
            f'<section class="section{hero}" id="{sid}" data-kind="{kind}">'
            f'<header class="section-head"><p class="eyebrow">{eyebrow}</p>'
            f'<h1>{html.escape(title)}</h1></header>{inner}</section>'
        )

    return TEMPLATE.replace("<!--NAV-->", "\n".join(nav_parts)).replace(
        "<!--BODY-->", "\n".join(body_parts)
    )


TEMPLATE = r"""<title>Hollow Build</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&display=swap">
<style>
:root{
  --paper:#f2f5f6; --surface:#fbfcfc; --sunken:#e8edef;
  --ink:#131a1f; --ink-2:#4d5a63; --ink-3:#77858e;
  --rule:#d3dbe0; --rule-soft:#e2e8eb;
  --accent:#a8501c; --accent-soft:#f0e2d7;
  --r1:#a8501c; --r2:#12606e; --judge:#5a4a86; --org:#4d5a63; --check:#2c6248;
  --crit:#96202a; --ok:#2c6248;
  --shadow:0 1px 2px rgba(19,26,31,.06), 0 8px 24px -16px rgba(19,26,31,.28);
  --sans:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  --serif:"Newsreader",Georgia,"Times New Roman",serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#0d1216; --surface:#141c22; --sunken:#1a242b;
    --ink:#e7edf0; --ink-2:#a2b0ba; --ink-3:#7d8b95;
    --rule:#26333c; --rule-soft:#1f2b33;
    --accent:#e08a4e; --accent-soft:#2a1f18;
    --r1:#e08a4e; --r2:#4fb6c6; --judge:#a596d8; --org:#a2b0ba; --check:#6fc49a;
    --crit:#e4737c; --ok:#6fc49a;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px -18px rgba(0,0,0,.8);
  }
}
:root[data-theme="dark"]{
  --paper:#0d1216; --surface:#141c22; --sunken:#1a242b;
  --ink:#e7edf0; --ink-2:#a2b0ba; --ink-3:#7d8b95;
  --rule:#26333c; --rule-soft:#1f2b33;
  --accent:#e08a4e; --accent-soft:#2a1f18;
  --r1:#e08a4e; --r2:#4fb6c6; --judge:#a596d8; --org:#a2b0ba; --check:#6fc49a;
  --crit:#e4737c; --ok:#6fc49a;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px -18px rgba(0,0,0,.8);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:var(--sans); font-size:15px; line-height:1.62;
  -webkit-font-smoothing:antialiased;
}
::selection{background:var(--accent-soft); color:var(--ink)}
a{color:var(--accent); text-decoration:none}
a:hover{text-decoration:underline; text-underline-offset:2px}
:focus-visible{outline:2px solid var(--accent); outline-offset:2px; border-radius:3px}

/* ---------- masthead ---------- */
.masthead{
  border-bottom:1px solid var(--rule); background:var(--surface);
  padding-block:44px 30px; padding-inline:16px;
}
.masthead-in{max-width:1180px; margin-inline:auto}
.wordmark{
  font-family:var(--serif); font-weight:600; font-size:clamp(38px,7.2vw,68px);
  line-height:.98; letter-spacing:-.022em; margin:0; text-wrap:balance;
}
.wordmark em{font-style:italic; color:var(--accent)}
.pitch{
  font-family:var(--serif); font-size:clamp(17px,2.3vw,21px); line-height:1.5;
  color:var(--ink-2); max-width:62ch; margin:14px 0 0;
}
.chips{display:flex; flex-wrap:wrap; gap:8px; margin-top:22px; padding:0; list-style:none}
.chips li{
  font-family:var(--mono); font-size:11.5px; letter-spacing:.04em; text-transform:uppercase;
  color:var(--ink-2); border:1px solid var(--rule); border-radius:2px;
  padding:5px 9px; background:var(--paper);
}
.chips li b{color:var(--ink); font-weight:500}

/* ---------- shell ---------- */
.shell{
  max-width:1180px; margin-inline:auto; padding-inline:16px; padding-block:0 80px;
  display:grid; grid-template-columns:238px minmax(0,1fr); gap:44px; align-items:start;
}
@media (max-width:900px){ .shell{grid-template-columns:minmax(0,1fr); gap:0} }

/* ---------- nav ---------- */
.nav{
  position:sticky; top:calc(env(safe-area-inset-top, 0px) + 20px);
  max-height:calc(100vh - 60px); overflow-y:auto; overscroll-behavior:contain;
  padding-block:28px 24px; font-size:13px;
}
.nav-group{margin-bottom:20px; border-left:2px solid var(--rule-soft); padding-left:12px}
.nav-group[data-kind="r1"]{border-left-color:var(--r1)}
.nav-group[data-kind="r2"]{border-left-color:var(--r2)}
.nav-group[data-kind="judge"]{border-left-color:var(--judge)}
.nav-group[data-kind="check"]{border-left-color:var(--check)}
.nav-top{display:block; color:var(--ink); margin-bottom:6px}
.nav-top:hover{text-decoration:none}
.nav-title{
  display:block; font-family:var(--serif); font-size:15px; font-weight:600;
  line-height:1.25; letter-spacing:-.01em;
}
.nav-links{display:flex; flex-direction:column; gap:1px}
.nav-links a{
  color:var(--ink-3); padding:2px 0; line-height:1.4; font-size:12.5px;
  border-left:2px solid transparent; margin-left:-14px; padding-left:12px;
}
.nav-links a:hover{color:var(--ink); text-decoration:none}
.nav-links a.here{color:var(--ink); border-left-color:currentColor; font-weight:500}
.eyebrow{
  font-family:var(--mono); font-size:10.5px; letter-spacing:.13em; text-transform:uppercase;
  color:var(--ink-3); margin:0;
}
.nav-mobile{display:none}
@media (max-width:900px){
  .nav{position:static; max-height:none; overflow:visible; padding-block:0}
  .nav-mobile{display:block; margin-block:20px 8px; border:1px solid var(--rule); border-radius:4px; background:var(--surface)}
  .nav-mobile>summary{
    cursor:pointer; padding:11px 14px; font-family:var(--mono); font-size:12px;
    letter-spacing:.08em; text-transform:uppercase; color:var(--ink-2);
  }
  .nav-mobile[open]>summary{border-bottom:1px solid var(--rule-soft)}
  .nav-inner{padding:14px}
  .nav-desktop{display:none}
}

/* ---------- sections ---------- */
main{padding-block:28px 0; min-width:0}
.section{
  scroll-margin-top:24px; padding-block:34px 44px;
  border-top:1px solid var(--rule); margin-top:26px;
}
.section:first-child{border-top:0; margin-top:0; padding-top:8px}
.section-head{margin-bottom:26px; border-left:3px solid var(--accent); padding-left:16px}
.section[data-kind="r1"] .section-head{border-left-color:var(--r1)}
.section[data-kind="r2"] .section-head{border-left-color:var(--r2)}
.section[data-kind="judge"] .section-head{border-left-color:var(--judge)}
.section[data-kind="org"] .section-head{border-left-color:var(--org)}
.section[data-kind="check"] .section-head{border-left-color:var(--check)}
.section-head h1{
  font-family:var(--serif); font-weight:600; font-size:clamp(27px,4.2vw,40px);
  line-height:1.08; letter-spacing:-.02em; margin:4px 0 0; text-wrap:balance;
}
.section--hero .section-head{display:none}
.section--hero{padding-top:0}

h2{
  font-family:var(--serif); font-weight:600; font-size:clamp(21px,3vw,27px);
  line-height:1.2; letter-spacing:-.015em; margin:44px 0 14px;
  padding-bottom:8px; border-bottom:1px solid var(--rule-soft); text-wrap:balance;
  scroll-margin-top:24px;
}
h3{
  font-family:var(--sans); font-weight:600; font-size:15.5px; letter-spacing:-.005em;
  margin:30px 0 10px; color:var(--ink); scroll-margin-top:24px;
}
h4{font-family:var(--mono); font-size:12.5px; letter-spacing:.06em; text-transform:uppercase; color:var(--ink-2); margin:24px 0 8px}
p{margin:0 0 14px; max-width:74ch}
strong{font-weight:600}
main ul,main ol{margin:0 0 16px; padding-left:22px; max-width:74ch}
main li{margin-bottom:6px}
main li::marker{color:var(--ink-3)}
hr{border:0; border-top:1px solid var(--rule-soft); margin:30px 0}

blockquote{
  margin:18px 0; padding:14px 18px; border-left:3px solid var(--accent);
  background:var(--surface); border-radius:0 4px 4px 0; color:var(--ink-2);
  box-shadow:var(--shadow);
}
blockquote p{margin-bottom:8px; max-width:66ch}
blockquote p:last-child{margin-bottom:0}
blockquote em{color:var(--ink)}

code{
  font-family:var(--mono); font-size:.855em; background:var(--sunken);
  padding:1px 5px; border-radius:3px; color:var(--ink); word-break:break-word;
}
pre{
  background:var(--surface); border:1px solid var(--rule); border-radius:5px;
  padding:14px 16px; overflow-x:auto; margin:0 0 18px; box-shadow:var(--shadow);
}
pre code{background:none; padding:0; font-size:12.4px; line-height:1.62; white-space:pre}

.scroller{overflow-x:auto; margin:0 0 20px; border:1px solid var(--rule); border-radius:5px; background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:13.4px; min-width:480px}
thead th{
  text-align:left; font-family:var(--mono); font-weight:500; font-size:11px;
  letter-spacing:.09em; text-transform:uppercase; color:var(--ink-2);
  padding:10px 13px; border-bottom:1px solid var(--rule); background:var(--sunken);
  white-space:nowrap;
}
tbody td{padding:9px 13px; border-bottom:1px solid var(--rule-soft); vertical-align:top; font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--sunken)}
td code,th code{font-size:12px}

.footer{
  max-width:1180px; margin:0 auto; padding:26px 16px 40px; border-top:1px solid var(--rule);
  color:var(--ink-3); font-family:var(--mono); font-size:11.5px; letter-spacing:.04em;
  display:flex; flex-wrap:wrap; gap:10px 22px; justify-content:space-between;
}
@media (prefers-reduced-motion: no-preference){ html{scroll-behavior:smooth} }
</style>

<header class="masthead">
  <div class="masthead-in">
    <p class="eyebrow">Two-round technical investigation event</p>
    <h1 class="wordmark">HOLLOW <em>BUILD</em></h1>
    <p class="pitch">A signed firmware release shipped to 2,300 customers contains code that no one wrote. Rebuild the provenance of every artifact from nine disconnected logs, prove which releases are contaminated, then let an autonomous agent crew quarantine them under human authority.</p>
    <ul class="chips">
      <li><b>2</b> connected rounds</li>
      <li><b>9</b> evidence sources</li>
      <li><b>46k</b> rows</li>
      <li><b>45</b> hidden questions</li>
      <li><b>6</b> traps</li>
      <li><b>4</b> planted injections</li>
      <li><b>6</b> agent nodes</li>
      <li><b>8</b> cycles</li>
      <li><b>100</b> pts per round</li>
      <li>no paid API</li>
    </ul>
  </div>
</header>

<div class="shell">
  <nav class="nav" aria-label="Contents">
    <details class="nav-mobile">
      <summary>Contents</summary>
      <div class="nav-inner"><!--NAV--></div>
    </details>
    <div class="nav-desktop"><!--NAV--></div>
  </nav>
  <main><!--BODY--></main>
</div>

<footer class="footer">
  <span>Hollow Build — competition specification</span>
  <span>Round 1 LEDGER · Round 2 QUARANTINE</span>
</footer>

<script>
(function(){
  var links = Array.prototype.slice.call(document.querySelectorAll('.nav-desktop .nav-links a'));
  if(!links.length || !('IntersectionObserver' in window)) return;
  var byId = {};
  links.forEach(function(a){ byId[a.getAttribute('href').slice(1)] = a; });
  var targets = Object.keys(byId).map(function(id){ return document.getElementById(id); }).filter(Boolean);
  var seen = {};
  var io = new IntersectionObserver(function(entries){
    entries.forEach(function(e){ seen[e.target.id] = e.isIntersecting ? e.boundingClientRect.top : null; });
    var best = null;
    targets.forEach(function(t){
      var r = t.getBoundingClientRect();
      if(r.top <= 120 && (best === null || r.top > best.getBoundingClientRect().top)) best = t;
    });
    links.forEach(function(a){ a.classList.remove('here'); });
    if(best && byId[best.id]) byId[best.id].classList.add('here');
  }, {rootMargin:'-100px 0px -70% 0px', threshold:0});
  targets.forEach(function(t){ io.observe(t); });
})();
</script>
"""


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
