"""Lecture notes -> animated chalkboard lecture taught by Professor Hoot (the owl).

Usage: python make_video.py notes/lecture1.pdf
Needs: GEMINI_API_KEY env var, ffmpeg. Files: board.py, owl.py, make_video.py
"""
import asyncio
import base64
import json
import math
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

from board import (BH, BW, BX, BY, H, W, DRAW, blank_board, clamp01, plan_pages,
                   render_board, reveal_seconds)
from owl import (blink_amount, caption_image, draw_owl, draw_pointer, make_base,
                 scene_base)

FPS = int(os.getenv("FPS", "15"))
SR = 24000
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
MAX_SCENES = int(os.getenv("MAX_SCENES", "45"))
SCENES_PER_PAGE = float(os.getenv("SCENES_PER_PAGE", "1.3"))
SPEECH_TEMPO = float(os.getenv("SPEECH_TEMPO", "0.95"))   # <1 = slower, calmer speech
EDGE_VOICE = os.getenv("TTS_VOICE", "en-GB-RyanNeural")
WIPE = 0.8

# ======================================================================
# 1. LECTURE SCRIPT (Gemini)
# ======================================================================
OUTLINE_PROMPT = """You are planning a long, engaging chalkboard video lecture taught by "Professor Hoot", a friendly owl teacher. Use ONLY the attached lecture notes.
Read ALL of the notes and split the lecture into %MINS% to %MAXS% sections that follow the order of the notes and together cover EVERYTHING in them.
Give each section a scene budget so that the total number of scenes is about %TARGET%.
Return ONLY JSON:
{"title":"lecture title","sections":[{"name":"short section name","covers":"specific list of what in the notes this section teaches","scenes":3}]}"""

SECTION_PROMPT = """You are Professor Hoot, a warm, funny, endlessly patient owl who teaches on a chalkboard in a video lecture. Use ONLY the attached lecture notes as your source of facts.

YOUR PART: section %I% of %N%: "%NAME%" - %COVERS%
Sections already taught before this one: %BEFORE%
Sections that come after (do not teach them yet): %AFTER%
Write exactly %K% scenes for your part.
%SPECIAL%

HOW TO TEACH
- Explain ideas, do not read the notes out. Say what it is, why it matters and how it works, and give a simple everyday analogy or example for every important idea.
- Be faithful: every fact, definition, name, number, formula, list and table must match the notes. You may add simple analogies and restatements, but no new facts, and never contradict the notes. Cover everything in your part of the notes.
- Sound human: short sentences, curiosity, small jokes, questions to the viewer. When you ask a question, the very next beat answers it.
- Take your time and go step by step, simple to complex. End each scene by restating its key point in one sentence.

SCENES AND BEATS
- A scene is one chalkboard topic with a short heading (max 6 words) and 3 to 6 beats.
- A beat is one thing Professor Hoot says (35 to 70 words) plus, optionally, one thing he writes or draws on the board while saying it.
- "say": plain spoken English, no markdown, no bullet symbols. Write acronyms and formulas the way they are spoken (for example "A T P", "D N A", "delta G", "H two O").
- "show": very short, correct board text (labels, key terms, formulas). Never copy long sentences onto the board.

BOARD ELEMENTS for "show" (pick the best one for the idea, or null):
{"type":"bullet","text":"short key point","hot":false}   (hot=true only for the single most important point of a scene)
{"type":"term","term":"Word","meaning":"simple meaning"}
{"type":"equation","text":"E + S \u21cc ES \u2192 E + P"}   (arrows and subscripts allowed)
{"type":"flow","nodes":["step 1","step 2","step 3"]}   (2 to 5 short steps: a process or pathway)
{"type":"cycle","nodes":["a","b","c","d"],"center":"cycle name"}   (3 to 6 nodes)
{"type":"hub","center":"main idea","nodes":["part","part","part"]}   (3 to 6 items: types, parts, groups)
{"type":"compare","left_title":"A","right_title":"B","left":["point","point"],"right":["point","point"]}
{"type":"table","columns":["col 1","col 2","col 3"],"rows":[["a","b","c"]]}   (2 to 4 columns, max 5 rows; use when the notes contain a table)
{"type":"curve","kind":"saturation","x_label":"Substrate","y_label":"Rate","note":"Vmax"}   (kind is one of: saturation, sigmoid, bell, decay, linear)
Mix element types, because diagrams make learning easier. At most 4 board elements per scene.

Return ONLY JSON: {"scenes":[{"heading":"...","beats":[{"say":"...","show":null}]}]}"""

FIRST_SPECIAL = ("This is the FIRST section: scene 1 opens with a friendly hook (a surprising question or "
                 "a tiny story) and then a 'what we will learn' board (a hub or flow of the main topics).")
LAST_SPECIAL = ("This is the LAST section: the final scene recaps the whole lecture (a hub or flow of the key "
                "ideas), gives one memorable mnemonic or takeaway, and ends with a warm sign-off.")


def notes_parts(path: Path):
    if path.suffix.lower() == ".pdf":
        data = base64.b64encode(path.read_bytes()).decode()
        return [{"inline_data": {"mime_type": "application/pdf", "data": data}}]
    return [{"text": "LECTURE NOTES:\n" + path.read_text(errors="ignore")}]


def count_pages(path: Path) -> int:
    try:
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            return max(1, len(PdfReader(str(path)).pages))
        return max(1, len(path.read_text(errors="ignore").split()) // 350)
    except Exception:
        return 15


def parse_json(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    try:
        return json.loads(text)
    except Exception:
        a, b = text.find("{"), text.rfind("}")
        return json.loads(text[a:b + 1])


def gemini(parts, retries=6):
    key = os.environ["GEMINI_API_KEY"]
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.5}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    for attempt in range(retries):
        try:
            r = requests.post(url, params={"key": key}, json=body, timeout=600)
            if r.status_code == 200:
                out = r.json()["candidates"][0]["content"]["parts"]
                return parse_json("".join(p.get("text", "") for p in out if not p.get("thought")))
            print(f"Gemini {r.status_code}: {r.text[:160]}")
        except Exception as e:
            print("Gemini problem:", str(e)[:160])
        time.sleep(min(20 * (attempt + 1), 90))
    raise RuntimeError("Gemini kept failing")


def fill(prompt, **kw):
    for k, v in kw.items():
        prompt = prompt.replace(f"%{k}%", str(v))
    return prompt


# ---- cleaning / validating what Gemini returns ----
def clean(s, limit=None):
    s = str(s or "")
    s = (s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"')
         .replace("\u201d", '"').replace("\u2013", "-").replace("\u2014", "-").replace("\u2026", "..."))
    s = re.sub(r"[*_#`]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit].rstrip() if limit else s


def strs(v, n, limit):
    return [clean(x, limit) for x in (v if isinstance(v, list) else []) if clean(x)][:n]


def sanitize_show(show):
    if not isinstance(show, dict):
        return None
    t = str(show.get("type", "")).lower()
    try:
        if t == "bullet" and clean(show.get("text")):
            return {"type": "bullet", "text": clean(show["text"], 110), "hot": bool(show.get("hot"))}
        if t == "term" and clean(show.get("term")) and clean(show.get("meaning")):
            return {"type": "term", "term": clean(show["term"], 40), "meaning": clean(show["meaning"], 150)}
        if t == "equation" and clean(show.get("text")):
            return {"type": "equation", "text": clean(show["text"], 70)}
        if t == "flow":
            nodes = strs(show.get("nodes"), 5, 30)
            if len(nodes) >= 2:
                return {"type": "flow", "nodes": nodes}
        if t == "cycle":
            nodes = strs(show.get("nodes"), 6, 26)
            if len(nodes) >= 3:
                return {"type": "cycle", "nodes": nodes, "center": clean(show.get("center"), 26)}
        if t == "hub":
            nodes = strs(show.get("nodes"), 6, 26)
            if len(nodes) >= 3 and clean(show.get("center")):
                return {"type": "hub", "nodes": nodes, "center": clean(show["center"], 28)}
        if t == "compare":
            l, r = strs(show.get("left"), 4, 60), strs(show.get("right"), 4, 60)
            if l and r:
                return {"type": "compare", "left_title": clean(show.get("left_title"), 24) or "A",
                        "right_title": clean(show.get("right_title"), 24) or "B", "left": l, "right": r}
        if t == "table":
            cols = strs(show.get("columns"), 4, 22)
            rows = []
            for row in (show.get("rows") or [])[:5]:
                if isinstance(row, list):
                    cells = [clean(c, 30) for c in row][:len(cols)]
                    rows.append(cells + [""] * (len(cols) - len(cells)))
            if len(cols) >= 2 and rows:
                return {"type": "table", "columns": cols, "rows": rows}
        if t == "curve":
            kind = str(show.get("kind", "saturation")).lower()
            if kind not in ("saturation", "sigmoid", "bell", "decay", "linear"):
                kind = "saturation"
            return {"type": "curve", "kind": kind, "x_label": clean(show.get("x_label"), 22) or "x",
                    "y_label": clean(show.get("y_label"), 22) or "y", "note": clean(show.get("note"), 26)}
    except Exception:
        pass
    txt = clean(show.get("text") or show.get("term") or show.get("center") or "", 110)
    return {"type": "bullet", "text": txt, "hot": False} if txt else None


def sanitize_scene(sc):
    beats = []
    for b in (sc.get("beats") or []):
        say = clean(b.get("say"))
        if len(say.split()) < 4:
            continue
        beats.append({"say": say, "show": sanitize_show(b.get("show"))})
    if not beats:
        return None
    return {"heading": clean(sc.get("heading"), 56) or "Let's learn", "beats": beats}


def make_script(path: Path) -> dict:
    notes = notes_parts(path)
    pages = count_pages(path)
    target = int(max(8, min(MAX_SCENES, round(pages * SCENES_PER_PAGE))))
    print(f"Notes: about {pages} pages -> aiming for about {target} scenes")

    outline = gemini([{"text": fill(OUTLINE_PROMPT, MINS=max(3, target // 7), MAXS=max(5, target // 3),
                                    TARGET=target)}] + notes)
    sections = outline["sections"]
    budget = [max(1, min(8, int(s.get("scenes", 3)))) for s in sections]
    while sum(budget) > MAX_SCENES:
        budget[budget.index(max(budget))] -= 1
    print("Outline:", [(s["name"], b) for s, b in zip(sections, budget)])

    scenes = []
    names = [s["name"] for s in sections]
    for i, (sec, k) in enumerate(zip(sections, budget)):
        special = (FIRST_SPECIAL if i == 0 else "") + (" " + LAST_SPECIAL if i == len(sections) - 1 else "")
        prompt = fill(SECTION_PROMPT, I=i + 1, N=len(sections), NAME=sec["name"], COVERS=sec.get("covers", ""),
                      BEFORE=", ".join(names[:i]) or "none", AFTER=", ".join(names[i + 1:]) or "none",
                      K=k, SPECIAL=special.strip())
        print(f"Writing section {i + 1}/{len(sections)}: {sec['name']}")
        got = []
        for attempt in range(3):
            data = gemini([{"text": prompt}] + notes)
            lst = data.get("scenes") if isinstance(data, dict) else data
            got = [x for x in (sanitize_scene(sc) for sc in (lst or [])) if x]
            if got:
                break
        scenes += got
        time.sleep(3)
    return {"title": clean(outline.get("title"), 80), "scenes": scenes}


# ======================================================================
# 2. VOICE
# ======================================================================
PIPER_BASE = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
              "en/en_US/lessac/medium/en_US-lessac-medium")
_engine = "piper" if os.getenv("TTS_ENGINE", "").lower() == "piper" else None
_piper = None
_tmp = Path("work")


async def _edge(text, mp3):
    import edge_tts
    comm = edge_tts.Communicate(text, EDGE_VOICE, rate="-4%")
    with open(mp3, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])


def ensure_piper_voice() -> Path:
    d = Path("voices")
    d.mkdir(exist_ok=True)
    for ext in (".onnx", ".onnx.json"):
        p = d / f"en_US-lessac-medium{ext}"
        if not p.exists():
            r = requests.get(PIPER_BASE + ext, timeout=300)
            r.raise_for_status()
            p.write_bytes(r.content)
    return d / "en_US-lessac-medium.onnx"


def piper_wav(text, wav_path: Path):
    global _piper
    model = ensure_piper_voice()
    try:
        if _piper is None:
            from piper import PiperVoice
            _piper = PiperVoice.load(str(model))
        with wave.open(str(wav_path), "wb") as wf:
            if hasattr(_piper, "synthesize_wav"):
                _piper.synthesize_wav(text, wf)
            else:
                _piper.synthesize(text, wf)
        if wav_path.stat().st_size > 2000:
            return
    except Exception as e:
        print("Piper python API failed, using command line:", str(e)[:100])
    subprocess.run([sys.executable, "-m", "piper", "-m", str(model), "-f", str(wav_path)],
                   input=text.encode(), check=True)


def decode_audio(path: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-af", f"atempo={SPEECH_TEMPO}",
                          "-ar", str(SR), "-ac", "1", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.int16)


def speak(text: str) -> np.ndarray:
    global _engine
    _tmp.mkdir(exist_ok=True)
    spoken = text.replace("\u2192", " to ").replace("&", " and ")
    if _engine is None:
        try:
            asyncio.run(_edge("Hello there.", _tmp / "probe.mp3"))
            _engine = "edge"
        except Exception as e:
            print("Microsoft voice unavailable, using Piper:", str(e)[:100])
            _engine = "piper"
    if _engine == "edge":
        for attempt in range(2):
            try:
                mp3 = _tmp / "beat.mp3"
                asyncio.run(_edge(spoken, mp3))
                return decode_audio(mp3)
            except Exception as e:
                print("Edge voice problem:", str(e)[:100])
                time.sleep(2)
    wav = _tmp / "beat.wav"
    piper_wav(spoken, wav)
    return decode_audio(wav)


# ======================================================================
# 3. ANIMATION
# ======================================================================
def wipe_image(old, new, prog):
    prog = clamp01(prog)
    prog = prog * prog * (3 - 2 * prog)
    sx = int((BW + 60) * prog) - 30
    img = new.copy()
    if sx < BW:
        cx = max(0, sx)
        img.paste(old.crop((cx, 0, BW, BH)), (cx, 0))
    d = ImageDraw.Draw(img)
    ey = BH // 2 - 80 + int(55 * math.sin(prog * 20))
    d.rounded_rectangle((sx - 40, ey, sx + 32, ey + 150), radius=10, fill=(58, 42, 34))
    d.rectangle((sx - 34, ey + 108, sx + 26, ey + 144), fill=(232, 226, 208))
    return img


def mouth_envelope(samples, nframes):
    hop = SR / FPS
    x = samples.astype(np.float32)
    env = np.zeros(nframes)
    for f in range(nframes):
        seg = x[int(f * hop):int((f + 1) * hop)]
        env[f] = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    loud = env[env > 300]
    ref = float(np.percentile(loud, 80)) if len(loud) else 1.0
    m = np.clip(env / ref, 0, 1) ** 0.9
    out = np.zeros(nframes)
    for f in range(nframes):
        out[f] = max(m[f], out[f - 1] * 0.55 if f else 0.0)
    return out


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for p in parts:
        if len(p) > 150 and ", " in p:
            mid = len(p) // 2
            cut = min([m.end() for m in re.finditer(", ", p)], key=lambda e: abs(e - mid))
            out += [p[:cut].strip(), p[cut:].strip()]
        else:
            out.append(p)
    return [p for p in out if p]


def build_scene(idx, total, scene, st, work: Path) -> Path:
    heading, beats = scene["heading"], scene["beats"]
    els = []
    for bi, b in enumerate(beats):
        if b["show"]:
            el = dict(b["show"])
            el["_beat"] = bi
            els.append(el)
    npages = plan_pages(els) if els else 1

    # ---- voice + timeline ----
    speech = [speak(b["say"]) for b in beats]
    wipe_in = WIPE if st["prev_board"] is not None else 0.0
    intro = wipe_in + 1.0
    t = intro
    chunks = [np.zeros(int(intro * SR), dtype=np.int16)]
    btimes, caps = [], []
    for bi, b in enumerate(beats):
        dur = len(speech[bi]) / SR
        lead = 0.3
        gap = 1.9 if b["say"].rstrip().endswith("?") else 0.75
        start, sstart = t, t + lead
        chunks += [np.zeros(int(lead * SR), dtype=np.int16), speech[bi], np.zeros(int(gap * SR), dtype=np.int16)]
        btimes.append((start, sstart, dur))
        sents = split_sentences(b["say"])
        tot = sum(len(s) for s in sents)
        c = sstart
        for s in sents:
            d = dur * len(s) / tot
            caps.append((c, c + d, s))
            c += d
        t = sstart + dur + gap
    total_t = t + 0.6
    chunks.append(np.zeros(int(0.6 * SR), dtype=np.int16))
    nframes = int(math.ceil(total_t * FPS))
    need = int(round(nframes / FPS * SR))
    samples = np.concatenate(chunks)
    samples = np.pad(samples, (0, max(0, need - len(samples))))[:need]
    wav = work / f"scene{idx}.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(samples.tobytes())
    mouth = mouth_envelope(samples, nframes)

    # ---- when things appear ----
    page_wipe = {}
    seen = set()
    for el in els:
        start, sstart, dur = btimes[el["_beat"]]
        pg = el["_page"]
        if pg > 0 and pg not in seen:
            page_wipe[pg] = start
            el["_t0"] = start + WIPE + 0.1
        else:
            el["_t0"] = start + 0.2
        seen.add(pg)
        el["_rev"] = reveal_seconds(el, dur)
    pages = [[e for e in els if e["_page"] == k] for k in range(npages)]

    blank = blank_board()
    head_only, _ = render_board(heading, 1.0, [], marker=False)
    page_final = {}

    def final_of(k):
        if k not in page_final:
            page_final[k] = render_board(heading, 1.0, [(e, 1.0) for e in pages[k]], marker=False)[0]
        return page_final[k]

    sbase = scene_base(st["base"], idx, total)
    out = work / f"scene{idx}.mp4"
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    cache = {"sig": None, "img": None, "my": 34}
    tip = st["tip"]
    board = blank
    for f in range(nframes):
        t = f / FPS
        latest_t0 = -9.0
        wiping = None
        if t < wipe_in:
            wiping = (st["prev_board"], blank, t / WIPE)
            sig = ("w0", f)
        elif t < intro:
            hp = (t - wipe_in) / 1.0
            sig = ("h", round(hp, 3))
        else:
            k = 0
            for pg in range(1, npages):
                if pg in page_wipe and t >= page_wipe[pg]:
                    k = pg
            if k > 0 and t < page_wipe[k] + WIPE:
                wiping = (final_of(k - 1), head_only, (t - page_wipe[k]) / WIPE)
                sig = ("wp", f)
            else:
                vis = [(e, clamp01((t - e["_t0"]) / e["_rev"])) for e in pages[k] if e["_t0"] <= t]
                if vis:
                    latest_t0 = vis[-1][0]["_t0"]
                sig = ("p", k, tuple((id(e), round(p, 3)) for e, p in vis))
        if wiping:
            board = wipe_image(*wiping)
            my = cache["my"]
        elif cache["sig"] == sig:
            board, my = cache["img"], cache["my"]
        else:
            if sig[0] == "h":
                board, my = render_board(heading, hp, [])
            else:
                board, my = render_board(heading, 1.0, vis)
            cache.update(sig=sig, img=board, my=my)
        st["last_board"] = board

        target = (BX + 12, BY + my)
        tip = (tip[0] + (target[0] - tip[0]) * 0.28, tip[1] + (target[1] - tip[1]) * 0.28)
        hop = 12 * math.sin(math.pi * clamp01((t - latest_t0) / 0.35)) if 0 <= t - latest_t0 < 0.35 else 0
        look = (max(-1, min(1, (tip[0] - 170) / 200)), max(-1, min(1, (tip[1] - 360) / 200)))

        frame = sbase.copy()
        frame.paste(board, (BX, BY))
        hand = draw_owl(frame, t, float(mouth[f]), blink_amount(t), look, tip, hop)
        draw_pointer(frame, hand, tip)
        for c0, c1, s in caps:
            if c0 <= t < c1:
                ci = caption_image(s)
                frame.paste(ci, (60, 712 - ci.size[1]), ci)
                break
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed for scene " + str(idx))
    st["prev_board"] = board
    st["tip"] = tip
    return out


def main():
    path = Path(sys.argv[1])
    work = Path("work") / path.stem
    work.mkdir(parents=True, exist_ok=True)
    Path("out").mkdir(exist_ok=True)

    print("Professor Hoot is preparing the lecture...")
    script = make_script(path)
    (work / "script.json").write_text(json.dumps(script, indent=2))
    scenes = script["scenes"]
    if not scenes:
        raise RuntimeError("No scenes were written")
    print(f"{len(scenes)} scenes, {sum(len(s['beats']) for s in scenes)} beats")

    st = {"base": make_base(), "prev_board": None, "tip": (BX + 12, BY + 40)}
    clips = []
    for i, sc in enumerate(scenes, 1):
        t0 = time.time()
        for attempt in range(2):
            try:
                clips.append(build_scene(i, len(scenes), sc, st, work))
                break
            except Exception as e:
                print(f"Scene {i} problem ({e}); retrying" if attempt == 0 else "")
                if attempt == 1:
                    raise
        print(f"Scene {i}/{len(scenes)} done in {time.time() - t0:.0f}s: {sc['heading']}", flush=True)

    lst = work / "all.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    final = Path("out") / f"{path.stem}.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(final)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Done:", final)


if __name__ == "__main__":
    main()
