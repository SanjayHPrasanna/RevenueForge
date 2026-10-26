"""Proposal video: a narrated, animated "solution story" for one deal, rendered to MP4.

Everything on screen comes from the deal's own data (requirements, architecture, team and skills from the
knowledge graph, case studies, certifications, delivery plan), so nothing is invented. The AI only writes
the spoken narration, from masked facts (the client's name is never sent; it is put back afterwards).
The video is client-facing: costs, margins, gaps, risks and internal codes are never shown.

Pipeline: facts -> narration (AI or template) -> computer voice per scene -> animated frames (Pillow)
-> MP4 with the bundled ffmpeg. Runs in a background thread with progress kept on a Document row."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from sqlalchemy import select

from ..config import OUTPUT_DIR, settings
from ..db import SessionLocal
from ..models import Deal, DealStage, Document
from . import llm
from . import pipeline

log = logging.getLogger("revenueforge.story")

W, H, FPS = 1280, 720, 25
RATE = 44100
CLIENT = "{CLIENT}"
FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

C = {
    "b950": "#082B3D", "b900": "#0C3D55", "b800": "#125C7E", "b700": "#0B638E", "b500": "#118AC3", "b200": "#9FD1EB", "b100": "#CFE8F5",
    "b50": "#EAF5FB", "e500": "#F5833A", "e400": "#F79A5E", "ink": "#10222E", "soft": "#3D4F5B", "muted": "#5F707B", "faint": "#8A99A3",
    "paper": "#F3F6F8", "line": "#DCE3E8", "white": "#FFFFFF", "ok": "#17876A",
}
CAT_COLOR = {"Functional": "#118AC3", "Non-functional": "#0B638E", "Compliance": "#7A3E9A", "Commercial": "#F5833A"}
SCENES = ["intro", "needs", "solution", "team", "proof", "plan", "close"]
WORDS = {"intro": 22, "needs": 38, "solution": 42, "team": 38, "proof": 38, "plan": 34, "close": 22}
KICKER = {"needs": "What you asked for", "solution": "Our solution", "team": "The team behind it", "proof": "Done before",
          "plan": "How we'll deliver"}


# =========================================================================== facts
def _months(weeks: float) -> int:
    return max(1, round(weeks / 4.345))


def build_facts(db, deal: Deal) -> dict:
    """Client-facing facts for the video, masked the same way as everything else sent to the AI."""
    ctx = pipeline.context(db, deal)
    meta, reqs, arch, est = ctx["meta"], ctx["requirements"], ctx["architecture"] or {}, ctx["estimation"] or {}
    cats = Counter(r.get("category") or "Other" for r in reqs)
    subcats = Counter(r.get("subcategory") for r in reqs if r.get("subcategory") and r.get("category") == "Functional"
                      and not re.search(r"general|other|misc|scope|project management", r.get("subcategory") or "", re.I))
    must = [r["text"][:220] for r in reqs if r.get("category") in ("Functional", "Non-functional") and r.get("priority") in ("Mandatory", "Must", "")][:10]

    layers = []
    for l in (arch.get("layers") or [])[:6]:
        comps = [{"name": c["name"], "mandated": c.get("source") == "RFP-mandated"} for c in (l.get("components") or [])[:4]]
        if comps:
            layers.append({"layer": l["layer"], "components": comps})

    kb = ctx["kb"]
    by_code = {e["code"]: e for e in kb.employees}
    relevant = {t.lower() for r in reqs for t in (r.get("technologies") or [])}
    relevant |= {c["name"].lower() for l in layers for c in l["components"]}
    relevant |= {(c.get("choice") or "").lower() for c in (arch.get("choices") or [])}
    team, people, years, places, skill_hits, skill_all = [], set(), 0.0, set(), Counter(), Counter()
    for t in est.get("team") or []:
        team.append({"role": t["role"], "fte": t.get("fte", 0), "headcount": t.get("headcount", 0)})
        for a in t.get("assigned") or []:
            e = by_code.get(a.get("code"))
            if not e or e["code"] in people:
                continue
            people.add(e["code"])
            years += float(e.get("years") or 0)
            loc = (e.get("location") or "").split(",")[-1].strip()
            if loc:
                places.add(loc)
            for s in e.get("skills") or []:
                if (s.get("level") or 0) >= 4:
                    skill_all[s["name"]] += 1
                    if s["name"].lower() in relevant or any(s["name"].lower() in x or x in s["name"].lower() for x in relevant if len(x) > 3):
                        skill_hits[s["name"]] += 1
    ranked = [s for s, _ in skill_hits.most_common(20)] + [s for s, _ in skill_all.most_common(30)]
    skills = []
    for s in ranked:
        if len(s) <= 2 or s in skills or any(s.lower() in k.lower() for k in skills):
            continue
        skills = [k for k in skills if k.lower() not in s.lower()] + [s]
        if len(skills) >= 10:
            break

    cases = []
    for c in ctx["case_studies"][:3]:
        cases.append({"title": c["title"], "industry": c.get("industry", ""), "region": c.get("region", ""), "year": str(c.get("year") or ""),
                      "outcome": (c.get("outcomes") or [""])[0]})
    certs = [c["name"] for c in ctx["certifications"]][:5]

    phases, start, prev = [], 0.0, None
    for p in est.get("phases") or []:
        wk = float(p.get("weeks") or 0)
        if prev and abs(wk - prev["weeks"]) < 0.5 and wk > 8:  # equal long phases run side by side (e.g. managed-service tracks)
            s0 = prev["start"]
        else:
            s0 = start
        phases.append({"name": p["name"], "weeks": wk, "start": s0, "detail": p.get("detail", "")})
        start = max(start, s0 + wk)
        prev = phases[-1]

    return {
        "company": ctx["company"]["name"], "client": CLIENT, "title": meta.get("title") or ctx["deal"]["name"],
        "doc_type": deal.doc_type or "RFP", "industry": deal.industry, "region": deal.region,
        "engagement": (deal.engagement_type or "").replace("_", " "),
        "requirements": len(reqs), "categories": dict(cats.most_common()), "top_areas": [s for s, _ in subcats.most_common(3)],
        "key_requirements": must,
        "layers": layers, "headcount": int(est.get("headcount") or sum(t["headcount"] for t in team) or 0), "roles": team[:8],
        "people_named": len(people), "years": int(years), "locations": sorted(places)[:4], "skills": skills[:10],
        "case_studies": cases, "certifications": certs,
        "phases": phases[:5], "total_months": _months(max([p["start"] + p["weeks"] for p in phases] or [0])),
        "slas": (meta.get("slas") or [])[:3], "deliverables": (meta.get("deliverables") or [])[:3],
        "_alias": ctx["deal"]["client_display"],
    }


# =========================================================================== narration
def _fallback(f: dict) -> dict:
    cats = ", ".join(f"{n} {k.lower()}" for k, n in list(f["categories"].items())[:3])
    needs = f["top_areas"] or ["a dependable platform", "smooth delivery", "measurable outcomes"]
    layers = f["layers"]
    comps = [c["name"] for l in layers for c in l["components"]][:3]
    case = f["case_studies"][0] if f["case_studies"] else None
    sla = f["slas"][0] if f["slas"] else ""
    sc = {
        "intro": f"{f['company']} is pleased to present our proposal for {CLIENT}: {f['title']}.",
        "needs": f"Your {f['doc_type']} sets out {f['requirements']} requirements, including {cats}. "
                 f"Three areas matter most: {', '.join(needs[:-1])} and {needs[-1]}." if len(needs) > 1 else
                 f"Your {f['doc_type']} sets out {f['requirements']} requirements, and we have answered every one.",
        "solution": (f"Our solution is built in {len(layers)} layers, from {layers[0]['layer']} to {layers[-1]['layer']}, "
                     f"using {', '.join(comps)}. Every part traces back to the requirements behind it.") if layers else
                    "Our solution is designed around your requirements, and every part traces back to what you asked for.",
        "team": (f"A team of {f['headcount']} people, with {f['years']} years of combined experience, brings proven skills in "
                 f"{', '.join(f['skills'][:3])}.") if f["skills"] else f"A dedicated team of {f['headcount']} people will deliver this programme.",
        "proof": (f"We have done this before. Our {case['title'].lower()} work led to this result: {case['outcome']}."
                  if case and case["outcome"] else "We have delivered programmes like this before.")
                 + (f" We hold {', '.join(f['certifications'][:2])}." if f["certifications"] else ""),
        "plan": f"Delivery runs in {len(f['phases'])} phases over {f['total_months']} months, starting with {f['phases'][0]['name'].lower()}."
                + (f" The service is designed to meet your target of {sla}." if sla else "") if f["phases"] else
                "We will start quickly, with clear phases and regular checkpoints.",
        "close": f"We are ready to start. Thank you for considering {f['company']}.",
    }
    return {"needs": needs[:3], "scenes": sc, "engine": "template"}


def write_narration(f: dict) -> dict:
    fb = _fallback(f)
    # the separate narration key only stands in for the server's default AI, never for a company's own key
    key = (settings.gemini_video_api_key or None) if llm.current_profile().source == "server" else None
    if not key and not llm.is_enabled():
        return fb
    facts = {k: v for k, v in f.items() if not k.startswith("_")}
    limits = ", ".join(f"{s}: at most {n} words" for s, n in WORDS.items())
    system = ("You write the spoken narration for a short animated video that a company sends to a prospective client with its proposal. "
              "Tone: warm, confident, plain spoken English, like a senior bid lead talking to the client. Speak as 'we' for the company "
              "and 'you' for the client. Use ONLY the facts given. Never mention prices, costs, margins, discounts, gaps, risks, weaknesses, "
              "requirement codes or employee codes. Refer to the client only as {CLIENT} or 'you'. No lists, bullets, headings or emojis; "
              "short sentences that read well aloud.")
    keys = ", ".join('"%s": "..."' % s for s in SCENES)
    prompt = ("Facts (JSON):\n" + json.dumps(facts, ensure_ascii=False)[:9000] + "\n\n"
              "Return JSON: {\"needs\": [three short phrases of at most 6 words naming what the client most needs], "
              "\"scenes\": {" + keys + "}}.\n"
              "Scene order and purpose: intro (who we are, what this is for), needs (what the client asked for), solution (the layered "
              "architecture and key technologies), team (size, experience, key skills), proof (case studies with their outcomes, "
              "certifications), plan (phases and timeline, service targets), close (confident, thank them). Word limits: " + limits + ".")
    try:
        out = llm.complete_json(system, prompt, max_tokens=3000, api_key=key)
        sc = out.get("scenes") or {}
        res = {"needs": [str(x)[:60] for x in (out.get("needs") or [])][:3] or fb["needs"], "scenes": {}, "engine": "ai"}
        for s in SCENES:
            txt = re.sub(r"\s+", " ", str(sc.get(s) or "")).strip()
            words = txt.split()
            if not txt or len(words) > WORDS[s] * 1.6 or re.search(r"\b(REQ|MIL|EMP)-\d", txt) or re.search(r"margin|cost|price|discount", txt, re.I):
                txt = fb["scenes"][s]
            res["scenes"][s] = txt
        return res
    except Exception as e:
        log.info("Video narration: AI unavailable, using the template (%s)", e)
        return fb


def personalise(text: str, client: str) -> str:
    """Put the client's real name (or 'you') back where the AI saw only a placeholder."""
    if client:
        return text.replace(CLIENT, client)
    text = re.sub(r"\{CLIENT\}'s", "your", text)
    text = re.sub(r"(?i)(for|with|to|at) \{CLIENT\}", r"\1 you", text)
    return text.replace(CLIENT, "you")


# =========================================================================== voice
_NOWIN = 0x08000000 if sys.platform == "win32" else 0


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _speak_raw(text: str, out: Path, work: Path) -> bool:
    txt = work / (out.stem + ".txt")
    txt.write_text(text, encoding="utf-8")
    try:
        if sys.platform == "win32":
            q = lambda p: str(p).replace("'", "''")
            pick = (f"try {{ $s.SelectVoice('{q(settings.video_voice)}') }} catch {{}}" if settings.video_voice else
                    "$vs = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'en-*' }; "
                    "$pref = $vs | Where-Object { $_.VoiceInfo.Name -match 'Aria|Jenny|Zira|Hazel|Susan|Catherine' } | Select-Object -First 1; "
                    "if (-not $pref) { $pref = $vs | Select-Object -First 1 }; if ($pref) { $s.SelectVoice($pref.VoiceInfo.Name) }")
            script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; " + pick + "; "
                      f"$s.Rate = 0; $s.SetOutputToWaveFile('{q(out)}'); $t = Get-Content -Raw -Encoding UTF8 -LiteralPath '{q(txt)}'; "
                      "$s.Speak($t); $s.Dispose()")
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, timeout=120, creationflags=_NOWIN)
        elif sys.platform == "darwin":
            subprocess.run(["say", "-o", str(out.with_suffix(".aiff")), "-f", str(txt)], capture_output=True, timeout=120)
            if out.with_suffix(".aiff").exists():
                out.with_suffix(".aiff").rename(out)
        else:
            exe = shutil.which("espeak-ng") or shutil.which("espeak")
            if not exe:
                return False
            subprocess.run([exe, "-s", "160", "-w", str(out), "-f", str(txt)], capture_output=True, timeout=120)
    except Exception as e:
        log.info("Video voice failed: %s", e)
        return False
    return out.exists() and out.stat().st_size > 1000


def speak(text: str, out: Path, work: Path, ff: str) -> float | None:
    """Writes a 44.1 kHz mono WAV of the narration and returns its length in seconds (None = no voice available)."""
    raw = work / (out.stem + "_raw.wav")
    if not _speak_raw(text, raw, work):
        return None
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(raw), "-ar", str(RATE), "-ac", "1", "-sample_fmt", "s16", str(out)],
                   capture_output=True, timeout=120, creationflags=_NOWIN)
    if not out.exists():
        return None
    with wave.open(str(out), "rb") as w:
        return w.getnframes() / w.getframerate()


# =========================================================================== drawing helpers
_fonts: dict = {}


def font(size: int, weight: int = 400, serif: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, weight, serif)
    if key not in _fonts:
        path = FONT_DIR / ("Newsreader.ttf" if serif else "HankenGrotesk.ttf")
        try:
            f = ImageFont.truetype(str(path), size)
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
        except Exception:
            f = ImageFont.load_default(size)
        _fonts[key] = f
    return _fonts[key]


def wrap(text: str, f, width: int, max_lines: int = 99) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if f.getlength(t) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and f.getlength(lines[-1] + "…") > width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
        lines[-1] += "…"
    return lines


_cmaps: dict = {}
SWAP = {"≤": "up to ", "≥": "at least ", "→": "to", "←": "from", "×": "x", "•": "·", "✓": "", "≈": "about ", "€": "EUR ", "₹": "INR ",
        "\u00a0": " ", "\u2009": " "}


def safe(text: str, serif: bool = False) -> str:
    """Replace characters the bundled fonts can't draw (they'd show as empty boxes)."""
    key = "serif" if serif else "sans"
    if key not in _cmaps:
        try:
            from fontTools.ttLib import TTFont

            _cmaps[key] = set(TTFont(str(FONT_DIR / ("Newsreader.ttf" if serif else "HankenGrotesk.ttf"))).getBestCmap())
        except Exception:
            _cmaps[key] = None
    cm = _cmaps[key]
    out = []
    for ch in str(text):
        if cm is None or ord(ch) in cm or ch in "\n":
            out.append(ch)
        else:
            out.append(SWAP.get(ch, ""))
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


def spoken(text: str) -> str:
    """Narration as the voice should read it."""
    for a, b in (("≤", "up to "), ("≥", "at least "), ("%", " percent"), ("&", " and "), ("/", " "), ("·", ","), ("24x7", "24 by 7")):
        text = text.replace(a, b)
    return re.sub(r"\s{2,}", " ", text)


class Sprite:
    def __init__(self, img: Image.Image, ox: int = 0, oy: int = 0):
        self.img, self.ox, self.oy = img, ox, oy
        self._alpha: dict = {}

    @property
    def w(self):
        return self.img.width - 2 * self.ox

    @property
    def h(self):
        return self.img.height - 2 * self.oy

    def faded(self, a: float) -> Image.Image:
        q = round(max(0.0, min(1.0, a)) * 20)
        if q == 20:
            return self.img
        if q not in self._alpha:
            im = self.img.copy()
            im.putalpha(im.getchannel("A").point(lambda v, k=q / 20: int(v * k)))
            self._alpha[q] = im
        return self._alpha[q]


def text_sprite(text: str, f, color: str, width: int | None = None, max_lines: int = 99, spacing: float = 1.22, align: str = "left") -> Sprite:
    text = safe(text, serif="Newsreader" in str(getattr(f, "path", "")))
    lines = wrap(text, f, width, max_lines) if width else [text]
    asc, desc = f.getmetrics()
    lh = round(f.size * spacing)
    tw = max([math.ceil(f.getlength(l)) for l in lines] + [1])
    img = Image.new("RGBA", (tw + 4, lh * (len(lines) - 1) + asc + desc + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        x = (tw - f.getlength(l)) / 2 if align == "center" else 0
        d.text((x + 1, i * lh + 1), l, font=f, fill=color)
    return Sprite(img)


def box(w: int, h: int, r: int, fill: str, outline: str | None = None, width: int = 1, shadow: bool = False) -> Sprite:
    """Anti-aliased rounded rectangle (drawn at 2x, then reduced), optionally with a soft shadow."""
    pad = 18 if shadow else 0
    S = 2
    img = Image.new("RGBA", ((w + 2 * pad) * S, (h + 2 * pad) * S), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([pad * S, (pad + 6) * S, (pad + w) * S, (pad + h + 6) * S], r * S, fill=(8, 43, 61, 46))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(12 * S)))
    ImageDraw.Draw(img).rounded_rectangle([pad * S, pad * S, (pad + w) * S - 1, (pad + h) * S - 1], r * S, fill=fill,
                                          outline=outline, width=width * S if outline else 0)
    return Sprite(img.resize((w + 2 * pad, h + 2 * pad), Image.LANCZOS), pad, pad)


def tick_sprite(size: int, color: str, bg: str) -> Sprite:
    S = 4
    img = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, size * S - 1, size * S - 1], fill=bg)
    k = size * S
    d.line([(k * .28, k * .52), (k * .44, k * .68), (k * .74, k * .36)], fill=color, width=max(2, int(k * .1)), joint="curve")
    return Sprite(img.resize((size, size), Image.LANCZOS))


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def appear(t: float, at: float, dur: float = 0.55) -> float:
    return ease((t - at) / dur)


def put(frame: Image.Image, sp: Sprite, x: float, y: float, a: float = 1.0):
    if a <= 0.01:
        return
    frame.alpha_composite(sp.faded(a), (int(round(x - sp.ox)), int(round(y - sp.oy))))


def light_bg() -> Image.Image:
    img = Image.new("RGBA", (W, H), "#F7F9FB")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W - 520, -380, W + 380, 360], fill=(207, 232, 245, 150))
    return Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(90)))


def dark_bg() -> Image.Image:
    img = Image.new("RGBA", (W, H), C["b950"])
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse([W - 620, -300, W + 300, 520], fill=(17, 138, 195, 70))
    d.ellipse([-300, H - 260, 420, H + 380], fill=(245, 131, 58, 36))
    return Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(110)))


# =========================================================================== scenes
class Scene:
    dark = False
    items = 6

    def __init__(self, idx: int, f: dict, narr: dict, client: str):
        self.idx, self.f, self.narr, self.client = idx, f, narr, client
        self.bg = dark_bg() if self.dark else light_bg()
        self.mark = text_sprite(f["company"], font(17, 700), C["b100"] if self.dark else C["muted"])
        key = SCENES[idx]
        if key in KICKER:
            self.kicker = text_sprite(f"{idx:02d}  ·  {KICKER[key].upper()}", font(16, 700), C["b700"])
        self.build()

    def build(self):
        pass

    def header(self, frame, t, title: str):
        if not hasattr(self, "_head"):
            self._head = text_sprite(title, font(46, 500, serif=True), C["ink"], width=1000, max_lines=1)
        put(frame, self.kicker, 80, 60, appear(t, 0.0, 0.4))
        put(frame, self._head, 80, 86 + 14 * (1 - appear(t, 0.1)), appear(t, 0.1))

    def draw(self, frame, t: float, d: float):
        pass

    def at(self, i: int, d: float) -> float:
        """When element i starts: spread over the first ~55% of the scene so the screen keeps moving with the voice."""
        step = min(0.55, max(0.18, (d * 0.55 - 0.6) / max(1, self.items)))
        return 0.5 + i * step


class Intro(Scene):
    dark = True

    def build(self):
        f = self.f
        who = self.client or "you"
        self.kick = text_sprite(f"PROPOSAL FOR {who.upper()}", font(18, 700), C["e400"])
        self.title = text_sprite(f["title"], font(60, 500, serif=True), C["white"], width=1040, max_lines=3, spacing=1.12)
        self.sub = text_sprite(f"{f['company']}  ·  {datetime.now():%B %Y}", font(24, 500), C["b100"])

    def draw(self, frame, t, d):
        y = 300 - self.title.h / 2
        a = appear(t, 0.1, 0.7)
        ImageDraw.Draw(frame).rounded_rectangle([100, y - 70, 100 + int(130 * a), y - 64], 3, fill=C["e500"])
        put(frame, self.kick, 100, y - 50, appear(t, 0.25))
        put(frame, self.title, 100, y + 22 * (1 - appear(t, 0.45, 0.8)), appear(t, 0.45, 0.8))
        put(frame, self.sub, 100, y + self.title.h + 34, appear(t, 1.1))


class Needs(Scene):
    items = 8

    def build(self):
        f = self.f
        self.head = "What you asked for"
        self.lbl = text_sprite(f"requirements in your {f['doc_type']}, all answered", font(22, 500), C["soft"])
        cats = list(f["categories"].items())[:4]
        mx = max([n for _, n in cats] + [1])
        self.rows = []
        for i, (k, n) in enumerate(cats):
            self.rows.append((text_sprite(k, font(20, 600), C["ink"]), box(max(8, int(360 * n / mx)), 16, 8, CAT_COLOR.get(k, C["b500"])),
                              text_sprite(str(n), font(20, 700), C["b900"])))
        self.track = box(360, 16, 8, "#E6ECF0")
        self.cap = text_sprite("WHAT MATTERS MOST", font(15, 700), C["muted"])
        self.cards = []
        for i, need in enumerate(self.narr["needs"][:3]):
            self.cards.append((box(520, 96, 14, C["white"], C["line"], shadow=True), tick_sprite(34, C["white"], C["b500"]),
                               text_sprite(str(need), font(24, 600), C["ink"], width=420, max_lines=2)))

    def draw(self, frame, t, d):
        self.header(frame, t, self.head)
        n = self.f["requirements"]
        k = appear(t, 0.4, 1.4)
        ImageDraw.Draw(frame).text((80, 190), str(int(round(n * k))), font=font(112, 500, serif=True), fill=C["b900"])
        put(frame, self.lbl, 82, 320, appear(t, 0.6))
        for i, (lab, bar, num) in enumerate(self.rows):
            st = self.at(1 + i, d)
            a, y = appear(t, st), 380 + i * 52
            put(frame, lab, 82, y, a)
            put(frame, self.track, 250, y + 6, a)
            g = ease((t - st - 0.1) / 0.9)
            if g > 0:
                cw = max(1, int(bar.img.width * g))
                put(frame, Sprite(bar.img.crop((0, 0, cw, bar.img.height))), 250, y + 6, a)
            put(frame, num, 250 + 372, y, a)
        put(frame, self.cap, 680, 196, appear(t, self.at(1, d)))
        for i, (card, tk, txt) in enumerate(self.cards):
            st = self.at(3 + i, d)
            a = appear(t, st, 0.6)
            x = 680 + 40 * (1 - a)
            y = 228 + i * 118
            put(frame, card, x, y, a)
            put(frame, tk, x + 24, y + 31, a)
            put(frame, txt, x + 76, y + (96 - txt.h) / 2, a)


class Solution(Scene):
    items = 10

    def build(self):
        layers = self.f["layers"] or [{"layer": "Solution", "components": [{"name": "Designed around your requirements", "mandated": False}]}]
        n = len(layers)
        self.bh = min(66, int((410 - (n - 1) * 10) / n))
        self.bands = []
        for l in layers:
            chips = []
            for c in l["components"]:
                tx = text_sprite(c["name"], font(17, 600), C["b800"] if c["mandated"] else C["soft"], width=230, max_lines=1)
                chips.append((box(tx.w + 30, 36, 18, C["b50"] if c["mandated"] else C["white"], C["b500"] if c["mandated"] else C["line"]), tx))
            self.bands.append((box(1120, self.bh, 14, C["white"], C["line"], shadow=True), box(250, self.bh, 14, C["b50"]),
                               text_sprite(l["layer"], font(19, 700), C["b900"], width=220, max_lines=2, spacing=1.1), chips))
        self.items = n + 2
        self.leg = [(box(14, 14, 7, C["b50"], C["b500"]), text_sprite("Asked for in your RFP", font(15, 600), C["muted"])),
                    (box(14, 14, 7, C["white"], C["line"]), text_sprite("Proposed by us", font(15, 600), C["muted"]))]

    def draw(self, frame, t, d):
        self.header(frame, t, "Built in layers, traced to your needs")
        n = len(self.bands)
        for j, (band, lab_bg, lab, chips) in enumerate(self.bands):
            i = n - 1 - j  # build from the bottom layer up
            st = self.at(i, d)
            a = appear(t, st, 0.6)
            y = 180 + j * (self.bh + 10) + 18 * (1 - a)
            put(frame, band, 80, y, a)
            put(frame, lab_bg, 80, y, a)
            put(frame, lab, 102, y + (self.bh - lab.h) / 2, a)
            x = 350
            for k, (chip, tx) in enumerate(chips):
                ca = appear(t, st + 0.25 + k * 0.12, 0.4)
                if x + chip.w > 1185:
                    break
                cy = y + (self.bh - 36) / 2
                put(frame, chip, x, cy + 6 * (1 - ca), ca * a)
                put(frame, tx, x + 15, cy + (36 - tx.h) / 2 + 6 * (1 - ca), ca * a)
                x += chip.w + 12
        la = appear(t, self.at(n, d))
        x = 830
        for sw, tx in self.leg:
            put(frame, sw, x, 70, la)
            put(frame, tx, x + 22, 66, la)
            x += 22 + tx.w + 26


class Team(Scene):
    items = 9

    def build(self):
        f = self.f
        loc = ", ".join(f["locations"][:3]) or "Onsite and offshore"
        self.stats = [(str(f["headcount"]), "people on your programme"), (f"{f['years']}+" if f["years"] else "—", "years of combined experience"),
                      (str(len(f["locations"]) or 1), f"delivery locations · {loc}")]
        self.tiles = [(box(340, 128, 16, C["white"], C["line"], shadow=True), text_sprite(lbl, font(18, 500), C["soft"], width=300, max_lines=2))
                      for _, lbl in self.stats]
        self.rcap = text_sprite("ROLES", font(15, 700), C["muted"])
        self.roles = []
        for r in f["roles"][:8]:
            tx = text_sprite(f"{r['role']}" + (f"  ×{r['headcount']}" if r.get("headcount", 0) > 1 else ""), font(17, 600), C["ink"], width=230, max_lines=1)
            self.roles.append((box(262, 42, 10, C["white"], C["line"]), tx))
        self.scap = text_sprite("KEY SKILLS ON THE TEAM", font(15, 700), C["muted"])
        self.skills = []
        for s in f["skills"][:10]:
            tx = text_sprite(s, font(17, 600), C["b800"], width=220, max_lines=1)
            self.skills.append((box(tx.w + 30, 38, 19, C["b50"], C["b200"]), tx))

    def draw(self, frame, t, d):
        self.header(frame, t, "The team behind it")
        dr = ImageDraw.Draw(frame)
        for i, ((num, _), (tile, lbl)) in enumerate(zip(self.stats, self.tiles)):
            st = self.at(i, d)
            a = appear(t, st)
            x, y = 80 + i * 368, 182 + 14 * (1 - a)
            put(frame, tile, x, y, a)
            if a > 0.05:
                m = re.match(r"(\d+)(.*)", num)
                shown = f"{int(int(m.group(1)) * appear(t, st, 1.2))}{m.group(2)}" if m else num
                dr.text((x + 22, y + 10), shown, font=font(54, 500, serif=True), fill=C["b900"])
            put(frame, lbl, x + 24, y + 78, a)
        put(frame, self.rcap, 80, 342, appear(t, self.at(3, d)))
        for k, (bx, tx) in enumerate(self.roles):
            a = appear(t, self.at(3, d) + 0.1 + k * 0.1, 0.4)
            x, y = 80 + (k % 2) * 276, 370 + (k // 2) * 54
            put(frame, bx, x, y, a)
            put(frame, tx, x + 14, y + (42 - tx.h) / 2, a)
        put(frame, self.scap, 680, 342, appear(t, self.at(5, d)))
        x, y = 680, 370
        for k, (bx, tx) in enumerate(self.skills):
            if x + bx.w > 1200:
                x, y = 680, y + 50
            if y > 560:
                break
            a = appear(t, self.at(5, d) + 0.1 + k * 0.1, 0.4)
            put(frame, bx, x, y + 6 * (1 - a), a)
            put(frame, tx, x + 15, y + (38 - tx.h) / 2 + 6 * (1 - a), a)
            x += bx.w + 10


class Proof(Scene):
    items = 6

    def build(self):
        cs = self.f["case_studies"][:3]
        n = max(1, len(cs))
        self.cw = int((1120 - (n - 1) * 24) / n)
        self.cards = []
        for c in cs:
            meta = " · ".join(x for x in (c["industry"], c["region"], c["year"]) if x)
            self.cards.append((box(self.cw, 282, 18, C["white"], C["line"], shadow=True),
                               text_sprite(meta.upper(), font(14, 700), C["muted"], width=self.cw - 48, max_lines=1),
                               text_sprite(c["title"], font(27, 500, serif=True), C["ink"], width=self.cw - 48, max_lines=3, spacing=1.12),
                               text_sprite(c["outcome"] or "Delivered", font(21, 700), C["b900"], width=self.cw - 66, max_lines=2)))
        self.ccap = text_sprite("CERTIFIED", font(15, 700), C["muted"])
        self.certs = []
        for c in self.f["certifications"][:5]:
            tx = text_sprite(c, font(16, 600), C["ink"], width=300, max_lines=1)
            self.certs.append((box(tx.w + 52, 40, 20, C["white"], C["line"]), tick_sprite(22, C["white"], C["ok"]), tx))
        self.items = len(self.cards) + 2

    def draw(self, frame, t, d):
        self.header(frame, t, "We have done this before")
        dr = ImageDraw.Draw(frame)
        for i, (card, meta, title, out) in enumerate(self.cards):
            st = self.at(i, d)
            a = appear(t, st, 0.6)
            x, y = 80 + i * (self.cw + 24), 184 + 20 * (1 - a)
            put(frame, card, x, y, a)
            put(frame, meta, x + 24, y + 24, a)
            put(frame, title, x + 24, y + 52, a)
            g = appear(t, st + 0.5, 0.5)
            if g > 0.02:
                dr.rounded_rectangle([x + 24, y + 282 - 24 - out.h, x + 28, y + 282 - 24], 2, fill=C["e500"])
            put(frame, out, x + 40, y + 282 - 24 - out.h, g * a)
        if self.certs:
            st = self.at(len(self.cards), d)
            put(frame, self.ccap, 80, 500, appear(t, st))
            x = 80
            for k, (bx, tk, tx) in enumerate(self.certs):
                if x + bx.w > 1200:
                    break
                a = appear(t, st + 0.15 + k * 0.12, 0.4)
                put(frame, bx, x, 528, a)
                put(frame, tk, x + 10, 537, a)
                put(frame, tx, x + 40, 528 + (40 - tx.h) / 2, a)
                x += bx.w + 12


class Plan(Scene):
    items = 8

    def build(self):
        f = self.f
        ph = f["phases"] or [{"name": "Delivery", "weeks": 12, "start": 0}]
        self.total = max(p["start"] + p["weeks"] for p in ph) or 1
        self.bars = []
        for i, p in enumerate(ph):
            w = max(70, int(800 * p["weeks"] / self.total))
            col = [C["b900"], C["b500"], "#2F9FD3", C["b700"], C["e500"]][i % 5]
            self.bars.append((p, box(w, 40, 10, col), text_sprite(p["name"], font(17, 600), C["ink"], width=288, max_lines=1),
                              text_sprite(self._range(p), font(15, 700), C["white"])))
        self.out_lbl = [text_sprite(self._range(p), font(15, 700), C["b800"]) for p, *_ in self.bars]
        self.items = len(self.bars) + 3
        lines = [f"Designed to meet your target: {s}" for s in f["slas"][:3]] or [f"Deliverable: {x}" for x in f["deliverables"][:3]]
        self.ccap = text_sprite("OUR COMMITMENTS" if f["slas"] else "KEY DELIVERABLES", font(15, 700), C["muted"])
        self.commit = [(tick_sprite(26, C["white"], C["ok"]), text_sprite(x, font(20, 500), C["ink"], width=1040, max_lines=1)) for x in lines]

    def _range(self, p):
        a = 1 if p["start"] <= 0 else round(p["start"] / 4.345) + 1
        b = max(a, _months(p["start"] + p["weeks"]))
        return f"Month {a}" if a == b else f"Months {a}–{b}"

    def draw(self, frame, t, d):
        self.header(frame, t, f"Delivered in phases over {self.f['total_months']} months")
        dr = ImageDraw.Draw(frame)
        x0 = 384
        rows = len(self.bars)
        rh = min(58, int(260 / max(1, rows)))
        a0 = appear(t, 0.4)
        if a0 > 0:
            for k in range(5):
                gx = x0 + int(800 * k / 4)
                dr.line([(gx, 184), (gx, 184 + rows * rh + 6)], fill="#E3E9ED", width=1)
        for i, (p, bar, lab, rng) in enumerate(self.bars):
            st = self.at(i, d)
            a = appear(t, st)
            y = 190 + i * rh
            put(frame, lab, 80, y + (40 - lab.h) / 2, a)
            g = ease((t - st) / 0.9)
            if g > 0:
                bx = x0 + int(800 * p["start"] / self.total)
                cw = max(1, int(bar.img.width * g))
                put(frame, Sprite(bar.img.crop((0, 0, cw, bar.img.height))), bx, y, a)
                if bar.img.width >= rng.w + 24:
                    put(frame, rng, bx + 12, y + (40 - rng.h) / 2, appear(t, st + 0.6, 0.4))
                else:
                    put(frame, self.out_lbl[i], bx + bar.img.width + 10, y + (40 - rng.h) / 2, appear(t, st + 0.6, 0.4))
        if self.commit:
            st = self.at(len(self.bars) + 1, d)
            y0 = 190 + rows * rh + 40
            put(frame, self.ccap, 80, y0, appear(t, st))
            for k, (tk, tx) in enumerate(self.commit):
                a = appear(t, st + 0.2 + k * 0.25, 0.45)
                y = y0 + 32 + k * 44
                if y > 575:
                    break
                put(frame, tk, 80, y + 2, a)
                put(frame, tx, 118, y + (30 - tx.h) / 2, a)


class Close(Scene):
    dark = True

    def build(self):
        f = self.f
        who = self.client or "you"
        self.name = text_sprite(f["company"], font(64, 500, serif=True), C["white"], width=1080, max_lines=2, spacing=1.1)
        self.line = text_sprite(f"Ready to start with {who}.", font(28, 500), C["b100"], width=1080, max_lines=2)
        pts = [f"All {f['requirements']} requirements answered", f"A {f['headcount']}-person team ready to mobilise" if f["headcount"] else ""]
        if f["case_studies"]:
            pts.append(f"Proven in {len(f['case_studies'])} similar programmes")
        self.pts = [(tick_sprite(28, C["b950"], C["e400"]), text_sprite(p, font(24, 600), C["white"])) for p in pts if p]

    def draw(self, frame, t, d):
        a = appear(t, 0.1, 0.7)
        ImageDraw.Draw(frame).rounded_rectangle([100, 170, 100 + int(130 * a), 176], 3, fill=C["e500"])
        put(frame, self.name, 100, 200 + 18 * (1 - appear(t, 0.2, 0.8)), appear(t, 0.2, 0.8))
        y = 200 + self.name.h + 20
        put(frame, self.line, 100, y, appear(t, 0.7))
        for k, (tk, tx) in enumerate(self.pts):
            ka = appear(t, 1.2 + k * 0.35, 0.45)
            yy = y + 90 + k * 50
            put(frame, tk, 100, yy, ka)
            put(frame, tx, 142, yy + (28 - tx.h) / 2, ka)


SCENE_CLS = [Intro, Needs, Solution, Team, Proof, Plan, Close]


# =========================================================================== captions + render
def caption_chunks(text: str) -> list[str]:
    f = font(23, 500)
    out = []
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not s:
            continue
        if len(wrap(s, f, 1060)) <= 2:
            out.append(s)
            continue
        cur = ""
        for part in re.split(r"(?<=,)\s+", s):
            t2 = f"{cur} {part}".strip()
            if cur and len(wrap(t2, f, 1060)) > 2:
                out.append(cur)
                cur = part
            else:
                cur = t2
        if cur:
            out.append(cur)
    return out or [text]


def render(facts: dict, narr: dict, client: str, out: Path, progress=lambda pct, msg: None) -> dict:
    ff = ffmpeg_exe()
    if not ff:
        raise RuntimeError("The video encoder isn't installed. Run setup.bat (or pip install imageio-ffmpeg) and try again.")
    work = Path(tempfile.mkdtemp(prefix="rf-story-"))
    try:
        texts = [personalise(narr["scenes"][s], client) for s in SCENES]
        lead, tail = 0.35, 0.9
        clips, durs, voiced = [], [], 0
        for i, txt in enumerate(texts):
            progress(5 + i * 4, f"Recording the narration ({i + 1} of {len(texts)})")
            wav = work / f"s{i}.wav"
            L = speak(spoken(txt), wav, work, ff)
            if L is None:
                L = max(2.5, len(txt.split()) / 2.5)
                clips.append(None)
            else:
                voiced += 1
                clips.append(wav)
            durs.append(max(4.5, lead + L + tail))
            durs[-1] = math.ceil(durs[-1] * FPS) / FPS
        # one audio track, each scene's voice placed at its start
        total_frames = sum(round(d * FPS) for d in durs)
        full = work / "voice.wav"
        with wave.open(str(full), "wb") as o:
            o.setnchannels(1)
            o.setsampwidth(2)
            o.setframerate(RATE)
            for clip, d in zip(clips, durs):
                n = round(d * FPS) * RATE // FPS
                pcm = b""
                if clip:
                    with wave.open(str(clip), "rb") as w:
                        pcm = w.readframes(w.getnframes())
                body = b"\0\0" * int(lead * RATE) + pcm
                body = body[: n * 2]
                o.writeframes(body + b"\0\0" * (n - len(body) // 2))

        progress(35, "Animating the scenes")
        scenes = [cls(i, facts, narr, client) for i, cls in enumerate(SCENE_CLS)]
        cap_font = font(23, 500)
        caps = []
        for txt, d in zip(texts, durs):
            chunks = caption_chunks(txt)
            talk = max(0.5, d - lead - tail)
            total_chars = sum(len(c) for c in chunks) or 1
            t0, row = lead, []
            for c in chunks:
                L = talk * len(c) / total_chars
                row.append((t0, t0 + L, text_sprite(c, cap_font, C["white"], width=1060, max_lines=2, align="center")))
                t0 += L
            caps.append(row)
        band = Image.new("RGBA", (W, 112), (8, 43, 61, 0))
        bd = ImageDraw.Draw(band)
        for y in range(112):  # soft gradient so captions sit on any background
            bd.line([(0, y), (W, y)], fill=(8, 43, 61, int(225 * min(1, y / 40))))
        band_sp = Sprite(band)

        cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
               "-i", str(full), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
               "-shortest", "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NOWIN)
        done, prev_last, fade = 0, None, int(0.4 * FPS)
        try:
            for sc, d, row in zip(scenes, durs, caps):
                n = round(d * FPS)
                first = True
                for k in range(n):
                    t = k / FPS
                    frame = sc.bg.copy()
                    sc.draw(frame, t, d)
                    put(frame, sc.mark, W - 80 - sc.mark.w, 26 if sc.dark else 28, 0.9)
                    for (a, b, sp) in row:
                        if a - 0.05 <= t < b + 0.15:
                            put(frame, band_sp, 0, H - 112)
                            put(frame, sp, (W - sp.w) / 2, H - 22 - sp.h, min(1.0, (t - a + 0.05) / 0.15))
                            break
                    pg = int(W * (done + 1) / total_frames)
                    ImageDraw.Draw(frame).rectangle([0, H - 4, pg, H], fill=C["e500"])
                    rgb = frame.convert("RGB")
                    if prev_last is not None and k < fade:
                        rgb = Image.blend(prev_last, rgb, (k + 1) / fade)
                    proc.stdin.write(rgb.tobytes())
                    if k == n - 1:
                        prev_last = rgb
                    done += 1
                    if done % FPS == 0:
                        progress(35 + int(60 * done / total_frames), "Animating the scenes")
                    first = False
            proc.stdin.close()
            err = proc.stderr.read().decode(errors="replace")
            if proc.wait() != 0:
                raise RuntimeError(f"Video encoding failed: {err[-400:]}")
        except BrokenPipeError:
            err = proc.stderr.read().decode(errors="replace")
            raise RuntimeError(f"Video encoding failed: {err[-400:]}")
        return {"duration": round(total_frames / FPS, 1), "voice": voiced == len(texts), "narration": texts}
    finally:
        shutil.rmtree(work, ignore_errors=True)


# =========================================================================== jobs
_job_lock = threading.Lock()


def _stamp(db, deal_id: str) -> str:
    sts = db.scalars(select(DealStage).where(DealStage.deal_id == deal_id, DealStage.stage.in_(("architecture", "estimation", "proposal")))).all()
    ts = [s.updated_at for s in sts if s.updated_at]
    return max(ts).isoformat() if ts else ""


def find(db, tenant_id: str, deal_id: str) -> Document | None:
    for d in db.scalars(select(Document).where(Document.tenant_id == tenant_id, Document.kind == "story_video").order_by(Document.created_at.desc())):
        if (d.parsed or {}).get("deal_id") == deal_id:
            return d
    return None


def status(db, deal: Deal) -> dict:
    d = find(db, deal.tenant_id, deal.id)
    if not d:
        return {"status": "none"}
    p = d.parsed or {}
    ready = d.status == "ready" and Path(d.path or "").exists()
    return {"status": "ready" if ready else ("none" if d.status == "ready" else d.status), "pct": p.get("pct", 0), "message": p.get("message", ""),
            "duration": p.get("duration"), "voice": p.get("voice"), "engine": p.get("engine"), "error": d.error,
            "created_at": p.get("finished_at"), "stale": ready and p.get("stamp") != _stamp(db, deal.id), "size": d.size,
            "use_client_name": p.get("use_client_name", True)}


def start(db, deal: Deal, user_id: str, use_client_name: bool = True) -> None:
    d = find(db, deal.tenant_id, deal.id)
    if d and d.status == "running":
        raise RuntimeError("A video for this deal is already being made.")
    if not d:
        d = Document(tenant_id=deal.tenant_id, kind="story_video", filename="", path="", uploaded_by=user_id, parsed={"deal_id": deal.id})
        db.add(d)
    d.status, d.error = "running", ""
    d.parsed = {"deal_id": deal.id, "pct": 1, "message": "Queued", "use_client_name": use_client_name}
    db.commit()
    threading.Thread(target=_run, args=(d.id, deal.id, use_client_name), daemon=True, name="story-video").start()


def _run(doc_id: str, deal_id: str, use_client_name: bool) -> None:
    with _job_lock:  # one video at a time: rendering is CPU heavy
        db = SessionLocal()
        try:
            doc, deal = db.get(Document, doc_id), db.get(Deal, deal_id)
            llm.set_tenant(deal.tenant_id)

            def progress(pct, msg):
                doc.parsed = {**(doc.parsed or {}), "pct": pct, "message": msg}
                db.commit()

            progress(2, "Gathering the deal's facts")
            facts = build_facts(db, deal)
            stamp = _stamp(db, deal.id)
            progress(4, "Writing the narration")
            narr = write_narration(facts)
            client = (deal.client_name or "").strip() if use_client_name else ""
            out_dir = OUTPUT_DIR / deal.tenant_id / deal.id
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / "solution-story.mp4"
            tmp = out_dir / "solution-story.tmp.mp4"
            info = render(facts, narr, client, tmp, progress)
            os.replace(tmp, out)
            doc.path, doc.filename, doc.size, doc.status = str(out), out.name, out.stat().st_size, "ready"
            doc.parsed = {**(doc.parsed or {}), "pct": 100, "message": "Ready", "duration": info["duration"], "voice": info["voice"],
                          "engine": narr.get("engine"), "stamp": stamp, "finished_at": datetime.now(timezone.utc).isoformat(),
                          "narration": info["narration"]}
            db.commit()
        except Exception as e:
            log.exception("Proposal video failed")
            db.rollback()
            doc = db.get(Document, doc_id)
            if doc:
                doc.status, doc.error = "failed", str(e)[:500]
                doc.parsed = {**(doc.parsed or {}), "message": "Failed"}
                db.commit()
        finally:
            db.close()


def mark_interrupted() -> None:
    """Called at start-up: a video that was being made when the app stopped can't finish."""
    db = SessionLocal()
    try:
        for d in db.scalars(select(Document).where(Document.kind == "story_video", Document.status == "running")):
            d.status, d.error = "failed", "Making the video was interrupted by a restart. Generate it again."
        db.commit()
    finally:
        db.close()
