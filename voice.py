"""Voiceover- TTS chain, best engine first (config tts.engine_order):

  chatterbox (Resemble AI, MIT- beat ElevenLabs 65.3/24.5 in blind tests; emotion
              exaggeration + cfg pacing knobs; CUDA on the RTX 3060)
  -> kokoro  (Kokoro-82M ONNX, Apache- top-rated local narration, ~5x realtime CPU,
              bundled in tools/kokoro/- the offline/dry-run default)
  -> edge-tts (free MS neural, online- REAL word-boundary timings)
  -> piper   (bundled offline, phrase-split at punctuation)
  -> pyttsx3 -> captions-only.

The hook is NEVER spoken- it's a brief silent title card (config video.hook_seconds);
VO covers beats + CTA only. Word timing indices start at sentence 1 (the hook is 0).
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import wave
from pathlib import Path

from contracts import Script
from theme import ROOT, config, ffmpeg_exe

PIPER_EXE = ROOT / "tools" / "piper" / "piper" / "piper.exe"
PIPER_MODEL = ROOT / "tools" / "piper" / "en_GB-alan-medium.onnx"
PAUSE_COMMA = 0.24   # inserted at , ; : - when piper renders phrase-by-phrase
GAP_SENTENCE = 0.15  # extra tail after each sentence part


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def _role(sentence: str, is_cta: bool) -> str:
    if is_cta:
        return "cta"
    return "numbers" if re.search(r"\d", sentence) else "beat"


# ── edge-tts: neural prosody + real word boundaries ──────────────────────────
async def _edge_one(text: str, out_mp3: Path, voice: str, rate: str) -> list[dict]:
    import edge_tts
    words = []
    comm = edge_tts.Communicate(text, voice=voice, rate=rate)
    with open(out_mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({"word": chunk["text"],
                              "start": chunk["offset"] / 1e7,
                              "end": (chunk["offset"] + chunk["duration"]) / 1e7})
    return words


def _edge_sentence(text: str, out_wav: Path, role: str) -> tuple[float, list[dict]] | None:
    cfg = config()["tts"]
    voice = cfg.get("edge_voice", "en-US-ChristopherNeural")
    rate = cfg.get("edge_rate_by_role", {}).get(role, "-6%")
    mp3 = out_wav.with_suffix(".mp3")
    try:
        words = asyncio.run(_edge_one(text, mp3, voice, rate))
        if not mp3.exists() or mp3.stat().st_size < 500:
            return None
        subprocess.run([ffmpeg_exe(), "-y", "-i", str(mp3), "-ar", "24000", "-ac", "1",
                        str(out_wav)], capture_output=True, check=True)
        mp3.unlink()
        return _wav_seconds(out_wav), words
    except Exception:
        return None


# ── piper: offline, phrase-split so punctuation actually lands ───────────────
def _piper_raw(text: str, out: Path) -> bool:
    try:
        scale = str(config()["tts"].get("piper_length_scale", 1.08))
        r = subprocess.run(
            [str(PIPER_EXE), "--model", str(PIPER_MODEL), "--length_scale", scale,
             "--output_file", str(out)],
            input=text.encode("utf-8"), capture_output=True, timeout=120)
        return r.returncode == 0 and out.exists()
    except Exception:
        return False


def _piper_sentence(text: str, out_wav: Path, workdir: Path, idx: int) -> tuple[float, list[dict]] | None:
    """Split at , ; : - synth each phrase, join with real pauses- the ebb and flow
    piper won't do on its own. Word timings proportional within each measured phrase."""
    phrases = [p.strip() for p in re.split(r"[,;:](?:\s|$)", text) if p.strip()]
    if not phrases:
        return None
    import numpy as np
    pieces, rate, sw, ch = [], None, None, None
    for j, ph in enumerate(phrases):
        p = workdir / f"ph_{idx:02d}_{j}.wav"
        if not _piper_raw(ph, p):
            return None
        with wave.open(str(p), "rb") as wi:
            if rate is None:
                rate, sw, ch = wi.getframerate(), wi.getsampwidth(), wi.getnchannels()
            data = np.frombuffer(wi.readframes(wi.getnframes()), dtype=np.int16)
        pieces.append((ph, data))
        p.unlink()
    pause = np.zeros(int(PAUSE_COMMA * rate) * ch, dtype=np.int16)
    words, chunks, t = [], [], 0.0
    for j, (ph, data) in enumerate(pieces):
        dur = len(data) / (rate * ch)
        ws = ph.split()
        weights = [max(len(w), 2) for w in ws]
        tw = sum(weights)
        for w, wt in zip(ws, weights):
            d = dur * wt / tw
            words.append({"word": w, "start": round(t, 3), "end": round(t + d, 3)})
            t += d
        chunks.append(data)
        if j < len(pieces) - 1:
            chunks.append(pause)
            t += PAUSE_COMMA
    with wave.open(str(out_wav), "wb") as wo:
        wo.setnchannels(ch)
        wo.setsampwidth(sw)
        wo.setframerate(rate)
        wo.writeframes(np.concatenate(chunks).tobytes())
    return _wav_seconds(out_wav), words


# ── kokoro: Kokoro-82M ONNX, local, Apache- the quality/reliability sweet spot ─
_KOKORO = None


def _kokoro_sentence(text: str, out_wav: Path, role: str) -> tuple[float, list[dict]] | None:
    global _KOKORO
    cfg = config()["tts"]
    try:
        if _KOKORO is None:
            from kokoro_onnx import Kokoro
            _KOKORO = Kokoro(str(ROOT / cfg["kokoro_model"]), str(ROOT / cfg["kokoro_voices"]))
        speed = float(cfg.get("kokoro_speed_by_role", {}).get(role, 0.95))
        samples, sr = _KOKORO.create(text, voice=cfg.get("kokoro_voice", "am_michael"),
                                     speed=speed, lang="en-us")
        import numpy as np
        pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
        with wave.open(str(out_wav), "wb") as wo:
            wo.setnchannels(1)
            wo.setsampwidth(2)
            wo.setframerate(sr)
            wo.writeframes(pcm.tobytes())
        return _wav_seconds(out_wav), None
    except Exception:
        return None


# ── chatterbox: MIT, most natural- emotion + pacing knobs, CUDA ────────────────
_CHATTERBOX = None


def _chatterbox_sentence(text: str, out_wav: Path, role: str) -> tuple[float, list[dict]] | None:
    global _CHATTERBOX
    cfg = config()["tts"]
    try:
        import torch
        if not torch.cuda.is_available():
            return None  # CPU chatterbox is minutes/sentence- not worth it
        if _CHATTERBOX is None:
            from chatterbox.tts import ChatterboxTTS
            _CHATTERBOX = ChatterboxTTS.from_pretrained(device="cuda")
        exag = float(cfg.get("chatterbox_exaggeration", 0.55))
        cfgw = float(cfg.get("chatterbox_cfg", 0.4))
        if role == "numbers":
            cfgw = max(0.25, cfgw - 0.1)  # slower, more deliberate on the money line
        wav = _CHATTERBOX.generate(text, exaggeration=exag, cfg_weight=cfgw)
        import numpy as np
        pcm = (np.clip(wav.squeeze(0).cpu().numpy(), -1, 1) * 32767).astype(np.int16)
        with wave.open(str(out_wav), "wb") as wo:  # write directly- torchaudio.save needs a backend Windows lacks
            wo.setnchannels(1)
            wo.setsampwidth(2)
            wo.setframerate(_CHATTERBOX.sr)
            wo.writeframes(pcm.tobytes())
        return _wav_seconds(out_wav), None
    except Exception:
        return None


def _try_engine(name: str, sentences: list[str], roles: list[str], workdir: Path):
    synth = {"chatterbox": _chatterbox_sentence, "kokoro": _kokoro_sentence,
             "edge": _edge_sentence}.get(name)
    if name == "piper":
        parts = []
        for i, s in enumerate(sentences):
            got = _piper_sentence(s, workdir / f"vo_{i:02d}.wav", workdir, i)
            if got is None:
                return None
            parts.append((workdir / f"vo_{i:02d}.wav", got[0], got[1]))
        return parts
    parts = []
    for i, (s, role) in enumerate(zip(sentences, roles)):
        got = synth(s, workdir / f"vo_{i:02d}.wav", role)
        if got is None:
            return None
        parts.append((workdir / f"vo_{i:02d}.wav", got[0], got[1]))
    return parts


# ── the chain ────────────────────────────────────────────────────────────────
def render_parts(script: Script, workdir: Path, offline: bool = False) -> dict:
    """Per-sentence TTS for beats + CTA (hook is silent).
    Returns {'parts': [(path|None, duration, words_rel|None)], 'engine': str, 'sentences': [...]}."""
    workdir.mkdir(parents=True, exist_ok=True)
    sentences = list(script.beats) + [script.cta]
    roles = [_role(s, i == len(sentences) - 1) for i, s in enumerate(sentences)]

    order = config()["tts"].get("engine_order", ["chatterbox", "kokoro", "edge", "piper"])
    if offline:  # dry-run stays zero-network: only engines bundled on disk
        order = [e for e in order if e in ("kokoro", "piper")]
    for engine in order:
        parts = _try_engine(engine, sentences, roles, workdir)
        if parts:
            return {"parts": parts, "engine": engine, "sentences": sentences}

    try:  # last-resort robotic voice
        import pyttsx3
        parts = []
        for i, s in enumerate(sentences):
            eng = pyttsx3.init()
            p = workdir / f"vo_{i:02d}.wav"
            eng.save_to_file(s, str(p))
            eng.runAndWait()
            if not p.exists():
                raise RuntimeError
            parts.append((p, _wav_seconds(p), None))
        return {"parts": parts, "engine": "pyttsx3", "sentences": sentences}
    except Exception:
        pass

    durs = [max(1.6, len(s.split()) / 2.6) for s in sentences]
    return {"parts": [(None, d, None) for d in durs], "engine": "captions-only",
            "sentences": sentences}


def place_parts(parts_info: dict, starts: list[float], total: float, workdir: Path) -> dict:
    """Paste each sentence wav at its scheduled start on a silence canvas- captions and
    reveals sync to the visual timeline by construction. Word timings are REAL when the
    engine provided boundaries (edge-tts), proportional otherwise.
    Sentence indices start at 1: the hook (0) is silent and never captioned.
    """
    parts = parts_info["parts"]
    sentences = parts_info["sentences"]
    words = []
    for si, ((path, dur, wrel), start, sent) in enumerate(zip(parts, starts, sentences), start=1):
        if wrel:  # engine-native boundaries
            for w in wrel:
                words.append({"word": w["word"], "start": round(start + w["start"], 3),
                              "end": round(start + w["end"], 3), "sentence": si})
        else:
            ws = sent.split()
            weights = [max(len(w), 2) for w in ws]
            tw = sum(weights)
            t = start
            for w, wt in zip(ws, weights):
                d = dur * wt / tw
                words.append({"word": w, "start": round(t, 3), "end": round(t + d, 3),
                              "sentence": si})
                t += d
    if parts_info["engine"] == "captions-only" or parts[0][0] is None:
        return {"wav": None, "words": words, "engine": parts_info["engine"]}

    import numpy as np
    with wave.open(str(parts[0][0]), "rb") as w0:
        rate, sw, ch = w0.getframerate(), w0.getsampwidth(), w0.getnchannels()
    canvas = np.zeros(int(total * rate) * ch, dtype=np.int16)
    for (path, dur, _), start in zip(parts, starts):
        with wave.open(str(path), "rb") as wi:
            data = np.frombuffer(wi.readframes(wi.getnframes()), dtype=np.int16)
        off = int(start * rate) * ch
        end = min(off + len(data), len(canvas))
        canvas[off:end] = data[: end - off]
    out = workdir / "voiceover.wav"
    with wave.open(str(out), "wb") as wo:
        wo.setnchannels(ch)
        wo.setsampwidth(sw)
        wo.setframerate(rate)
        wo.writeframes(canvas.tobytes())
    return {"wav": out, "words": words, "engine": parts_info["engine"]}