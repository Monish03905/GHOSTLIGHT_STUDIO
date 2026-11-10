from __future__ import annotations

import math
import random
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 32000


@dataclass(frozen=True)
class Mood:
    root: int
    chords: list[list[int]]
    tempo: int
    pulse: float
    bells: float
    brightness: float
    chord_beats: int = 8


MOODS: dict[str, Mood] = {
    "wonder": Mood(
        root=45,
        chords=[[0, 7, 12, 16, 19], [-3, 4, 9, 12, 16], [5, 12, 17, 21, 24], [-5, 2, 7, 11, 14]],
        tempo=66,
        pulse=0.12,
        bells=0.7,
        brightness=1.0,
    ),
    "weightless": Mood(
        root=43,
        chords=[[0, 7, 14, 19, 26], [2, 9, 16, 21, 26], [-3, 4, 9, 16, 21], [-5, 2, 9, 14, 19]],
        tempo=58,
        pulse=0.0,
        bells=0.55,
        brightness=0.9,
        chord_beats=10,
    ),
    "hush": Mood(
        root=38,
        chords=[[0, 3, 7, 10, 14], [-2, 3, 8, 12, 15], [-5, 2, 7, 10, 14], [-4, 3, 7, 12, 15]],
        tempo=54,
        pulse=0.0,
        bells=0.35,
        brightness=0.55,
        chord_beats=10,
    ),
    "sepia": Mood(
        root=41,
        chords=[[0, 3, 7, 10, 14], [5, 10, 14, 17, 21], [-2, 5, 9, 12, 17], [3, 7, 10, 14, 19]],
        tempo=70,
        pulse=0.18,
        bells=0.5,
        brightness=0.7,
    ),
    "tender": Mood(
        root=44,
        chords=[[0, 4, 7, 11, 14], [2, 7, 11, 14, 18], [-3, 4, 9, 12, 16], [-1, 4, 7, 12, 16]],
        tempo=60,
        pulse=0.08,
        bells=0.8,
        brightness=0.85,
        chord_beats=8,
    ),
    "midnight": Mood(
        root=36,
        chords=[[0, 3, 7, 10, 12], [-4, 3, 8, 10, 15], [-5, 2, 7, 10, 14], [-2, 5, 8, 12, 15]],
        tempo=62,
        pulse=0.28,
        bells=0.35,
        brightness=0.45,
    ),
    "pulse": Mood(
        root=38,
        chords=[[0, 3, 7, 10, 14], [0, 3, 7, 12, 15], [-2, 5, 8, 12, 15], [-4, 3, 7, 10, 14]],
        tempo=88,
        pulse=1.0,
        bells=0.4,
        brightness=0.75,
        chord_beats=4,
    ),
    "bloom": Mood(
        root=40,
        chords=[[0, 4, 7, 12, 14], [2, 7, 11, 14, 16], [-3, 4, 9, 12, 16], [0, 5, 9, 12, 17]],
        tempo=76,
        pulse=0.22,
        bells=0.9,
        brightness=1.1,
    ),
    "curious": Mood(
        root=42,
        chords=[[0, 3, 7, 10, 14], [2, 7, 12, 14, 19], [5, 10, 14, 17, 21], [-3, 4, 7, 11, 16]],
        tempo=80,
        pulse=0.35,
        bells=1.0,
        brightness=0.95,
    ),
}


def midi_to_hz(note: float) -> float:
    return 440.0 * (2.0 ** ((note - 69.0) / 12.0))


def compose(
    duration: float,
    mood_name: str,
    out_path: str | Path,
    seed: int = 0,
    tempo_base: int = 70,
) -> Path:
    duration = max(6.0, float(duration))
    mood = MOODS.get(mood_name, MOODS["wonder"])
    rng = np.random.default_rng(seed & 0xFFFFFFFF)
    py_rng = random.Random(seed ^ 0x5EED)
    tempo = max(45, min(120, int(round(mood.tempo * (tempo_base / 70.0)))))
    beat = 60.0 / tempo
    chord_seconds = beat * mood.chord_beats
    total = int(round(duration * SAMPLE_RATE)) + 1

    pad = np.zeros(total, dtype=np.float32)
    chord_samples = max(1, int(round(chord_seconds * SAMPLE_RATE)))
    chord_count = int(math.ceil(total / chord_samples)) + 1
    progression = [mood.chords[i % len(mood.chords)] for i in range(chord_count)]
    # occasional borrowed colour without breaking the key centre
    if py_rng.random() < 0.5:
        swap = py_rng.randrange(len(progression))
        progression[swap] = list(progression[swap])
        progression[swap][0] += 5

    for index, chord in enumerate(progression):
        start = index * chord_samples
        if start >= total:
            break
        release = int(1.6 * SAMPLE_RATE)
        end = min(total, start + chord_samples + release)
        length = end - start
        if length <= 0:
            continue
        t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
        attack = int(1.2 * SAMPLE_RATE)
        release_samples = int(1.8 * SAMPLE_RATE)
        env = np.ones(length, dtype=np.float32)
        if attack > 0:
            env[: min(attack, length)] = np.linspace(0, 1, min(attack, length), dtype=np.float32) ** 0.6
        if release_samples > 0 and length > release_samples:
            env[-release_samples:] *= np.linspace(1, 0, release_samples, dtype=np.float32) ** 0.8
        env *= 0.9 + 0.1 * np.sin(2 * math.pi * (0.045 + 0.01 * index) * t)
        for note_index, offset in enumerate(chord):
            note = mood.root + offset
            freq = midi_to_hz(note)
            detune = 1.0 + (py_rng.random() - 0.5) * 0.0025
            gain = 0.16 / (1.0 + 0.22 * note_index)
            wave_a = np.sin(2 * math.pi * freq * detune * t + py_rng.random() * 6.28)
            wave_b = np.sin(2 * math.pi * freq * (2.0 - detune) * t + py_rng.random() * 6.28)
            harmonic = (
                mood.brightness
                * 0.22
                * np.sin(2 * math.pi * freq * 2.0 * t)
                * np.exp(-t * (0.5 + 0.1 * note_index))
            )
            pad[start:end] += (gain * 0.5 * (wave_a + wave_b) + gain * harmonic) * env
        if index == 0:
            pad[: min(100, total)] *= np.linspace(0, 1, min(100, total), dtype=np.float32)

    # very low root drone
    t_all = np.arange(total, dtype=np.float32) / SAMPLE_RATE
    sub = np.sin(2 * math.pi * midi_to_hz(mood.root - 12) * t_all) * 0.05
    sub *= 0.7 + 0.3 * np.sin(2 * math.pi * 0.035 * t_all)
    pad += sub.astype(np.float32)

    # slow, low-frequency air
    air = _smooth_noise(total, rng, block=2200) * 0.018
    pad += air

    out = np.zeros((2, total), dtype=np.float32)
    out[0] += pad * 0.72
    haas = int(0.012 * SAMPLE_RATE)
    out[1, haas:] += pad[:-haas] * 0.62
    out[1] += pad * 0.12
    for i, (delay, gain) in enumerate([(0.23, 0.16), (0.41, 0.1), (0.67, 0.06)]):
        shift = int(delay * SAMPLE_RATE)
        if shift < total:
            target = 0 if i % 2 == 0 else 1
            out[target, shift:] += pad[:-shift] * gain
            out[1 - target, shift:] += pad[:-shift] * gain * 0.6

    # sparse bells
    bell_count = max(2, int(duration / 22.0 * mood.bells))
    scale = sorted({note for chord in mood.chords for note in chord})
    for _ in range(bell_count):
        at = float(rng.uniform(2.0, max(3.0, duration - 3.0)))
        start = int(at * SAMPLE_RATE)
        dur = float(rng.uniform(1.4, 3.4))
        freq = midi_to_hz(mood.root + py_rng.choice(scale) + 24)
        pan = float(rng.uniform(0.2, 0.8))
        length = int(dur * SAMPLE_RATE)
        if start + length >= total:
            continue
        t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
        env = np.exp(-t * (2.2 / dur)) * np.clip(t * 90, 0, 1)
        tone = np.sin(2 * math.pi * freq * t) * 0.028 * env
        out[0, start : start + length] += tone * (1.0 - pan)
        out[1, start : start + length] += tone * pan

    # pulse and soft percussion
    if mood.pulse > 0.05:
        beat_samples = int(beat * SAMPLE_RATE)
        accent = mood.pulse
        step = 0
        while step * beat_samples < total:
            start = step * beat_samples
            gain = accent * (0.05 if step % 4 else 0.075)
            _add_kick(out, start, gain, rng)
            if step % 2 == 1:
                _add_hat(out, start, 0.011 * accent, rng)
            step += 1

    _fade(out, SAMPLE_RATE, fade_in=1.8, fade_out=3.2)
    peak = float(np.max(np.abs(out))) or 1.0
    out *= min(1.0, 0.72 / peak)
    _write_wav(out_path, out, SAMPLE_RATE)
    return Path(out_path)


def _smooth_noise(total: int, rng: np.random.Generator, block: int = 2048) -> np.ndarray:
    coarse = rng.normal(0, 1, size=max(2, total // block + 2)).astype(np.float32)
    positions = np.linspace(0, len(coarse) - 1, total, dtype=np.float32)
    low = np.interp(positions, np.arange(len(coarse), dtype=np.float32), coarse).astype(np.float32)
    window = 64
    padded = np.pad(low, (window, window), mode="edge")
    cumulative = np.cumsum(padded, dtype=np.float64)
    smooth = ((cumulative[2 * window :] - cumulative[: -2 * window]) / (2 * window)).astype(np.float32)
    if smooth.size < total:
        smooth = np.pad(smooth, (0, total - smooth.size), mode="edge")
    return smooth[:total] * 0.5


def _add_kick(out: np.ndarray, start: int, gain: float, rng: np.random.Generator) -> None:
    length = int(0.32 * SAMPLE_RATE)
    if start + length >= out.shape[1]:
        return
    t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
    freq = 88.0 * np.exp(-t * 22.0) + 42.0
    phase = 2 * math.pi * np.cumsum(freq) / SAMPLE_RATE
    env = np.exp(-t * 14.0) * np.clip(t * 200, 0, 1)
    tone = (np.sin(phase) * env * gain).astype(np.float32)
    out[0, start : start + length] += tone
    out[1, start : start + length] += tone


def _add_hat(out: np.ndarray, start: int, gain: float, rng: np.random.Generator) -> None:
    length = int(0.045 * SAMPLE_RATE)
    if start + length >= out.shape[1]:
        return
    noise = rng.normal(0, 1, length).astype(np.float32)
    noise = np.diff(noise, prepend=0.0)
    env = np.exp(-np.arange(length, dtype=np.float32) / (0.008 * SAMPLE_RATE))
    tone = noise * env * gain
    out[0, start : start + length] += tone
    out[1, start : start + length] += tone * 0.8


def _fade(out: np.ndarray, rate: int, fade_in: float, fade_out: float) -> None:
    n = out.shape[1]
    fin = min(n, int(fade_in * rate))
    fout = min(n, int(fade_out * rate))
    if fin:
        out[:, :fin] *= np.linspace(0, 1, fin, dtype=np.float32)
    if fout:
        out[:, -fout:] *= np.linspace(1, 0, fout, dtype=np.float32) ** 0.8


def _write_wav(path: str | Path, samples: np.ndarray, rate: int) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    interleaved = np.clip(samples.T, -1, 1)
    pcm = (interleaved * 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm.tobytes())
