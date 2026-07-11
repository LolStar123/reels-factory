# Synthesize a licence-clean ambient-tech music bed (85 BPM, ~45s, loopable).
# Ours by construction- no licensing risk. Serves as the bundled sample bed for --dry-run.
import numpy as np
import wave, os
from pathlib import Path

SR = 44100
BPM = 85
BEAT = 60.0 / BPM
BARS = 16  # 4/4, ~45s
DUR = BARS * 4 * BEAT
N = int(SR * DUR)
t = np.arange(N) / SR

rng = np.random.default_rng(42)


def note(freq, start, dur, amp=0.2, detune=0.003):
    """Soft pad note: 2 detuned saw-ish sines + slow attack/release."""
    n0, n1 = int(start * SR), min(int((start + dur) * SR), N)
    if n1 <= n0:
        return np.zeros(N)
    seg = np.arange(n1 - n0) / SR
    out = np.zeros(N)
    sig = np.zeros(n1 - n0)
    for mult, a in [(1, 1.0), (1 + detune, 0.7), (2, 0.15), (0.5, 0.35)]:
        sig += a * np.sin(2 * np.pi * freq * mult * seg)
    env = np.minimum(seg / (dur * 0.35), 1.0) * np.minimum((dur - seg) / (dur * 0.4), 1.0)
    env = np.clip(env, 0, 1) ** 1.5
    out[n0:n1] = sig * env * amp
    return out


# A-minor ambient progression: Am - F - C - G, two bars each, cycled
A3, C4, E4, F3, A4, C3, G3, B3, D4, E3 = 220.0, 261.63, 329.63, 174.61, 440.0, 130.81, 196.0, 246.94, 293.66, 164.81
chords = [
    [A3, C4, E4],        # Am
    [F3, A3, C4],        # F
    [C3, E3 * 2, G3],    # C
    [G3, B3, D4],        # G
]
audio = np.zeros(N)
bar = 4 * BEAT
for i in range(BARS):
    ch = chords[(i // 2) % 4]
    for f in ch:
        audio += note(f, i * bar, bar * 1.05, amp=0.11)
    # sparse plucked lead every other bar
    if i % 2 == 1:
        lead = rng.choice(ch) * 2
        audio += note(lead, i * bar + 2 * BEAT, BEAT * 1.5, amp=0.05)

# sub pulse on beats 1+3 (understated tension)
for b in range(int(DUR / BEAT)):
    if b % 2 == 0:
        s = int(b * BEAT * SR)
        seg = np.arange(min(int(0.4 * SR), N - s)) / SR
        audio[s:s + len(seg)] += 0.16 * np.sin(2 * np.pi * 55 * seg) * np.exp(-seg * 9)

# soft vinyl-style noise floor, lowpassed by cumulative smoothing
noise = rng.normal(0, 1, N)
kernel = np.ones(48) / 48
noise = np.convolve(noise, kernel, mode="same")
audio += noise * 0.012

# gentle 8-bar sidechain-style swell for movement
audio *= 1.0 + 0.08 * np.sin(2 * np.pi * t / (8 * bar))

# loopable: crossfade last 0.5s into first 0.5s shape (fade to matching zero-phase)
fade = int(0.5 * SR)
audio[:fade] *= np.linspace(0, 1, fade)
audio[-fade:] *= np.linspace(1, 0, fade)

# normalise to ~-16 dBFS peak headroom
audio = audio / np.max(np.abs(audio)) * 0.55
pcm = (audio * 32767).astype(np.int16)
stereo = np.column_stack([pcm, pcm]).ravel()

out = str(Path(__file__).resolve().parents[1] / "assets" / "music" / "ambient_tech_85bpm_synth.wav")
with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(stereo.tobytes())
print("wrote", out, f"{DUR:.1f}s")
