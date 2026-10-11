"""Lecture notes -> narrated video with word-by-word highlighting (Stage 1).

Usage: python make_video.py notes/lecture1.pdf
Needs: GEMINI_API_KEY env var, ffmpeg, fonts-dejavu-core.
"""
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 25
VOICE = os.getenv("TTS_VOICE", "en-US-AriaNeural")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_SCENES = int(os.getenv("MAX_SCENES", "25"))

BG = (18, 22, 38)
ACCENT = (96, 200, 255)
HL = (255, 214, 64)
WHITE = (245, 247, 252)
GRAY = (112, 124, 150)
DARK = (18, 22, 38)

FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

PROMPT = """You are an outstanding teacher making a video lecture from the lecture notes below.

Rules:
- Cover ALL the content in the notes. Do not skip topics.
- Explain every idea in very simple words, as if to a first-year student.
- Define each technical term the first time it appears, then use everyday analogies.
- Go through the notes in order, explaining word by word what each line means.
- Split into at most {max_scenes} scenes. Each scene has a short heading (max 6 words)
  and a narration of 40 to 60 words in plain spoken English.
- No bullet symbols, markdown, or special characters in the narration.
  Write formulas and symbols out in words (for example: delta G, plus, arrow).
- Start with a short intro scene and end with a short recap scene.

Return ONLY JSON in this shape:
{{"title": "...", "scenes": [{{"heading": "...", "narration": "..."}}]}}
"""


# ---------- 1. script from Gemini ----------
def gemini_script(path: Path) -> dict:
    key = os.environ["GEMINI_API_KEY"]
    parts = [{"text": PROMPT.format(max_scenes=MAX_SCENES)}]
    if path.suffix.lower() == ".pdf":
        data = base64.b64encode(path.read_bytes()).decode()
        parts.append({"inline_data": {"mime_type": "application/pdf", "data": data}})
    else:
        parts.append({"text": "LECTURE NOTES:\n" + path.read_text(errors="ignore")})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    r = None
    for attempt in range(4):
        r = requests.post(url, params={"key": key}, json=body, timeout=300)
        if r.status_code == 200:
            break
        print(f"Gemini error {r.status_code}: {r.text[:200]}")
        time.sleep(15 * (attempt + 1))
    r.raise_for_status()
    cand = r.json()["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in cand if not p.get("thought"))
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    script = json.loads(text)
    script["scenes"] = script["scenes"][:MAX_SCENES]
    return script


def clean(s: str) -> str:
    s = re.sub(r"[*_#`>]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------- 2. voice + word timings ----------
async def _synth(text: str, mp3: Path):
    import edge_tts

    try:
        comm = edge_tts.Communicate(text, VOICE, boundary="WordBoundary")
    except TypeError:  # older edge-tts already sends word boundaries
        comm = edge_tts.Communicate(text, VOICE)
    events = []
    with open(mp3, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                events.append({"text": ch["text"], "start": ch["offset"] / 1e7})
    return events


def synth(text: str, mp3: Path):
    for attempt in range(3):
        try:
            return asyncio.run(_synth(text, mp3))
        except Exception as e:  # network hiccup: retry
            print("TTS retry:", e)
            time.sleep(5)
    raise RuntimeError("TTS failed")


def audio_duration(mp3: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(mp3)], text=True)
    return float(out.strip())


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def align(tokens, events, dur):
    """Start time (seconds) for each displayed token."""
    n = len(tokens)
    st = [None] * n
    k = 0
    for i, t in enumerate(tokens):
        nt = norm(t)
        if not nt:
            continue
        for j in range(k, min(k + 4, len(events))):
            if norm(events[j]["text"]) == nt:
                st[i] = events[j]["start"]
                k = j + 1
                break
    pts = [(-1, 0.0)] + [(i, s) for i, s in enumerate(st) if s is not None] + [(n, dur)]
    out = [0.0] * n
    for (ia, sa), (ib, sb) in zip(pts, pts[1:]):
        for i in range(ia + 1, ib):
            out[i] = sa + (sb - sa) * (i - ia) / (ib - ia)
        if 0 <= ib < n:
            out[ib] = sb
    for i in range(1, n):
        out[i] = max(out[i], out[i - 1])
    return out


# ---------- 3. frames ----------
def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def layout(tokens, f, size):
    x0, x1, y0 = 70, W - 70, 190
    line_h = int(size * 1.6)
    space = f.getlength(" ")
    pos, x, y = [], x0, y0
    for t in tokens:
        w = f.getlength(t)
        if x + w > x1 and x > x0:
            x, y = x0, y + line_h
        pos.append((x, y, w))
        x += w + space
    return pos, y + line_h, line_h


def fit(tokens):
    for size in range(46, 21, -2):
        f = font(FONT_REG, size)
        pos, bottom, line_h = layout(tokens, f, size)
        if bottom <= H - 60:
            break
    return f, pos, line_h


def draw_frame(out, no, total, heading, tokens, pos, f, line_h, current):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((70, 48), heading, font=font(FONT_BOLD, 52), fill=ACCENT)
    d.text((W - 70, 60), f"Part {no}/{total}", font=font(FONT_REG, 26), fill=GRAY, anchor="ra")
    d.line((70, 150, W - 70, 150), fill=(60, 72, 104), width=3)
    for i, (t, (x, y, w)) in enumerate(zip(tokens, pos)):
        if i == current:
            d.rounded_rectangle((x - 7, y - 4, x + w + 7, y + line_h - 14), radius=9, fill=HL)
            d.text((x, y), t, font=f, fill=DARK)
        else:
            d.text((x, y), t, font=f, fill=WHITE if i < current else GRAY)
    frac = (current + 1) / len(tokens)
    d.rectangle((0, H - 14, W, H), fill=(40, 50, 76))
    d.rectangle((0, H - 14, int(W * frac), H), fill=ACCENT)
    img.save(out)


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------- 4. one scene -> mp4 ----------
def build_scene(idx, total, scene, work: Path) -> Path:
    heading = clean(scene["heading"])[:38]
    narration = clean(scene["narration"])
    tokens = narration.split()
    mp3 = work / f"s{idx}.mp3"
    events = synth(narration, mp3)
    dur = audio_duration(mp3)
    starts = align(tokens, events, dur)

    f, pos, line_h = fit(tokens)
    fdir = work / f"f{idx}"
    fdir.mkdir()
    for cur in range(-1, len(tokens)):
        draw_frame(fdir / f"{cur + 1}.png", idx, total, heading, tokens, pos, f, line_h, cur)

    # timeline: (frame, seconds)
    segs = [(0, max(starts[0], 0.05))]
    for i in range(len(tokens)):
        end = starts[i + 1] if i + 1 < len(tokens) else dur + 0.4
        segs.append((i + 1, max(end - starts[i], 0.04)))
    total_len = sum(s for _, s in segs)

    lst = work / f"l{idx}.txt"
    with open(lst, "w") as fh:
        for fr, secs in segs:
            fh.write(f"file '{(fdir / f'{fr}.png').resolve()}'\nduration {secs:.3f}\n")
        fh.write(f"file '{(fdir / f'{segs[-1][0]}.png').resolve()}'\n")

    out = work / f"scene{idx}.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(mp3),
         "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
         "-af", "apad", "-t", f"{total_len:.3f}", str(out)])
    for p in fdir.glob("*.png"):
        p.unlink()
    return out


def main():
    path = Path(sys.argv[1])
    work = Path("work") / path.stem
    work.mkdir(parents=True, exist_ok=True)
    Path("out").mkdir(exist_ok=True)

    print("Writing the lecture script...")
    script = gemini_script(path)
    scenes = script["scenes"]
    (work / "script.json").write_text(json.dumps(script, indent=2))
    print(f"{len(scenes)} scenes")

    clips = []
    for i, sc in enumerate(scenes, 1):
        print(f"Scene {i}/{len(scenes)}: {sc['heading']}")
        clips.append(build_scene(i, len(scenes), sc, work))

    final_list = work / "all.txt"
    final_list.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    final = Path("out") / f"{path.stem}.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(final_list),
         "-c", "copy", str(final)])
    print("Done:", final)


if __name__ == "__main__":
    main()
