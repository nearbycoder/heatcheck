#!/usr/bin/env python3
"""
HEAT CHECK -- procedural audio generator.

Synthesizes every sound effect, crowd bed, music loop and (through macOS `say`) every announcer
line for the game. Output: 16-bit PCM WAV @ 48 kHz in Art/Export/Audio/ (mono SFX/VO, stereo crowd
beds/music) plus Art/Export/Audio/manifest.json. Verification previews (waveforms, spectrograms,
loop seams) go to Art/Previews/audio_*.png.

Everything is original and fully deterministic (fixed seeds): re-running reproduces the same files.

Run with any Python 3.9+ that has numpy -- e.g. Blender's bundled interpreter:
    /Applications/Blender.app/Contents/Resources/5.3/python/bin/python3.13 Tools/gen_audio.py

Options:
    --only S_Bounce,VO_     regenerate only assets whose name starts with one of these prefixes
    --no-vo                 skip announcer lines (they need macOS `say` + `afconvert`)
    --no-previews           skip the PNG previews
    --check                 only re-verify the WAVs listed in the manifest
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
import zlib
import struct

import numpy as np

SR = 48000
NYQ = SR / 2.0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "Art", "Export", "Audio")
PREVIEW_DIR = os.path.join(ROOT, "Art", "Previews")
TWO_PI = 2.0 * np.pi

# =============================================================================================
# Basics
# =============================================================================================


def N(seconds):
    """Seconds -> sample count."""
    return max(1, int(round(seconds * SR)))


def T(n):
    """Time axis (seconds) for n samples."""
    return np.arange(n, dtype=np.float64) / SR


def rng_for(name):
    return np.random.default_rng(zlib.crc32(name.encode("utf-8")))


def dbamp(d):
    return 10.0 ** (np.asarray(d, dtype=np.float64) / 20.0)


def amp2db(a):
    return 20.0 * math.log10(max(float(a), 1e-12))


def peak(x):
    return float(np.max(np.abs(x))) if x.size else 0.0


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def midi_hz(m):
    return 440.0 * 2.0 ** ((np.asarray(m, dtype=np.float64) - 69.0) / 12.0)


def as2d(x):
    return x if x.ndim == 2 else x[:, None]


def pad_to(x, n):
    """Zero-pad or truncate along axis 0 to exactly n samples."""
    if x.shape[0] >= n:
        return x[:n].copy()
    pad = [(0, n - x.shape[0])] + [(0, 0)] * (x.ndim - 1)
    return np.pad(x, pad)


def mix_into(buf, sig, start, gain=1.0):
    """Add sig into buf at sample offset start (clipped to the buffer)."""
    if sig.ndim == 1 and buf.ndim == 2:
        sig = np.repeat(sig[:, None], buf.shape[1], axis=1) * 0.7071
    if start >= buf.shape[0]:
        return
    if start < 0:
        sig = sig[-start:]
        start = 0
    n = min(sig.shape[0], buf.shape[0] - start)
    if n > 0:
        buf[start:start + n] += gain * sig[:n]


def mix_circular(buf, sig, start, gain=1.0):
    """Add sig into a looping buffer, wrapping whatever runs past the end back to the start."""
    if sig.ndim == 1 and buf.ndim == 2:
        sig = np.repeat(sig[:, None], buf.shape[1], axis=1) * 0.7071
    L = buf.shape[0]
    start %= L
    pos = 0
    while pos < sig.shape[0]:
        s = (start + pos) % L
        n = min(sig.shape[0] - pos, L - s)
        buf[s:s + n] += gain * sig[pos:pos + n]
        pos += n


def pan(x, pos):
    """Constant-power pan of a mono signal; pos in [-1 (left), +1 (right)]. Returns (n, 2)."""
    th = (np.clip(pos, -1.0, 1.0) + 1.0) * np.pi / 4.0
    return np.stack([x * np.cos(th), x * np.sin(th)], axis=1)


def resample(x, ratio):
    """Crude pitch/speed change by linear interpolation (ratio > 1 -> higher and shorter)."""
    n_out = max(1, int(x.shape[0] / ratio))
    idx = np.arange(n_out) * ratio
    return np.interp(idx, np.arange(x.shape[0]), x)


# =============================================================================================
# Envelopes
# =============================================================================================


def env_exp(n, tau, attack=0.0):
    """Exponential decay with time constant tau (s); optional smooth attack (s)."""
    t = T(n)
    e = np.exp(-t / max(tau, 1e-6))
    if attack > 0:
        e *= np.sin(0.5 * np.pi * np.clip(t / attack, 0.0, 1.0)) ** 2
    return e


def env_pts(n, pts):
    """Piecewise-linear envelope through (time_s, value) points."""
    ts, vs = zip(*pts)
    return np.interp(T(n), ts, vs)


def env_adsr(n, a, d, s, gate, r):
    """Classic ADSR: attack a, decay d (to level s), note-off at gate (s), release r."""
    t = T(n)
    e = np.where(t < a, t / max(a, 1e-6), s + (1.0 - s) * np.exp(-(t - a) / max(d, 1e-6)))
    level_at_gate = (gate / max(a, 1e-6)) if gate < a else s + (1.0 - s) * math.exp(-(gate - a) / max(d, 1e-6))
    rel = level_at_gate * np.exp(-(t - gate) / max(r, 1e-6))
    return np.where(t < gate, e, rel)


def fade(x, fin=0.0, fout=0.0):
    x = x.copy()
    if fin > 0:
        k = min(N(fin), x.shape[0])
        w = np.sin(0.5 * np.pi * np.linspace(0.0, 1.0, k)) ** 2
        x[:k] *= w if x.ndim == 1 else w[:, None]
    if fout > 0:
        k = min(N(fout), x.shape[0])
        w = np.cos(0.5 * np.pi * np.linspace(0.0, 1.0, k)) ** 2
        x[-k:] *= w if x.ndim == 1 else w[:, None]
    return x


def smooth_random(r, n, rate_hz, circular=False):
    """Band-limited random curve (unit RMS) whose fluctuations sit below ~rate_hz."""
    f = np.fft.rfftfreq(n, 1.0 / SR)
    X = np.fft.rfft(r.standard_normal(n)) * np.exp(-(f / max(rate_hz, 1e-3)) ** 2)
    X[0] = 0.0
    y = np.fft.irfft(X, n)
    return y / (rms(y) + 1e-12)


# =============================================================================================
# Filters
# =============================================================================================


def m_lp(f, fc, order=2):
    return 1.0 / np.sqrt(1.0 + (np.asarray(f) / fc) ** (2 * order))


def m_hp(f, fc, order=2):
    ff = np.maximum(np.asarray(f, dtype=np.float64), 1e-6)
    return 1.0 / np.sqrt(1.0 + (fc / ff) ** (2 * order))


def m_bp(f, fc, q):
    ff = np.maximum(np.asarray(f, dtype=np.float64), 1e-6)
    return 1.0 / np.sqrt(1.0 + q * q * (ff / fc - fc / ff) ** 2)


def m_peak(f, fc, q, gain_db):
    return 1.0 + (dbamp(gain_db) - 1.0) * m_bp(f, fc, q) ** 2


def m_tilt(f, db_per_oct, f_ref=1000.0):
    ff = np.maximum(np.asarray(f, dtype=np.float64), 20.0)
    return (ff / f_ref) ** (db_per_oct / 6.0206)


def fft_filter(x, mag_fn, circular=False, pad=0.25):
    """Zero-phase filtering with an arbitrary magnitude response mag_fn(freqs_hz).

    Use it on stationary material (noise beds, before an envelope is applied) or on loops
    (circular=True keeps the result exactly periodic). Works on mono or (n, ch) arrays."""
    n = x.shape[0]
    nfft = n if circular else n + N(pad)
    X = np.fft.rfft(x, nfft, axis=0)
    H = mag_fn(np.fft.rfftfreq(nfft, 1.0 / SR))
    X *= H if x.ndim == 1 else H[:, None]
    return np.fft.irfft(X, nfft, axis=0)[:n]


def shaped_noise(r, n, mag_fn=None):
    """Unit-RMS stationary noise with the given magnitude response; periodic in n (loop-safe)."""
    X = np.fft.rfft(r.standard_normal(n))
    if mag_fn is not None:
        X *= mag_fn(np.fft.rfftfreq(n, 1.0 / SR))
    X[0] = 0.0
    y = np.fft.irfft(X, n)
    return y / (rms(y) + 1e-12)


def biquad(kind, fc, q=0.7071, gain_db=0.0):
    """RBJ cookbook biquad coefficients -> (b0, b1, b2, a1, a2)."""
    fc = min(max(fc, 5.0), NYQ * 0.98)
    w0 = TWO_PI * fc / SR
    c, s = math.cos(w0), math.sin(w0)
    alpha = s / (2.0 * q)
    A = 10.0 ** (gain_db / 40.0)
    if kind == "lp":
        b, a = [(1 - c) / 2, 1 - c, (1 - c) / 2], [1 + alpha, -2 * c, 1 - alpha]
    elif kind == "hp":
        b, a = [(1 + c) / 2, -(1 + c), (1 + c) / 2], [1 + alpha, -2 * c, 1 - alpha]
    elif kind == "bp":
        b, a = [alpha, 0.0, -alpha], [1 + alpha, -2 * c, 1 - alpha]
    elif kind == "peak":
        b, a = [1 + alpha * A, -2 * c, 1 - alpha * A], [1 + alpha / A, -2 * c, 1 - alpha / A]
    elif kind == "lowshelf":
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - sq)]
        a = [(A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - sq]
    elif kind == "highshelf":
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sq)]
        a = [(A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sq]
    else:
        raise ValueError(kind)
    return (b[0] / a[0], b[1] / a[0], b[2] / a[0], a[1] / a[0], a[2] / a[0])


def _biquad_loop(xs, co):
    b0, b1, b2, a1, a2 = co
    z1 = z2 = 0.0
    out = []
    app = out.append
    for xi in xs:
        yi = b0 * xi + z1
        z1 = b1 * xi - a1 * yi + z2
        z2 = b2 * xi - a2 * yi
        app(yi)
    return out


def iir(x, *coeffs):
    """Causal (minimum-phase) cascade of biquads. Long signals use a truncated-IR FFT convolution."""
    if x.ndim == 2:
        return np.stack([iir(x[:, c], *coeffs) for c in range(x.shape[1])], axis=1)
    y = x
    for co in coeffs:
        if y.shape[0] <= 4 * SR:
            y = np.asarray(_biquad_loop(y.tolist(), co))
        else:
            imp = np.zeros(SR)
            imp[0] = 1.0
            h = np.asarray(_biquad_loop(imp.tolist(), co))
            keep = np.nonzero(np.abs(h) > 1e-9 * np.max(np.abs(h)))[0]
            h = h[: keep[-1] + 1] if keep.size else h[:1]
            y = convolve(y, h)[: y.shape[0]]
    return y


def svf(x, fc, q=0.7071, mode="lp"):
    """Time-varying state-variable filter (Simper/Cytomic TPT). fc and q may be per-sample arrays.
    mode: lp | bp (unity peak gain) | hp | notch."""
    n = x.shape[0]
    fcv = np.clip(np.broadcast_to(np.asarray(fc, dtype=np.float64), (n,)), 10.0, NYQ * 0.95)
    k = 1.0 / np.broadcast_to(np.asarray(q, dtype=np.float64), (n,))
    g = np.tan(np.pi * fcv / SR)
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    ic1 = ic2 = 0.0
    lp, bp = [], []
    lpa, bpa = lp.append, bp.append
    for xi, c1, c2, c3 in zip(x.tolist(), a1.tolist(), a2.tolist(), a3.tolist()):
        v3 = xi - ic2
        v1 = c1 * ic1 + c2 * v3
        v2 = ic2 + c2 * ic1 + c3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        lpa(v2)
        bpa(v1)
    lp = np.asarray(lp)
    bp = np.asarray(bp)
    if mode == "lp":
        return lp
    if mode == "bp":
        return bp * k
    if mode == "hp":
        return x - k * bp - lp
    if mode == "notch":
        return x - k * bp
    raise ValueError(mode)


def dc_block(x, fc=15.0):
    return iir(x, biquad("hp", fc, 0.7071))


# =============================================================================================
# Oscillators
# =============================================================================================


def phase_acc(freq, n, ph0=0.0):
    """Running phase in cycles for a (possibly per-sample) frequency."""
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    ph = np.empty(n)
    ph[0] = 0.0
    if n > 1:
        np.cumsum(f[:-1] / SR, out=ph[1:])
    return ph + ph0


def _blep(p, dt):
    y = np.zeros_like(p)
    m = p < dt
    t = p[m] / dt[m]
    y[m] = t + t - t * t - 1.0
    m = p > 1.0 - dt
    t = (p[m] - 1.0) / dt[m]
    y[m] = t * t + t + t + 1.0
    return y


def osc_sine(freq, n, ph0=0.0):
    return np.sin(TWO_PI * phase_acc(freq, n, ph0))


def osc_saw(freq, n, ph0=0.0):
    """Band-limited (PolyBLEP) sawtooth, -1..1."""
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    p = phase_acc(f, n, ph0) % 1.0
    dt = np.clip(np.abs(f) / SR, 1e-9, 0.5)
    return 2.0 * p - 1.0 - _blep(p, dt)


def osc_pulse(freq, n, pw=0.5, ph0=0.0):
    """Band-limited pulse with duty cycle pw (difference of two PolyBLEP saws), zero mean."""
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    ph = phase_acc(f, n, ph0)
    dt = np.clip(np.abs(f) / SR, 1e-9, 0.5)
    p1 = ph % 1.0
    p2 = (ph + pw) % 1.0
    return (2.0 * p1 - 1.0 - _blep(p1, dt)) - (2.0 * p2 - 1.0 - _blep(p2, dt))


def osc_tri(freq, n, ph0=0.0):
    p = phase_acc(freq, n, ph0) % 1.0
    return 1.0 - 4.0 * np.abs(p - 0.5)


def modal(n, modes, attack=0.0003):
    """Sum of exponentially damped sinusoids; modes = [(freq, amp, tau[, phase]), ...]."""
    t = T(n)
    y = np.zeros(n)
    for m in modes:
        f, a, tau = m[0], m[1], m[2]
        ph = m[3] if len(m) > 3 else 0.0
        if f >= NYQ * 0.92 or a == 0.0:
            continue
        y += a * np.sin(TWO_PI * f * t + ph) * np.exp(-t / tau)
    if attack > 0:
        y *= np.clip(t / attack, 0.0, 1.0)
    return y


def burst(r, dur, tau, mag_fn=None, attack=0.0):
    """Filtered noise burst: stationary noise is filtered first, then the envelope is applied
    (so the attack stays as sharp as the envelope and nothing rings before t=0)."""
    n = N(dur)
    x = r.standard_normal(n)
    if mag_fn is not None:
        x = fft_filter(x, mag_fn, pad=0.0)
        x /= rms(x) + 1e-12
    return x * env_exp(n, tau, attack)


# =============================================================================================
# Effects
# =============================================================================================


def _fft_size(n):
    return 1 << int(math.ceil(math.log2(max(n, 2))))


def convolve(x, h):
    """Linear convolution along axis 0 (mono/stereo broadcast). Output length len(x)+len(h)-1."""
    x2, h2 = as2d(x), as2d(h)
    n = x2.shape[0] + h2.shape[0] - 1
    nfft = _fft_size(n)
    y = np.fft.irfft(np.fft.rfft(x2, nfft, axis=0) * np.fft.rfft(h2, nfft, axis=0), nfft, axis=0)[:n]
    return y[:, 0] if (x.ndim == 1 and h.ndim == 1) else y


def convolve_circular(x, h):
    """Circular convolution with period len(x) (h must be shorter): reverb for seamless loops."""
    L = x.shape[0]
    x2, h2 = as2d(x), as2d(h)
    if h2.shape[0] > L:
        raise ValueError("IR longer than loop")
    y = np.fft.irfft(np.fft.rfft(x2, L, axis=0) * np.fft.rfft(h2, L, axis=0), L, axis=0)
    return y[:, 0] if (x.ndim == 1 and h.ndim == 1) else y


def reverb_ir(r, rt60=1.8, length=None, predelay=0.02, damping=(1.0, 0.8, 0.5, 0.28),
              early=10, stereo=True, er_gain=0.6):
    """Synthetic hall/arena impulse response (unit energy per channel).

    Frequency-dependent decay: 4 bands (<400, 400-2k, 2k-6k, >6k Hz) decay with rt60*damping[i].
    Early reflections are a few sparse taps in the first ~60 ms."""
    length = length or min(rt60 * 1.15 + predelay, 4.5)
    n = N(length)
    t = T(n)
    nch = 2 if stereo else 1
    f = np.fft.rfftfreq(n, 1.0 / SR)
    lf = np.log2(np.maximum(f, 1.0))
    steps = [0.5 * (1.0 + np.tanh(3.0 * (lf - math.log2(c)))) for c in (400.0, 2000.0, 6000.0)]
    masks = [1.0 - steps[0], steps[0] - steps[1], steps[1] - steps[2], steps[2]]
    build = np.clip((t - predelay) / 0.035, 0.0, 1.0) ** 1.5
    ir = np.zeros((n, nch))
    for ch in range(nch):
        W = np.fft.rfft(r.standard_normal(n))
        acc = np.zeros(n)
        for mask, dmp in zip(masks, damping):
            acc += np.fft.irfft(W * mask, n) * 10.0 ** (-3.0 * t / (rt60 * dmp))
        acc *= build
        acc /= np.sqrt(np.sum(acc ** 2)) + 1e-12
        er = np.zeros(n)
        for k in range(early):
            tk = predelay * 0.4 + r.uniform(0.004, 0.065)
            idx = N(tk)
            if idx < n:
                er[idx] += r.choice([-1.0, 1.0]) * er_gain * math.exp(-k * 0.22) * r.uniform(0.5, 1.0)
        er = fft_filter(er, lambda ff: m_lp(ff, 6500.0, 1), pad=0.0)
        acc = acc + er * 0.35
        ir[:, ch] = acc / (np.sqrt(np.sum(acc ** 2)) + 1e-12)
    ir = fade(ir, 0.0, min(0.15, length * 0.3))
    return ir if stereo else ir[:, 0]


def add_reverb(x, ir, wet, dry=1.0):
    """Dry + wet convolution reverb. Output grows by the IR length; stereo IR -> stereo output."""
    y = wet * convolve(x, ir)
    d = x if (x.ndim == 2 or y.ndim == 1) else pan(x, 0.0) * math.sqrt(2.0)
    out = np.zeros_like(y)
    out[: d.shape[0]] += dry * (d if out.ndim == d.ndim else as2d(d))
    return out + y


def echo(x, delay_s, feedback=0.35, wet=0.3, repeats=6, lp_hz=4500.0, hp_hz=250.0, circular=False):
    """Feedback-style delay rendered as a sum of progressively darker taps."""
    d = N(delay_s)
    n = x.shape[0]
    out = x.copy() if circular else pad_to(x, n + d * repeats)
    tap = x.copy()
    shape = lambda f: m_lp(f, lp_hz, 1) * m_hp(f, hp_hz, 1)
    for k in range(1, repeats + 1):
        tap = fft_filter(tap, shape, circular=circular)
        g = wet * feedback ** (k - 1)
        if circular:
            out += g * np.roll(tap, k * d, axis=0)
        else:
            out[k * d:k * d + n] += g * tap
    return out


def saturate(x, drive=2.0, mix=1.0, asym=0.0):
    y = (np.tanh(drive * x + asym) - math.tanh(asym)) / math.tanh(drive)
    return mix * y + (1.0 - mix) * x


def _detector(x):
    return np.max(np.abs(x), axis=1) if x.ndim == 2 else np.abs(x)


def compressor(x, thresh_db=-18.0, ratio=3.0, attack=0.005, release=0.1, knee_db=6.0, makeup_db=0.0,
               block=32):
    """Feed-forward peak compressor with soft knee (block-rate envelope, sample-rate gain)."""
    n = x.shape[0]
    a = _detector(x)
    nb = (n + block - 1) // block
    det = np.max(pad_to(a, nb * block).reshape(nb, block), axis=1)
    lvl = 20.0 * np.log10(det + 1e-9)
    over = lvl - thresh_db
    slope = 1.0 - 1.0 / ratio
    gr = np.where(over <= -knee_db / 2, 0.0,
                  np.where(over >= knee_db / 2, over * slope, slope * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    ca = math.exp(-block / (attack * SR))
    cr = math.exp(-block / (release * SR))
    g = 0.0
    sm = []
    for v in gr.tolist():
        c = ca if v > g else cr
        g = c * g + (1.0 - c) * v
        sm.append(g)
    gain_db = makeup_db - np.asarray(sm)
    gs = dbamp(np.interp(np.arange(n), (np.arange(nb) + 0.5) * block, gain_db))
    return x * (gs[:, None] if x.ndim == 2 else gs)


def limiter(x, ceiling_db=-1.0, lookahead=0.002, release=0.08):
    """Look-ahead brick-wall limiter (no overs by construction, then a safety clip)."""
    n = x.shape[0]
    c = float(dbamp(ceiling_db))
    req = np.minimum(1.0, c / (_detector(x) + 1e-12))
    B = max(4, N(lookahead))
    nb = (n + B - 1) // B
    bm = np.min(np.concatenate([req, np.ones(nb * B - n)]).reshape(nb, B), axis=1)
    fwd = np.minimum(bm, np.concatenate([bm[1:], [1.0]]))  # covers >= B samples of look-ahead
    rc = math.exp(-B / (release * SR))
    g = 1.0
    sm = []
    for v in fwd.tolist():
        g = min(v, 1.0 - (1.0 - g) * rc)
        sm.append(g)
    gs = np.repeat(np.asarray(sm), B)[:n]
    # attack ramp: box average over B samples (never exceeds the required gain, see docs above)
    cs = np.cumsum(np.concatenate([np.full(B, gs[0]), gs]))
    gs = (cs[B:] - cs[:-B]) / B
    y = x * (gs[:, None] if x.ndim == 2 else gs)
    return np.clip(y, -c, c)


# =============================================================================================
# Output helpers
# =============================================================================================


def normalize(x, peak_db=-1.0):
    p = peak(x)
    return x * (float(dbamp(peak_db)) / p) if p > 0 else x


def trim_lead(x, thresh_rel_db=-50.0, preroll=0.0):
    a = _detector(x)
    thr = a.max() * float(dbamp(thresh_rel_db))
    idx = int(np.argmax(a > thr))
    if preroll > 0:
        idx = max(0, idx - N(preroll))
    return x[idx:]


def trim_tail(x, thresh_rel_db=-66.0):
    a = _detector(x)
    above = np.nonzero(a > a.max() * float(dbamp(thresh_rel_db)))[0]
    return x[: above[-1] + 1] if above.size else x


def finalize_oneshot(x, peak_db=-1.0, max_len=None, fade_out=0.03, lead_db=-50.0, preroll=0.0,
                     fade_in=0.0003):
    """One-shot mastering: DC block, trim leading silence (sound starts at sample 0 = impact),
    trim/cap the tail, fade out, normalize."""
    x = dc_block(x, 12.0)
    x = trim_lead(x, lead_db, preroll)
    x = trim_tail(x, -66.0)
    if max_len is not None and x.shape[0] > N(max_len):
        x = x[: N(max_len)]
    x = fade(x, fade_in, min(fade_out, x.shape[0] / SR * 0.5))
    return normalize(x, peak_db)


def seamless_xfade(y, L, X):
    """Turn a signal of length >= L+X into an exactly loopable signal of length L by equal-power
    cross-fading its overhang [L, L+X) into its start [0, X)."""
    out = y[:L].copy()
    th = np.linspace(0.0, 0.5 * np.pi, X, endpoint=False)
    w_in, w_out = np.sin(th), np.cos(th)
    if y.ndim == 2:
        w_in, w_out = w_in[:, None], w_out[:, None]
    out[:X] = y[:X] * w_in + y[L:L + X] * w_out
    return out


def process_circular(x, fn, reps=3):
    """Apply a stateful process to a loop as if it had been playing forever: run it on
    `reps` copies back to back and keep the last one (state has converged)."""
    L = x.shape[0]
    y = fn(np.concatenate([x] * reps, axis=0))
    return y[(reps - 1) * L: reps * L]


def write_wav(path, x, seed=0):
    x = np.asarray(x, dtype=np.float64)
    if not np.all(np.isfinite(x)):
        raise ValueError("non-finite samples in " + path)
    ch = 1 if x.ndim == 1 else x.shape[1]
    r = np.random.default_rng(seed)
    dither = (r.random(x.shape) - r.random(x.shape)) * (x != 0.0)  # TPDF, +-1 LSB, none on digital silence
    q = np.clip(np.round(x * 32767.0 + dither), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(q.tobytes())


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64) / 32768.0
    return (x.reshape(-1, ch) if ch > 1 else x), sr


def unit(x):
    """Scale to unit RMS."""
    return x / (rms(x) + 1e-12)


def unitpeak(x):
    """Scale to unit peak."""
    return x / (peak(x) + 1e-12)


_IR_CACHE = {}


def ir_cached(key, **kw):
    if key not in _IR_CACHE:
        _IR_CACHE[key] = reverb_ir(rng_for("ir_" + key), **kw)
    return _IR_CACHE[key]


def court_ir():
    """Short mono 'gym floor' room, used to seat the close-up SFX in the space."""
    return ir_cached("court", rt60=0.9, length=0.6, predelay=0.012, stereo=False)


def arena_ir_mono():
    return ir_cached("arena_m", rt60=1.8, length=1.4, predelay=0.025, stereo=False)


def arena_ir():
    return ir_cached("arena", rt60=2.3, length=2.6, predelay=0.03, stereo=True)


# =============================================================================================
# Sound effects -- building blocks
# =============================================================================================


def thump(n, f_start, f_end, tau_pitch, tau_amp, attack=0.0004):
    """Pitch-dropping sine thud (floor / body / stanchion boom)."""
    t = T(n)
    f = f_end + (f_start - f_end) * np.exp(-t / tau_pitch)
    return osc_sine(f, n) * env_exp(n, tau_amp) * np.clip(t / attack, 0.0, 1.0)


def ball_ring(r, n, pitch=1.0, decay=1.0):
    """Air-cavity modes of a 0.12 m-radius ball (first mode ~947 Hz): the hollow 'ping' of a dribble."""
    base = [(947.0, 1.0, 0.050), (1520.0, 0.45, 0.034), (2050.0, 0.28, 0.024), (2700.0, 0.14, 0.015)]
    modes = [(f * pitch * r.uniform(0.985, 1.015), a * r.uniform(0.8, 1.15), tau * decay, r.uniform(0, TWO_PI))
             for f, a, tau in base]
    return modal(n, modes)


# In-plane flexural modes of a steel ring: f_n ~ n(n^2-1)/sqrt(n^2+1), n = 2..8 (relative to n = 2).
RING_RATIOS = [1.0, 2.828, 5.423, 8.770, 12.866, 17.71, 23.30]


def rim_modes(r, f0, decay=1.0, bright=1.0):
    amps = [0.45, 1.0, 0.9, 0.7, 0.5, 0.34, 0.22]
    taus = [0.22, 0.30, 0.24, 0.17, 0.12, 0.085, 0.06]
    modes = []
    for k, ratio in enumerate(RING_RATIOS):
        f = f0 * ratio * r.uniform(0.99, 1.01)
        a = amps[k] * (bright ** k) * r.uniform(0.6, 1.2)
        tau = taus[k] * decay * r.uniform(0.85, 1.15)
        modes.append((f, a, tau, r.uniform(0, TWO_PI)))
        # slightly detuned out-of-plane twin -> metallic beating
        modes.append((f * r.uniform(1.004, 1.018), a * r.uniform(0.35, 0.75), tau * r.uniform(0.8, 1.1),
                      r.uniform(0, TWO_PI)))
    return modes


def rim_hit(r, n, f0, decay=1.0, bright=1.0):
    metal = unitpeak(modal(n, rim_modes(r, f0, decay, bright)))
    tick = unitpeak(burst(r, n / SR, 0.0010, lambda f: m_hp(f, 3000, 2)))
    return 0.85 * metal + 0.35 * tick


def board_modes(r, scale=1.0):
    table = [(168, 1.0, 0.11), (251, 0.8, 0.09), (338, 0.65, 0.07), (447, 0.5, 0.055), (583, 0.38, 0.045),
             (742, 0.28, 0.035), (931, 0.2, 0.028), (1180, 0.14, 0.02)]
    return [(f * scale * r.uniform(0.98, 1.02), a, tau, r.uniform(0, TWO_PI)) for f, a, tau in table]


def rattle(r, n, t0, t1, rate, tau, pitch=1.0):
    """Loose hardware rattling: a decaying train of tiny metallic ticks."""
    y = np.zeros(n)
    t = t0
    while t < t1:
        a = math.exp(-(t - t0) / tau) * r.uniform(0.35, 1.0)
        f = r.uniform(1400.0, 3200.0) * pitch
        L = N(0.03)
        tick = modal(L, [(f, 1.0, 0.006), (f * 1.53, 0.6, 0.004), (f * 2.41, 0.35, 0.003)])
        tick = unitpeak(tick) + 0.4 * unitpeak(burst(r, 0.03, 0.0015, lambda ff: m_hp(ff, 2000, 2)))
        mix_into(y, a * tick, N(t))
        t += r.uniform(0.6, 1.4) / rate
    return y


def crackles(r, n, rate_fn, big_prob=0.12, circular=False):
    """Poisson fire crackles (rate_fn(t) events/s), small bright snaps plus occasional bigger pops."""
    y = np.zeros(n)
    dur = n / SR
    rmax = max(rate_fn(tt) for tt in np.linspace(0.0, dur, 64)) + 1e-6
    t = 0.0
    while True:
        t += r.exponential(1.0 / rmax)
        if t >= dur:
            break
        if r.random() > rate_fn(t) / rmax:
            continue
        if r.random() < big_prob:
            L, fc, tau, a = N(0.04), r.uniform(500, 1600), r.uniform(0.006, 0.015), r.uniform(0.6, 1.0)
        else:
            L, fc, tau, a = N(0.012), r.uniform(1500, 7000), r.uniform(0.0008, 0.003), min(1.0, r.exponential(0.35))
        ev = r.standard_normal(L) * env_exp(L, tau)
        ev = unitpeak(iir(ev, biquad("bp", fc, r.uniform(0.8, 2.0))))
        (mix_circular if circular else mix_into)(y, a * ev, N(t))
    return y


# =============================================================================================
# Sound effects -- ball, rim, board
# =============================================================================================


def sfx_bounce(i):
    r = rng_for("bounce%d" % i)
    n = N(0.4)
    pitch = (1.0, 0.95, 1.05)[i]
    hard = (1.0, 1.15, 0.9)[i]
    floor = thump(n, 210 * pitch, 72 * pitch, 0.010, 0.045)          # ball/floor contact boom
    panel = thump(n, 132, 118, 0.02, 0.09)                             # hardwood panel resonance
    body = modal(n, [(385 * pitch, 1.0, 0.018, 0.3), (610 * pitch, 0.5, 0.012, 1.1)])
    ring = ball_ring(r, n, pitch, decay=r.uniform(0.9, 1.15))
    slap = unitpeak(burst(r, 0.4, 0.0016, lambda f: m_hp(f, 1200, 2) * m_lp(f, 9000, 2)))
    y = 0.95 * floor + 0.35 * panel + 0.30 * body + 0.42 * ring + 0.30 * hard * slap
    y = saturate(0.9 * y, 1.4)
    return add_reverb(y, court_ir(), wet=0.10)[:n]


def sfx_swish(i):
    r = rng_for("swish%d" % i)
    dur = (0.55, 0.6)[i]
    n = N(dur)
    t = T(n)
    sweep = (1.0, 0.88)[i]
    fc = np.interp(t, [0, 0.07, 0.25, dur], [2400, 5200, 3600, 2600]) * sweep
    body = unit(svf(r.standard_normal(n), fc, q=0.8, mode="bp"))
    env = np.interp(t, [0, 0.02, 0.06, 0.16, 0.32, dur], [0, 0.75, 1.0, 0.5, 0.15, 0.0]) ** 1.3
    # net cords rubbing: dense little grains of 5-9 kHz hiss
    hiss = unit(fft_filter(r.standard_normal(n), lambda f: m_bp(f, 6500, 1.2), pad=0.0))
    am = np.zeros(n)
    tg = 0.003
    while tg < 0.36:
        mix_into(am, env_exp(N(0.015), r.uniform(0.0015, 0.004)) * r.uniform(0.3, 1.0) * (1 - tg / 0.4), N(tg))
        tg += r.uniform(0.006, 0.02) * (1.0, 0.75)[i]
    whump = unit(fft_filter(r.standard_normal(n), lambda f: m_bp(f, 420, 0.9), pad=0.0))
    whump *= np.interp(t, [0, 0.03, 0.09, 0.2], [0, 1, 0.3, 0])
    y = body * env + 0.55 * hiss * am + 0.22 * whump
    return add_reverb(y, court_ir(), wet=0.12)[:n]


def sfx_rim(i):
    r = rng_for("rim%d" % i)
    n = N(0.75)
    f0 = (205.0, 228.0, 192.0)[i]
    y = rim_hit(r, n, f0, decay=(1.0, 0.85, 1.1)[i], bright=(1.0, 1.08, 0.95)[i])
    y += 0.5 * thump(n, 240, 120, 0.008, 0.03) + 0.22 * ball_ring(r, n, 1.0, decay=0.6)
    if i == 2:  # the ball chatters on the rim: second, softer contact
        y2 = 0.5 * rim_hit(r, n, f0, decay=0.8, bright=0.9) + 0.25 * thump(n, 220, 120, 0.008, 0.025)
        mix_into(y, y2, N(0.085))
    return add_reverb(y, court_ir(), wet=0.14)[:n]


def sfx_backboard():
    r = rng_for("backboard")
    n = N(0.6)
    thud = thump(n, 240, 128, 0.012, 0.075)
    plate = unitpeak(modal(n, board_modes(r)))
    knock = unitpeak(burst(r, 0.6, 0.006, lambda f: m_lp(f, 3500, 2) * m_hp(f, 150, 1)))
    ring = ball_ring(r, n, 0.98, decay=0.8)
    rat = unitpeak(rattle(r, n, 0.018, 0.4, rate=26, tau=0.11))
    y = 1.0 * thud + 0.55 * plate + 0.35 * knock + 0.25 * ring + 0.22 * rat
    y = saturate(0.8 * y, 1.3)
    return add_reverb(y, court_ir(), wet=0.14)[:n]


def sfx_dunk():
    r = rng_for("dunk")
    n = N(1.25)
    t = T(n)
    metal = rim_hit(r, n, 176.0, decay=1.3, bright=1.0)
    metal *= 1.0 + 0.3 * np.sin(TWO_PI * 10.5 * t) * np.exp(-t / 0.3)     # breakaway-rim spring wobble
    board = thump(n, 220, 105, 0.012, 0.08) + 0.5 * unitpeak(modal(n, board_modes(r, 0.85)))
    stanchion = thump(n, 110, 50, 0.03, 0.17)                              # deep support boom
    crack = unitpeak(burst(r, 1.25, 0.003, lambda f: m_hp(f, 1000, 2) * m_lp(f, 12000, 1)))  # ball+hands impact
    slap = unitpeak(burst(r, 1.25, 0.006, lambda f: m_bp(f, 1800, 0.7)))    # palms on the rim
    rat = unitpeak(rattle(r, n, 0.04, 0.9, rate=22, tau=0.22, pitch=0.9))
    net = unit(fft_filter(r.standard_normal(n), lambda f: m_bp(f, 3000, 0.8), pad=0.0))
    net *= np.interp(t, [0, 0.01, 0.12, 0.35], [0, 1, 0.35, 0])
    y = 1.0 * metal + 0.8 * board + 0.75 * stanchion + 0.5 * crack + 0.3 * slap + 0.22 * rat + 0.1 * net
    y = saturate(1.2 * unitpeak(y), 1.4)
    return add_reverb(y, arena_ir_mono(), wet=0.2)[:N(1.15)]


# =============================================================================================
# Sound effects -- players
# =============================================================================================


SQUEAKS = [
    dict(dur=0.12, f=[(0, 1350), (0.06, 1750), (0.12, 1900)],
         env=[(0, 0), (0.006, 1), (0.10, 0.9), (0.12, 0)]),
    dict(dur=0.18, f=[(0, 2050), (0.09, 1650), (0.18, 1300)],
         env=[(0, 0), (0.008, 1), (0.15, 0.8), (0.18, 0)]),
    dict(dur=0.24, f=[(0, 1500), (0.07, 1820), (0.1, 1700), (0.13, 1600), (0.2, 2000), (0.24, 2050)],
         env=[(0, 0), (0.006, 1), (0.09, 0.85), (0.1, 0), (0.13, 0), (0.136, 1), (0.22, 0.8), (0.24, 0)]),
    dict(dur=0.085, f=[(0, 1750), (0.03, 2150), (0.085, 1650)],
         env=[(0, 0), (0.004, 1), (0.07, 0.85), (0.085, 0)]),
]


def sfx_squeak(i):
    """Sneaker stick-slip squeak: a gliding buzzy tone with chatter, shaped by a sole resonance."""
    r = rng_for("squeak%d" % i)
    sp = SQUEAKS[i]
    n = N(sp["dur"] + 0.05)
    t = T(n)
    ft, fv = zip(*sp["f"])
    f0 = np.interp(t, ft, fv) * (1.0 + 0.012 * smooth_random(r, n, 180.0))
    src = 0.7 * osc_saw(f0, n, r.random()) + 0.3 * osc_pulse(f0, n, 0.3, r.random())
    env = env_pts(n, sp["env"])
    chatter = np.clip(0.78 + 0.22 * smooth_random(r, n, 110.0), 0.3, 1.2)
    y = src * env * chatter
    y = iir(y, biquad("hp", 700, 0.7), biquad("peak", 2600, 1.2, 6.0), biquad("lp", 7500, 0.7))
    hiss = unit(fft_filter(r.standard_normal(n), lambda f: m_bp(f, 4500, 1.0), pad=0.0))
    y = unitpeak(y) + 0.06 * hiss * env
    return add_reverb(y, court_ir(), wet=0.12)[:n]


def sfx_pass():
    r = rng_for("pass")
    dur = 0.26
    n = N(dur + 0.03)
    t = T(n)
    fc = np.interp(t, [0, 0.05, 0.12, dur], [700, 2300, 1700, 900])
    air = unit(svf(r.standard_normal(n), fc, q=1.1, mode="bp"))
    env = np.interp(t, [0, 0.012, 0.05, 0.14, dur], [0, 0.6, 1.0, 0.35, 0.0]) ** 1.2
    pop = thump(n, 180, 110, 0.01, 0.018)                              # ball leaving the hands
    return air * env + 0.35 * pop


def sfx_steal():
    r = rng_for("steal")
    n = N(0.25)
    t = T(n)
    slap = unitpeak(burst(r, 0.25, 0.011, lambda f: m_hp(f, 700, 2) * m_peak(f, 2600, 1.0, 6) * m_lp(f, 9000, 2)))
    skin = modal(n, [(330, 1.0, 0.02, 0.5), (520, 0.5, 0.012, 1.0)])
    tap = ball_ring(r, n, 1.02, decay=0.45)
    fc = np.interp(t, [0, 0.03, 0.2], [2800, 2000, 900])
    swipe = unit(svf(r.standard_normal(n), fc, 1.0, "bp")) * np.interp(t, [0, 0.015, 0.05, 0.2], [0, 0, 0.5, 0])
    y = 0.9 * slap + 0.35 * skin + 0.28 * tap + 0.35 * swipe
    return add_reverb(y, court_ir(), wet=0.1)[:n]


def sfx_block():
    r = rng_for("block")
    n = N(0.32)
    slap = unitpeak(burst(r, 0.32, 0.014, lambda f: m_hp(f, 500, 2) * m_peak(f, 2200, 0.8, 5) * m_lp(f, 10000, 2)))
    ring = ball_ring(r, n, 0.97, decay=1.0)
    thd = thump(n, 190, 92, 0.012, 0.045)
    skin = modal(n, [(290, 1.0, 0.025), (470, 0.6, 0.015)])
    y = 1.0 * slap + 0.5 * ring + 0.75 * thd + 0.3 * skin
    y = saturate(0.8 * y, 1.6)
    return add_reverb(y, court_ir(), wet=0.14)[:n]


def sfx_shove():
    r = rng_for("shove")
    n = N(0.36)
    body = thump(n, 125, 62, 0.03, 0.075)
    whump = unitpeak(burst(r, 0.36, 0.04, lambda f: m_bp(f, 320, 0.8), attack=0.004))
    cloth = unitpeak(burst(r, 0.36, 0.05, lambda f: m_bp(f, 3200, 0.9), attack=0.006))
    y = saturate(1.0 * body + 0.55 * whump + 0.18 * cloth, 2.2)
    return add_reverb(y, court_ir(), wet=0.1)[:n]


def sfx_fall():
    r = rng_for("fall")
    n = N(0.5)
    y = np.zeros(n)
    for t0, a in [(0.0, 1.0), (0.048, 0.75), (0.1, 0.45), (0.16, 0.3)]:   # hip, shoulder, elbow, hand
        m = n - N(t0)
        hit = thump(m, 115 * r.uniform(0.9, 1.1), 58, 0.02, 0.06)
        hit += 0.5 * unitpeak(burst(r, m / SR, 0.018, lambda f: m_bp(f, 420, 0.8)))
        hit += 0.3 * modal(m, [(142, 1.0, 0.12), (263, 0.6, 0.08)])
        mix_into(y, a * hit, N(t0))
    slide = unitpeak(burst(r, 0.4, 0.12, lambda f: m_bp(f, 2400, 0.8), attack=0.03))
    mix_into(y, 0.1 * slide, N(0.05))
    y = saturate(0.8 * y, 1.8)
    return add_reverb(y, court_ir(), wet=0.14)[:n]


# =============================================================================================
# Sound effects -- officials / horns
# =============================================================================================


def sfx_buzzer():
    """End-of-period arena horn: two raspy pulse tones a minor third apart through horn resonances."""
    r = rng_for("buzzer")
    hold = 1.25
    n = N(hold + 0.06)
    t = T(n)
    scoop = 1.0 - 0.06 * np.exp(-t / 0.025)
    flutter = 1.0 + 0.002 * smooth_random(r, n, 8.0)
    y = sum(0.5 * osc_pulse(f * scoop * flutter, n, 0.32, r.random()) for f in (164.8, 196.0))
    y = iir(y, biquad("hp", 90, 0.7), biquad("peak", 950, 1.2, 7.0), biquad("peak", 2400, 1.5, 5.0),
            biquad("lp", 6500, 0.7))
    y *= 1.0 + 0.08 * np.sin(TWO_PI * 30.0 * t)
    y = saturate(unitpeak(y), 3.0)
    y *= env_pts(n, [(0, 0), (0.012, 1), (hold, 0.95), (hold + 0.05, 0)])
    return add_reverb(y, arena_ir_mono(), wet=0.28)[:N(1.65)]


def sfx_shotclock():
    """Shot-clock violation: higher, electronic buzzer with a 100 Hz grind."""
    r = rng_for("shotclock")
    hold = 0.62
    n = N(hold + 0.04)
    y = osc_pulse(440.0, n, 0.42, r.random())
    y *= 1.0 + 0.3 * osc_sine(100.0, n)
    y = iir(y, biquad("hp", 200, 0.7), biquad("peak", 1500, 1.0, 5.0), biquad("lp", 5000, 0.7))
    y = saturate(unitpeak(y), 2.5)
    y *= env_pts(n, [(0, 0), (0.006, 1), (hold, 1), (hold + 0.03, 0)])
    return add_reverb(y, arena_ir_mono(), wet=0.2)[:N(0.82)]


def sfx_whistle():
    """Referee pea whistle: ~2.9 kHz tone with the pea's 34 Hz warble (FM + AM) and breath."""
    r = rng_for("whistle")
    hold = 0.5
    n = N(hold + 0.06)
    t = T(n)
    rate = 34.0 * (1.0 + 0.05 * smooth_random(r, n, 3.0))
    ph = phase_acc(rate, n)
    f0 = 2950.0 * (1.0 - 0.05 * np.exp(-t / 0.03)) * (1.0 + 0.045 * np.sin(TWO_PI * ph))
    tone = osc_sine(f0, n) + 0.12 * osc_sine(2 * f0, n) + 0.035 * osc_sine(3 * f0, n)
    am = 1.0 - 0.45 * (0.5 + 0.5 * np.sin(TWO_PI * ph + 0.8))
    breath = unit(fft_filter(r.standard_normal(n), lambda f: m_bp(f, 3000, 1.5), pad=0.0))
    env = env_pts(n, [(0, 0), (0.018, 0.85), (hold * 0.6, 1.0), (hold, 0.95), (hold + 0.035, 0)])
    y = (tone * am + 0.12 * breath * (0.6 + 0.4 * am)) * env
    return add_reverb(y, arena_ir_mono(), wet=0.22)[:N(0.66)]


# =============================================================================================
# Sound effects -- fire
# =============================================================================================


def sfx_fire_ignite():
    """Player catches fire: gas 'fwoomp' + rising flame whoosh + crackle bloom."""
    r = rng_for("fireignite")
    dur = 1.5
    n = N(dur + 0.2)
    t = T(n)
    boom = thump(n, 105, 45, 0.06, 0.2)
    cut = np.interp(t, [0, 0.03, 0.25, 0.8, dur], [250, 900, 5500, 2600, 1500])
    gas_env = np.interp(t, [0, 0.012, 0.12, 0.45, 1.0, dur, dur + 0.2], [0, 0.85, 1.0, 0.55, 0.3, 0.0, 0.0])
    gas = unit(svf(r.standard_normal(n), cut, 0.8, "lp")) * gas_env * (0.8 + 0.2 * smooth_random(r, n, 14.0))
    wf = np.interp(t, [0, 0.3, dur], [400, 3500, 2000])
    whoosh = unit(svf(r.standard_normal(n), wf, 1.2, "bp")) * np.interp(t, [0, 0.05, 0.15, 0.5, 0.9], [0, 0.4, 1.0, 0.3, 0])
    crk = unitpeak(crackles(r, n, lambda tt: 8.0 + 45.0 * min(tt / 0.2, 1.0) * math.exp(-max(tt - 0.3, 0.0) / 0.7),
                            big_prob=0.15))
    sizzle = unit(fft_filter(r.standard_normal(n), lambda f: m_hp(f, 6000, 2), pad=0.0)) * gas_env
    y = 0.75 * boom + 0.30 * gas + 0.14 * whoosh + 0.45 * crk + 0.025 * sizzle
    y = saturate(0.8 * unitpeak(y), 1.4)
    return add_reverb(y, court_ir(), wet=0.15)[:N(dur)]


def sfx_fire_loop():
    """Seamless 4 s crackling fire bed: every layer is periodic in the loop length."""
    r = rng_for("fireloop")
    L = N(4.0)
    roar = shaped_noise(r, L, lambda f: m_tilt(f, -4.0, 300.0) * m_hp(f, 70, 2) * m_lp(f, 900, 2))
    gust = 0.75 + 0.25 * smooth_random(r, L, 1.5)
    band = shaped_noise(r, L, lambda f: m_bp(f, 1600, 0.7))
    flick = np.clip(0.55 + 0.45 * smooth_random(r, L, 12.0), 0.05, None)
    hiss = shaped_noise(r, L, lambda f: m_hp(f, 5000, 2))
    crk = unitpeak(crackles(r, L, lambda tt: 24.0, circular=True))
    y = 0.55 * roar * gust + 0.28 * band * flick + 0.05 * hiss + 0.55 * crk
    y = y + 0.1 * convolve_circular(y, court_ir())
    return y


def sfx_fire_basket():
    """On-fire make: flaming-net fwoosh dropping through the hoop, crackles and a little sparkle."""
    r = rng_for("firebasket")
    dur = 1.2
    n = N(dur + 0.15)
    t = T(n)
    cut = np.interp(t, [0, 0.08, 0.6, dur], [6500, 4000, 900, 500])
    fw = unit(svf(r.standard_normal(n), cut, 0.9, "lp"))
    fw *= np.interp(t, [0, 0.015, 0.15, 0.6, dur], [0, 1.0, 0.7, 0.25, 0.0]) * (0.85 + 0.15 * smooth_random(r, n, 12.0))
    sf = np.interp(t, [0, 0.07, 0.25, 0.4], [3000, 6000, 3500, 2800])
    swish = unit(svf(r.standard_normal(n), sf, 0.8, "bp")) * np.interp(t, [0, 0.02, 0.07, 0.2, 0.4], [0, 0.7, 1.0, 0.4, 0])
    boom = thump(n, 90, 48, 0.04, 0.13)
    crk = unitpeak(crackles(r, n, lambda tt: 50.0 * math.exp(-tt / 0.45), big_prob=0.18))
    sparkle = np.zeros(n)
    for _ in range(12):
        L = N(0.12)
        ping = osc_sine(r.uniform(3000, 7000), L) * env_exp(L, r.uniform(0.03, 0.08), attack=0.001)
        mix_into(sparkle, r.uniform(0.1, 0.25) * ping, N(r.uniform(0.03, 0.7)))
    y = 0.32 * fw + 0.18 * swish + 0.6 * boom + 0.4 * crk + 0.35 * sparkle
    y = saturate(0.8 * unitpeak(y), 1.3)
    return add_reverb(y, court_ir(), wet=0.15)[:N(dur)]


# =============================================================================================
# UI and stingers
# =============================================================================================


def synth_note(midi, dur, kind="pulse", pw=0.5, tau=None, attack=0.002, vib=0.0, detune=0.0, release=0.02,
               bright=1.0):
    """Small arcade synth voice used by the UI sounds."""
    n = N(dur + release)
    t = T(n)
    f = float(midi_hz(midi)) * (1.0 + vib * np.sin(TWO_PI * 6.0 * t) * np.clip((t - 0.08) / 0.1, 0.0, 1.0))
    if kind == "pulse":
        y = osc_pulse(f, n, pw)
    elif kind == "saw":
        y = 0.5 * osc_saw(f * (1 + detune), n) + 0.5 * osc_saw(f * (1 - detune), n, 0.37)
    elif kind == "tri":
        y = osc_tri(f, n)
    else:
        y = osc_sine(f, n)
    if bright < 1.0:
        y = iir(y, biquad("lp", 2000 + 9000 * bright, 0.7))
    env = env_exp(n, tau, attack) if tau else env_pts(n, [(0, 0), (attack, 1), (dur, 0.85), (dur + release, 0)])
    return y * env


def fm_bell(midi, dur, index=2.5, ratio=3.5, tau=0.35):
    n = N(dur)
    t = T(n)
    f = float(midi_hz(midi))
    I = index * np.exp(-t / (tau * 0.5))
    return np.sin(TWO_PI * f * t + I * np.sin(TWO_PI * f * ratio * t)) * env_exp(n, tau, 0.001)


def ui_move():
    n = N(0.085)
    t = T(n)
    f = 1046.5 * (1.0 + 0.25 * np.exp(-t / 0.006))
    y = 0.6 * osc_pulse(f, n, 0.25) + 0.5 * osc_sine(2.0 * f, n)
    y = iir(y, biquad("lp", 6000, 0.7))
    return y * env_exp(n, 0.022, attack=0.0015)


def ui_select():
    n = N(0.27)
    y = np.zeros(n)
    for t0, m, d in [(0.0, 88, 0.06), (0.055, 95, 0.2)]:          # E6 -> B6
        v = 0.55 * synth_note(m, d, "pulse", tau=d * 0.45) + 0.35 * synth_note(m + 12, d, "sine", tau=d * 0.4)
        v += 0.25 * synth_note(m, d, "tri", tau=d * 0.5)
        mix_into(y, v, N(t0))
    y = iir(y, biquad("lp", 7000, 0.7))
    return echo(y, 0.07, 0.3, 0.2, repeats=2)[:n]


def ui_back():
    n = N(0.16)
    y = np.zeros(n)
    for t0, m, d in [(0.0, 81, 0.05), (0.045, 76, 0.1)]:           # A5 -> E5
        v = 0.5 * synth_note(m, d, "tri", tau=d * 0.5) + 0.3 * synth_note(m, d, "pulse", pw=0.25, tau=d * 0.4)
        mix_into(y, v, N(t0))
    return iir(y, biquad("lp", 4000, 0.7))


def ui_start():
    """Bright arcade 'press start' jingle in E major: quick arpeggio into a shimmering chord."""
    n = N(0.95)
    y = np.zeros(n)
    for k, m in enumerate([76, 80, 83, 88]):                       # E5 G#5 B5 E6
        v = 0.6 * synth_note(m, 0.09, "pulse", pw=0.35, tau=0.06) + 0.35 * synth_note(m, 0.09, "saw", detune=0.004, tau=0.05)
        mix_into(y, 0.7 * v, N(k * 0.06))
    t0 = 0.24
    for m, g in [(88, 0.33), (92, 0.3), (95, 0.3), (100, 0.16)]:   # E6 G#6 B6 E7
        v = synth_note(m, 0.55, "saw", detune=0.005, attack=0.004, vib=0.004, release=0.12, bright=0.7)
        v += 0.5 * synth_note(m, 0.55, "pulse", pw=0.4, attack=0.004, vib=0.004, release=0.12)
        mix_into(y, g * v, N(t0))
    mix_into(y, 0.35 * fm_bell(100, 0.65, tau=0.3), N(t0))
    lift = unit(svf(rng_for("uistart").standard_normal(N(0.3)), np.linspace(800, 7000, N(0.3)), 1.0, "bp"))
    mix_into(y, 0.06 * lift * np.linspace(0, 1, N(0.3)) ** 2, 0)
    y = iir(y, biquad("lp", 10000, 0.7))
    y = echo(y, 0.11, 0.25, 0.18, repeats=2)[:n]
    return add_reverb(y, court_ir(), wet=0.12)[:n]


def sfx_score():
    """Made-basket stinger: 'ba-DING' -- pickup note into a bright E-major hit with a bell."""
    n = N(0.42)
    y = np.zeros(n)
    mix_into(y, 0.5 * synth_note(83, 0.06, "pulse", pw=0.35, tau=0.04), 0)
    t0 = 0.065
    for m in (88, 92, 95):
        v = synth_note(m, 0.3, "saw", detune=0.006, tau=0.12, attack=0.003, bright=0.75)
        mix_into(y, 0.3 * v, N(t0))
    mix_into(y, 0.4 * fm_bell(100, 0.35, index=2.0, tau=0.12), N(t0))
    mix_into(y, 0.25 * synth_note(100, 0.3, "pulse", pw=0.5, tau=0.08), N(t0))
    y = iir(y, biquad("lp", 11000, 0.7))
    return add_reverb(y, court_ir(), wet=0.1)[:n]


def sfx_countdown():
    """Last-seconds clock tick: short A6 beep with a woody click."""
    r = rng_for("countdown")
    n = N(0.1)
    beep = (osc_sine(1760.0, n) + 0.3 * osc_pulse(1760.0, n, 0.5)) * env_exp(n, 0.03, attack=0.001)
    click = unitpeak(burst(r, 0.1, 0.0008, lambda f: m_bp(f, 3500, 1.0)))
    return iir(beep + 0.3 * click, biquad("lp", 9000, 0.7))


# =============================================================================================
# Crowd: formant-synthesized voices (STFT cascade-formant filter), claps, whistles
# =============================================================================================

VOWELS = {  # F1, F2, F3 (Hz), adult male; F4/F5 fixed. Female/child voices scale by ~1.15-1.2.
    "a": (730, 1090, 2440), "ae": (660, 1720, 2410), "e": (530, 1840, 2480), "i": (300, 2250, 3000),
    "o": (570, 840, 2410), "u": (320, 870, 2240), "uh": (520, 1190, 2390), "oh": (460, 820, 2600),
    "er": (490, 1350, 1690),
}
F45 = (3350.0, 4200.0)
FBW = np.array([90.0, 110.0, 150.0, 220.0, 300.0])
NFFT, HOP = 1024, 256


def vowel_vec(v, fscale=1.0):
    f1, f2, f3 = VOWELS[v]
    return np.array([f1, f2, f3, F45[0], F45[1]], dtype=np.float64) * fscale


def _stft(x):
    win = np.sqrt(np.hanning(NFFT + 1)[:-1])
    xp = np.pad(x, (NFFT, 2 * NFFT))
    nfr = (xp.shape[0] - NFFT) // HOP + 1
    idx = HOP * np.arange(nfr)[:, None] + np.arange(NFFT)[None, :]
    return np.fft.rfft(xp[idx] * win, axis=1), win


def _istft(S, win, n):
    frames = np.fft.irfft(S, NFFT, axis=1) * win
    nfr, k = frames.shape[0], NFFT // HOP
    blocks = np.zeros((nfr + k, HOP))
    for j in range(k):
        blocks[j:j + nfr] += frames[:, j * HOP:(j + 1) * HOP]
    return blocks.reshape(-1)[NFFT:NFFT + n] / 2.0     # sqrt-Hann^2 at 75 % overlap sums to 2


def frame_times(n):
    nfr = (n + 2 * NFFT) // HOP + 1
    return (np.arange(nfr) * HOP - NFFT / 2) / SR


def formant_track(n, key_t, key_F):
    ft = frame_times(n)
    key_F = np.asarray(key_F, dtype=np.float64)
    return np.stack([np.interp(ft, key_t, key_F[:, j]) for j in range(key_F.shape[1])], axis=1)


def _formant_mag(freqs, F, bw_scale=1.0):
    """Cascade of 2-pole resonators (Klatt-style): natural relative formant levels."""
    f = freqs[None, :]
    H = np.ones((F.shape[0], freqs.shape[0]))
    for k in range(F.shape[1]):
        Fk = F[:, k:k + 1]
        Bk = FBW[k] * bw_scale
        H /= np.sqrt((1.0 - (f / Fk) ** 2) ** 2 + (f * Bk / Fk ** 2) ** 2)
    return H


def render_voice(r, f0, F_frames, amp, breath=0.2, tilt_db=0.0, bw_scale=1.0, noise_only=False):
    """Source-filter voice: band-limited glottal saw (+ breath noise) through time-varying formants."""
    n = amp.shape[0]
    exc = r.standard_normal(n) if noise_only else osc_saw(f0, n, r.random()) + breath * r.standard_normal(n)
    S, win = _stft(exc)
    freqs = np.fft.rfftfreq(NFFT, 1.0 / SR)
    H = _formant_mag(freqs, F_frames, bw_scale) * m_hp(freqs, 90.0, 2)[None, :]
    if tilt_db:
        H *= m_tilt(freqs, tilt_db, 500.0)[None, :]
    return _istft(S * H, win, n) * amp


def babble_talker(r, n, female):
    """One distant conversational talker: syllable-rate vowels, intonation, phrase pauses, consonant hiss."""
    dur = n / SR
    fs = r.uniform(1.12, 1.22) if female else r.uniform(0.94, 1.06)
    base = r.uniform(175, 250) if female else r.uniform(95, 145)
    names = list(VOWELS)
    amp = np.zeros(n)
    kt, kF, ft, fv, cons = [], [], [], [], []
    t = r.uniform(-0.3, 0.8)
    phrase_t = t
    while t < dur + 0.3:
        if r.random() < 0.12:                       # pause between phrases
            t += r.uniform(0.25, 1.1)
            phrase_t = t
            continue
        sd = r.uniform(0.11, 0.30)
        a = r.uniform(0.5, 1.0)
        Fv = vowel_vec(names[r.integers(len(names))], fs)
        kt += [t + 0.3 * sd, t + 0.7 * sd]
        kF += [Fv, Fv]
        decl = -2.5 * min((t - phrase_t) / 2.0, 1.0)      # phrase declination (semitones)
        ft.append(t + 0.5 * sd)
        fv.append(base * 2.0 ** ((decl + r.normal(0.0, 2.0)) / 12.0))
        L = N(1.3 * sd)
        mix_into(amp, a * np.sin(np.pi * np.linspace(0.0, 1.0, L)) ** 1.5, N(t - 0.15 * sd))
        if r.random() < 0.45:
            cons.append((t, r.uniform(0.02, 0.06), a))
        t += sd
    tt = T(n)
    f0 = np.interp(tt, ft, fv) * (1.0 + 0.012 * smooth_random(r, n, 25.0))
    y = render_voice(r, f0, formant_track(n, kt, kF), amp, breath=0.25)
    lvl = rms(y) + 1e-9
    for t0, d, a in cons:                            # s / t / k hiss
        b = burst(r, d, d * 0.35, lambda f, c=r.uniform(2500, 4500): m_hp(f, c, 2), attack=0.004)
        mix_into(y, 0.6 * lvl * a * unit(b), N(t0))
    return y


CHEER_WORDS = {  # vowel key points over the (relative) duration of the shout
    "yeah": [("i", 0.0), ("e", 0.2), ("ae", 0.45), ("a", 1.0)],
    "woo": [("u", 0.0), ("u", 1.0)],
    "hey": [("e", 0.0), ("e", 0.6), ("i", 1.0)],
    "ahh": [("a", 0.0), ("a", 1.0)],
    "oh": [("o", 0.0), ("oh", 1.0)],
    "ooh": [("u", 0.0), ("oh", 0.45), ("u", 1.0)],
    "aww": [("o", 0.0), ("o", 0.5), ("uh", 1.0)],
}


def shout_voice(r, word, dur, base, fs, rise_st, fall_st, breath=0.45, attack=0.1, release=0.35,
                vib_rate=5.5, vib_depth=0.006, tilt_db=3.0, peak_at=0.3):
    """One crowd member shouting/singing a word with a rise-then-fall pitch contour."""
    n = N(dur + release + 0.05)
    t = T(n)
    rel = np.clip(t / dur, 0.0, 1.0)
    st = np.where(rel < peak_at, rise_st * np.sin(0.5 * np.pi * rel / peak_at),
                  rise_st - (rise_st + fall_st) * (np.maximum(rel - peak_at, 0.0) / (1.0 - peak_at)) ** 1.3)
    f0 = base * 2.0 ** (st / 12.0) * (1.0 + vib_depth * np.sin(TWO_PI * vib_rate * t + r.uniform(0, TWO_PI)))
    f0 *= 1.0 + 0.01 * smooth_random(r, n, 25.0)
    keys = CHEER_WORDS[word]
    F = formant_track(n, [k * dur for _, k in keys], [vowel_vec(v, fs) for v, _ in keys])
    amp = np.interp(t, [0.0, attack, dur, dur + release], [0.0, 1.0, 0.8, 0.0])
    amp *= 1.0 + 0.08 * smooth_random(r, n, 6.0)
    return render_voice(r, f0, F, amp, breath=breath, tilt_db=tilt_db)


def clap_bank(r, count=32):
    bank = []
    for _ in range(count):
        L = N(0.08)
        fc, q = r.uniform(900, 2400), r.uniform(0.7, 1.6)
        x = fft_filter(r.standard_normal(L), lambda f: m_bp(f, fc, q) + 0.25 * m_bp(f, fc * 2.2, 1.0), pad=0.0)
        e = env_exp(L, r.uniform(0.005, 0.011), attack=0.0006)
        c = unitpeak(x) * e + 0.3 * modal(L, [(r.uniform(250, 450), 1.0, 0.01)])
        bank.append(unitpeak(c))
    return bank


def applause(r, n, bank, clappers, start, stop, rate, env_fn):
    """Independent clappers, each with its own hand timbre, position and tempo."""
    out = np.zeros((n, 2))
    for _ in range(clappers):
        p, g = r.uniform(-0.95, 0.95), r.uniform(0.3, 1.0)
        hz, t, t_end = r.uniform(*rate), r.uniform(*start), r.uniform(*stop)
        sig = bank[r.integers(len(bank))]
        while t < t_end:
            mix_into(out, pan(sig * g * env_fn(t) * r.uniform(0.7, 1.0), p), N(t))
            t += r.uniform(0.85, 1.15) / hz
    return out


def finger_whistle(r, dur):
    n = N(dur)
    t = T(n)
    f = np.interp(t, [0, 0.15 * dur, 0.7 * dur, dur], [2300, 2900, 2750, 2200]) * r.uniform(0.85, 1.15)
    f *= 1.0 + 0.006 * np.sin(TWO_PI * 5.5 * t) + 0.004 * smooth_random(r, n, 30.0)
    y = osc_sine(f, n) + 0.05 * osc_sine(2.0 * f, n)
    y += 0.08 * unit(fft_filter(r.standard_normal(n), lambda ff: m_bp(ff, float(np.mean(f)), 3.0), pad=0.0))
    return y * env_pts(n, [(0, 0), (0.03, 1), (0.7 * dur, 0.9), (dur, 0)])


def crowd_reaction(seed, dur, voices, words, rise, fall, vdur, onset, female=0.45, breath=(0.35, 0.6),
                   clappers=0, whistles=0, noise_vowel=None, noise_level=0.0, stomps=0, peak_at=0.3,
                   male_f0=(150, 240), female_f0=(260, 420), attack=(0.06, 0.2), release=(0.25, 0.5)):
    """Generic crowd reaction (cheer / ooh / groan): many shouted voices + applause + whistles,
    optional vowel-formant-filtered noise 'body', all in a big arena reverb."""
    r = rng_for(seed)
    n = N(dur)
    mix = np.zeros((n, 2))
    wk, wp = zip(*words)
    wp = np.asarray(wp, dtype=np.float64) / np.sum(wp)
    for _ in range(voices):
        fem = r.random() < female
        base = r.uniform(*(female_f0 if fem else male_f0))
        fs = r.uniform(1.12, 1.22) if fem else r.uniform(0.94, 1.06)
        word = wk[r.choice(len(wk), p=wp)]
        t0 = r.uniform(*onset[0]) if r.random() < onset[2] else r.uniform(*onset[1])
        d = min(r.uniform(*vdur), dur - t0 - 0.2)
        if d < 0.2:
            continue
        v = shout_voice(r, word, d, base, fs, r.uniform(*rise), r.uniform(*fall), breath=r.uniform(*breath),
                        attack=r.uniform(*attack), release=r.uniform(*release), peak_at=peak_at)
        mix_into(mix, pan(unit(v) * r.uniform(0.35, 1.0), r.uniform(-0.9, 0.9)), N(t0))
    mix /= rms(mix) + 1e-9
    if noise_vowel is not None:                     # breathy vowel-coloured crowd 'body'
        keys, env = noise_vowel
        for ch in range(2):
            F = formant_track(n, [k * dur for _, k in keys], [vowel_vec(v, 1.08) for v, _ in keys])
            body = render_voice(r, None, F, env_pts(n, env), noise_only=True, bw_scale=2.5)
            mix[:, ch] += noise_level * unit(body) * np.sqrt(np.mean(env_pts(n, env) ** 2) + 1e-9)
    if clappers:
        cl = applause(r, n, clap_bank(r), clappers, (0.04, 0.3), (0.55 * dur, 0.9 * dur), (3.5, 6.0),
                      lambda tt: min(1.0, 0.5 + tt / 0.2) * max(0.0, 1.0 - tt / dur) ** 0.6)
        mix += 0.55 * cl / (rms(cl) + 1e-9)
    for _ in range(whistles):
        w = finger_whistle(r, r.uniform(0.4, 0.9))
        mix_into(mix, pan(0.5 * unitpeak(w), r.uniform(-0.8, 0.8)), N(r.uniform(0.05, 0.4 * dur)))
    for k in range(stomps):
        L = N(0.2)
        s = thump(L, 90, 55, 0.02, 0.05)
        for ch in range(2):
            mix_into(mix[:, ch], 0.5 * s * r.uniform(0.7, 1.0), N(0.3 + k * 0.42 + r.uniform(0, 0.03)))
    wet = add_reverb(mix, arena_ir(), wet=0.55, dry=0.8)[:n]
    wet = iir(wet, biquad("hp", 70, 0.7), biquad("peak", 3000, 0.8, 1.5))
    return fade(wet, 0.0, min(0.6, dur * 0.25))


def crowd_cheer(i):
    words = [[("yeah", 3), ("woo", 2), ("hey", 2), ("ahh", 2)], [("woo", 4), ("yeah", 2), ("ahh", 2), ("oh", 1)]][i]
    return crowd_reaction("cheer%d" % i, 2.5, 52, words, rise=(3, 7), fall=(2, 5), vdur=(0.8, 1.8),
                          attack=(0.04, 0.12), onset=((0.0, 0.15), (0.15, 0.5), 0.8), clappers=26, whistles=2 + i,
                          noise_vowel=([("ae", 0.0), ("a", 0.5), ("o", 1.0)], [(0, 0), (0.25, 1), (1.4, 0.7), (2.5, 0)]),
                          noise_level=0.35)


def crowd_big_cheer():
    return crowd_reaction("bigcheer", 4.5, 96, [("yeah", 3), ("woo", 3), ("ahh", 3), ("hey", 1), ("oh", 1)],
                          rise=(3, 8), fall=(2, 6), vdur=(1.8, 3.7), onset=((0.0, 0.18), (0.18, 1.2), 0.7),
                          attack=(0.04, 0.14), clappers=44, whistles=5, stomps=7,
                          noise_vowel=([("ae", 0.0), ("a", 0.4), ("o", 1.0)], [(0, 0), (0.3, 1), (3.0, 0.8), (4.5, 0)]),
                          noise_level=0.5)


def crowd_ooh():
    return crowd_reaction("ooh", 1.5, 46, [("ooh", 1)], rise=(3, 5), fall=(6, 9), vdur=(1.0, 1.3),
                          onset=((0.0, 0.1), (0.08, 0.2), 0.8), breath=(0.4, 0.6), peak_at=0.32,
                          male_f0=(130, 190), female_f0=(230, 330), attack=(0.08, 0.16), release=(0.2, 0.35),
                          noise_vowel=([("u", 0.0), ("oh", 0.45), ("u", 1.0)], [(0, 0), (0.25, 1), (0.6, 0.85), (1.5, 0)]),
                          noise_level=0.6)


def crowd_groan():
    return crowd_reaction("groan", 1.5, 46, [("aww", 1)], rise=(0.5, 2), fall=(7, 10), vdur=(1.0, 1.3),
                          onset=((0.0, 0.12), (0.1, 0.25), 0.8), breath=(0.4, 0.65), peak_at=0.15,
                          male_f0=(115, 165), female_f0=(200, 290), attack=(0.08, 0.15), release=(0.2, 0.35),
                          noise_vowel=([("o", 0.0), ("o", 0.5), ("uh", 1.0)], [(0, 0), (0.15, 1), (0.7, 0.7), (1.5, 0)]),
                          noise_level=0.6)


def crowd_loop(seconds=12.0):
    """Seamless stereo arena bed: distant babble, sporadic claps, a few far-off 'whoo's, room tone."""
    r = rng_for("crowdloop")
    P, L, X = N(2.5), N(seconds), N(2.0)          # reverb pre-roll, loop length, cross-fade length
    n = P + L + X
    mix = np.zeros((n, 2))
    for _ in range(44):
        y = babble_talker(r, n, female=r.random() < 0.45)
        dist = r.uniform(0.0, 1.0)
        y = fft_filter(y, lambda f, c=6500.0 - 4000.0 * dist: m_lp(f, c, 1), pad=0.0)
        mix += pan(unit(y) * (0.25 + 0.75 * (1.0 - dist)), r.uniform(-0.9, 0.9))
    mix /= rms(mix) + 1e-9
    bank = clap_bank(r)
    claps = np.zeros((n, 2))
    t = 0.0
    while True:                                    # scattered single claps, ~6 per second
        t += r.exponential(1.0 / 6.0)
        if t >= n / SR:
            break
        mix_into(claps, pan(bank[r.integers(len(bank))] * r.uniform(0.2, 1.0), r.uniform(-0.95, 0.95)), N(t))
    for _ in range(3):                             # small pockets of rhythmic clapping
        c0 = r.uniform(0.0, n / SR - 3.0)
        claps += applause(r, n, bank, 4, (c0, c0 + 0.3), (c0 + 1.2, c0 + 2.6), (3.8, 4.4), lambda tt: 1.0)
    mix += 0.35 * claps / (rms(claps) + 1e-9)
    for _ in range(3):                             # distant 'whoo'
        d = r.uniform(0.7, 1.2)
        v = shout_voice(r, "woo", d, r.uniform(280, 420), 1.15, r.uniform(5, 8), r.uniform(3, 5), breath=0.5,
                        attack=0.15, release=0.4, tilt_db=0.0)
        v = fft_filter(v, lambda f: m_lp(f, 2800, 1), pad=0.0)
        mix_into(mix, pan(0.9 * unit(v), r.uniform(-0.8, 0.8)), N(r.uniform(P / SR, n / SR - 1.5)))
    room = np.stack([shaped_noise(r, n, lambda f: m_tilt(f, -3.0, 200.0) * m_lp(f, 500, 2) * m_hp(f, 40, 2))
                     for _ in range(2)], axis=1)
    mix += 0.12 * room
    wet = add_reverb(mix, arena_ir(), wet=0.85, dry=0.45)[:n]
    wet = iir(wet, biquad("hp", 50, 0.7))
    return seamless_xfade(wet[P:], L, X)


# =============================================================================================
# Music -- instruments
# =============================================================================================

NOTE_PC = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def note(name):
    """'E1' -> 28, 'C#5' -> 73 (MIDI, C4 = 60)."""
    return 12 * (int(name[-1]) + 1) + NOTE_PC[name[:-1]]


def parse_seq(s):
    """'step:Note:len[:kind[:vel]] ...' -> list of tuples (step, midi, len, kind, vel)."""
    out = []
    for tok in s.split():
        p = tok.split(":")
        out.append((float(p[0]), note(p[1]), float(p[2]), p[3] if len(p) > 3 else "", float(p[4]) if len(p) > 4 else 1.0))
    return out


class Groove:
    """16th-note grid with swing; loops are exactly `bars` long (sample-accurate length L)."""

    def __init__(self, bpm, bars, swing):
        self.bpm, self.bars, self.swing = bpm, bars, swing
        self.step = 60.0 / bpm / 4.0
        self.L = int(round(bars * 16 * self.step * SR))

    def time(self, bar, step):
        t = (bar * 16 + step) * self.step
        if float(step).is_integer() and int(step) % 2 == 1:
            t += (self.swing - 0.5) * 2.0 * self.step
        return t

    def at(self, bar, step):
        return int(round(self.time(bar, step) * SR))


def drum_kick(r, decay=0.22):
    n = N(0.5)
    t = T(n)
    f = 46.0 + 95.0 * np.exp(-t / 0.045) + 260.0 * np.exp(-t / 0.005)
    body = osc_sine(f, n) * np.exp(-t / decay) * np.clip(t / 0.001, 0.0, 1.0)
    click = 0.25 * unitpeak(burst(r, 0.5, 0.0025, lambda ff: m_hp(ff, 1500, 2) * m_lp(ff, 9000, 1)))
    return fade(saturate(body + click, 1.8), 0.0, 0.05)


def drum_snare(r, tight=1.0):
    n = N(0.4)
    t = T(n)
    body = 0.7 * osc_sine(190.0 * (1.0 + 0.25 * np.exp(-t / 0.01)), n) * np.exp(-t / 0.07)
    body += 0.35 * osc_sine(340.0, n) * np.exp(-t / 0.045)
    wires = unit(fft_filter(r.standard_normal(n), lambda f: m_bp(f, 3500, 0.5) * m_hp(f, 900, 2), pad=0.0))
    wires *= np.exp(-t / (0.13 * tight))
    crack = unitpeak(burst(r, 0.4, 0.004, lambda f: m_hp(f, 2000, 1)))
    y = (0.8 * body + 0.3 * wires + 0.35 * crack) * np.clip(t / 0.0005, 0.0, 1.0)
    return fade(saturate(y, 1.6), 0.0, 0.05)


def drum_clap(r):
    n = N(0.35)
    t = T(n)
    src = unit(fft_filter(r.standard_normal(n), lambda f: m_bp(f, 1300, 1.2) + 0.4 * m_bp(f, 2600, 1.5), pad=0.0))
    env = np.zeros(n)
    for k, tb in enumerate((0.0, 0.008, 0.017, 0.026)):
        env += (0.7 + 0.1 * k) * np.where(t >= tb, np.exp(-(t - tb) / (0.005 if k < 3 else 0.09)), 0.0)
    return fade(src * env, 0.0, 0.05)


def drum_hat(r, open_=False):
    n = N(0.6 if open_ else 0.12)
    t = T(n)
    base = 330.0 * r.uniform(0.98, 1.02)
    metal = sum(osc_pulse(base * k, n, 0.5, r.random()) for k in (1.0, 1.4471, 1.617, 1.9265, 2.5028, 2.6637))
    metal = unit(fft_filter(metal, lambda f: m_hp(f, 7000, 3) * (0.5 + m_bp(f, 10000, 0.8)), pad=0.0))
    air = unit(fft_filter(r.standard_normal(n), lambda f: m_hp(f, 8000, 2), pad=0.0))
    y = (0.6 * metal + 0.5 * air) * np.exp(-t / (0.26 if open_ else 0.03)) * np.clip(t / 0.0005, 0.0, 1.0)
    return fade(y, 0.0, 0.03)


def drum_crash(r, dur=2.4):
    n = N(dur)
    t = T(n)
    out = np.zeros((n, 2))
    for ch in range(2):
        partials = modal(n, [(r.uniform(3000, 11000), r.uniform(0.3, 1.0), r.uniform(0.4, 1.2), r.uniform(0, TWO_PI))
                             for _ in range(40)])
        hiss = unit(fft_filter(r.standard_normal(n), lambda f: m_hp(f, 3500, 2) * m_lp(f, 14000, 2), pad=0.0))
        y = 0.6 * unit(partials) * np.exp(-t / 0.7) + hiss * (0.7 * np.exp(-t / 0.65) + 0.6 * np.exp(-t / 0.06))
        out[:, ch] = y * np.clip(t / 0.001, 0.0, 1.0)
    return fade(out, 0.0, 0.3)


def drum_shaker(r):
    n = N(0.09)
    y = fft_filter(r.standard_normal(n), lambda f: m_bp(f, 7500, 1.0), pad=0.0)
    return unit(y) * env_exp(n, 0.025, attack=0.008)


def slap_bass(r, midi, dur, vel, kind):
    """Slap-style synth bass. kind: T = thumb, P = pop (brighter, snappier), X = dead/ghost note."""
    f0 = float(midi_hz(midi))
    if kind == "X":
        n = N(0.08)
        t = T(n)
        y = 0.6 * unitpeak(burst(r, 0.08, 0.01, lambda ff: m_bp(ff, 700, 0.8))) + 0.5 * osc_sine(f0, n) * np.exp(-t / 0.02)
        return 0.45 * vel * y
    n = N(dur + 0.06)
    t = T(n)
    f = f0 * (1.0 + 0.012 * np.exp(-t / 0.012))
    osc = 0.6 * osc_saw(f, n, r.random()) + 0.4 * osc_pulse(f, n, 0.42, r.random())
    if kind == "P":
        cut, q, decay, chp, camp = 900 + (3200 + 2500 * vel) * np.exp(-t / 0.035), 2.0, 0.3, 2200, 0.35
    else:
        cut, q, decay, chp, camp = 670 + (1800 + 1500 * vel) * np.exp(-t / 0.06), 1.6, 0.55, 900, 0.22
    y = svf(osc, cut, q, "lp") + 0.45 * osc_sine(f, n)
    amp = np.exp(-t / decay) * np.clip(t / 0.0008, 0.0, 1.0) * np.interp(t, [0, dur, dur + 0.025], [1, 1, 0])
    y = y * amp + camp * unitpeak(burst(r, n / SR, 0.0025, lambda ff: m_hp(ff, chp, 2)))
    if kind == "P":
        y += 0.15 * modal(n, [(2600.0 * r.uniform(0.95, 1.05), 1.0, 0.006)])
    return vel * saturate(0.8 * y, 1.6)


def brass_stab(r, chord, dur, vel):
    """Synth-brass section stab: 4 detuned saws per note, filter that blooms then closes."""
    n = N(dur + 0.18)
    t = T(n)
    out = np.zeros((n, 2))
    scoop = 2.0 ** ((-30.0 / 1200.0) * np.exp(-t / 0.025))
    for m in chord:
        for k, det in enumerate((-9.0, -3.0, 4.0, 10.0)):
            f = float(midi_hz(m)) * 2.0 ** (det / 1200.0) * scoop
            out += pan(osc_saw(f, n, r.random()), -0.6 + 0.4 * k)
    cut = 500.0 + 3800.0 * vel * (1.0 - np.exp(-t / 0.012)) * (0.55 + 0.45 * np.exp(-t / 0.12))
    out = np.stack([svf(out[:, c], cut, 0.9, "lp") for c in range(2)], axis=1)
    out *= env_adsr(n, 0.008, 0.08, 0.7, dur, 0.07)[:, None]
    return vel * saturate(out / (2.0 * len(chord)), 1.3)


def organ(r, chord, dur, vel, t_abs=0.0):
    """Drawbar organ with key click and a rotary-speaker style L/R amplitude swirl."""
    n = N(dur + 0.08)
    t = T(n)
    y = np.zeros(n)
    for m in chord:
        f = float(midi_hz(m))
        for h, a in ((0.5, 0.6), (1.0, 1.0), (1.5, 0.55), (2.0, 0.5), (3.0, 0.25), (4.0, 0.2)):
            if f * h < 15000:
                y += a * np.sin(TWO_PI * f * h * t + r.uniform(0, TWO_PI))
    y *= env_pts(n, [(0, 0), (0.005, 1), (dur, 1), (dur + 0.05, 0)])
    y += 0.15 * len(chord) * unitpeak(burst(r, n / SR, 0.003, lambda ff: m_hp(ff, 2500, 2)))
    lfo = np.sin(TWO_PI * 6.2 * (t + t_abs))
    return vel * np.stack([y * (1.0 + 0.25 * lfo), y * (1.0 - 0.25 * lfo)], axis=1) / (2.5 * len(chord))


def lead_synth(r, midi, dur, vel):
    """Hook lead: PWM pulse + saw, pitch scoop, delayed vibrato, plucky filter."""
    n = N(dur + 0.12)
    t = T(n)
    f = float(midi_hz(midi)) * 2.0 ** ((-35.0 / 1200.0) * np.exp(-t / 0.02))
    f *= 1.0 + (2.0 ** (14.0 / 1200.0) - 1.0) * np.sin(TWO_PI * 5.6 * t) * np.clip((t - 0.12) / 0.15, 0.0, 1.0)
    pw = 0.32 + 0.08 * np.sin(TWO_PI * 0.7 * t)
    y = 0.7 * osc_pulse(f, n, pw, r.random()) + 0.3 * osc_saw(f * 1.004, n, r.random())
    y = svf(y, 1600.0 + 4800.0 * vel * np.exp(-t / 0.2), 0.9, "lp")
    return vel * y * env_adsr(n, 0.004, 0.15, 0.75, dur, 0.05)


def chip_note(r, midi, dur, vel):
    n = N(dur + 0.01)
    return vel * osc_pulse(float(midi_hz(midi)), n, 0.25, r.random()) * env_exp(n, dur * 0.6, 0.001)


def rhodes(r, midi, dur, vel):
    """FM electric piano: 1:1 FM with decaying index, plus a short tine 'ding'."""
    n = N(dur + 0.3)
    t = T(n)
    f = float(midi_hz(midi))
    I = (0.8 + 2.2 * vel) * np.exp(-t / 0.18) + 0.25
    y = np.sin(TWO_PI * f * t + I * np.sin(TWO_PI * f * t + r.uniform(0, 0.3)))
    if f * 7.0 < 18000:
        y += 0.12 * vel * np.sin(TWO_PI * f * 7.0 * t) * np.exp(-t / 0.03)
    amp = np.exp(-t / 1.2) * np.clip(t / 0.002, 0.0, 1.0) * np.interp(t, [0, dur, dur + 0.15], [1, 1, 0])
    return vel * y * amp


def round_bass(r, midi, dur, vel):
    n = N(dur + 0.08)
    t = T(n)
    f = float(midi_hz(midi))
    y = osc_sine(f, n) + 0.25 * osc_tri(f, n) + 0.12 * osc_saw(f, n)
    y = svf(y, 700.0 + 600.0 * np.exp(-t / 0.08), 0.7, "lp")
    y += 0.15 * unitpeak(burst(r, n / SR, 0.008, lambda ff: m_lp(ff, 800, 2)))
    return vel * y * env_adsr(n, 0.006, 0.4, 0.75, dur, 0.06)


def vibes(r, midi, dur, vel, t_abs=0.0):
    n = N(dur + 0.9)
    t = T(n)
    f = float(midi_hz(midi))
    y = np.sin(TWO_PI * f * t) * np.exp(-t / 1.4) + 0.25 * np.sin(TWO_PI * 4.0 * f * t) * np.exp(-t / 0.3)
    if f * 10.0 < 18000:
        y += 0.06 * np.sin(TWO_PI * 10.0 * f * t) * np.exp(-t / 0.08)
    y += 0.1 * unitpeak(burst(r, n / SR, 0.002, lambda ff: m_hp(ff, 1500, 2)))
    y *= (1.0 + 0.25 * np.sin(TWO_PI * 5.0 * (t + t_abs))) * np.interp(t, [0, dur + 0.3, dur + 0.75], [1, 1, 0])
    return vel * y * np.clip(t / 0.001, 0.0, 1.0)


def set_rms(x, db):
    return x * (float(dbamp(db)) / (rms(x) + 1e-12))


def master_loop(mix, peak_db=-6.0, drive_db=3.0):
    """Loop-safe mastering: circular EQ, glue compression and look-ahead limiting computed as if
    the loop had been playing forever, so the seam stays sample-continuous."""
    mix = fft_filter(mix, lambda f: m_hp(f, 30.0, 2) * m_peak(f, 10000.0, 0.6, 1.5), circular=True)
    mix = process_circular(mix, lambda x: compressor(x, -14.0, 2.0, 0.01, 0.15, 6.0))
    mix = normalize(mix, peak_db + drive_db)
    mix = process_circular(mix, lambda x: limiter(x, peak_db, 0.002, 0.08))
    return normalize(mix, peak_db)


# =============================================================================================
# Music -- arrangements (original compositions)
# =============================================================================================

CHORDS = {  # rootless voicings (MIDI)
    "Em9": [55, 59, 62, 66], "A13": [55, 61, 66, 71], "Cmaj9": [52, 55, 59, 62],
    "B7#9": [51, 57, 62, 66], "B7sus": [52, 57, 59, 66],
}
ROOTS = {"Em9": 40, "A13": 33, "Cmaj9": 36, "B7#9": 35, "B7sus": 35}
FORM = ["Em9", "Em9", "A13", "A13", "Em9", "Em9", "Cmaj9", "B7#9",
        "Em9", "Em9", "A13", "A13", "Cmaj9", "Cmaj9", "B7sus", "B7#9"]

TITLE_BASS = {  # step:note:len:kind  (T thumb, P pop, X dead note)
    "EM_A": "0:E1:3:T 3:E2:1:P 4:E2:1:X 5:E1:1:T 6:G1:1:T 7:A1:1:T 8:B1:2:T 10:E2:1:P 11:D2:1:T 12:D2:1:X "
            "13:E2:1:P 14:G2:1:P 15:E2:1:T",
    "EM_B": "0:E1:2:T 2:E2:1:P 3:E2:1:X 4:E1:1:T 6:D2:1:P 7:E2:1:P 8:E1:2:T 10:E1:1:X 11:B1:1:T 12:D2:1:T "
            "13:D#2:1:T 14:G1:1:T 15:G#1:1:T",
    "A_A": "0:A1:3:T 3:A2:1:P 4:A2:1:X 5:A1:1:T 6:C#2:1:T 7:D2:1:T 8:E2:2:T 10:A2:1:P 11:G2:1:P 12:G2:1:X "
           "13:A2:1:P 14:G2:1:P 15:E2:1:T",
    "A_B": "0:A1:2:T 2:A2:1:P 3:A2:1:X 4:A1:1:T 6:G2:1:P 7:A2:1:P 8:A1:2:T 10:A1:1:X 11:E2:1:T 12:G2:1:T "
           "13:D2:1:T 14:D#2:1:T",
    "C_A": "0:C2:3:T 3:C3:1:P 4:C3:1:X 5:C2:1:T 6:E2:1:T 7:G2:1:T 8:C2:2:T 10:C3:1:P 11:B2:1:P 12:B2:1:X "
           "13:G2:1:T 14:E2:1:T",
    "C_B": "0:C2:2:T 2:C3:1:P 3:C3:1:X 4:C2:1:T 6:B2:1:P 7:C3:1:P 8:G2:2:T 10:E2:1:T 11:E2:1:X 12:C2:1:T "
           "13:D2:1:T 14:D#2:1:T 15:E2:1:T",
    "B7_A": "0:B1:2:T 2:B2:1:P 3:B2:1:X 4:B1:1:T 6:A2:1:P 7:B2:1:P 8:D#2:1:T 10:F#2:1:T 11:A2:1:P 12:B2:1:P "
            "13:B2:1:X 14:F#1:1:T 15:D#2:1:T",
    "B7SUS": "0:B1:3:T 3:B2:1:P 4:B2:1:X 5:B1:1:T 6:E2:1:T 7:F#2:1:T 8:A2:2:P 10:B2:1:P 11:B2:1:X 12:A2:1:P "
             "13:F#2:1:T 14:E2:1:T",
    "B7_B": "0:B1:2:T 2:B2:1:P 3:A2:1:P 4:F#2:1:T 5:F#2:1:X 6:D#2:1:T 8:B1:1:T 9:B1:1:X 10:D2:1:T 11:D#2:1:T "
            "12:F#2:1:P 13:A2:1:P 14:B2:1:P 15:D#2:1:T",
}
TITLE_BASS_FORM = ["EM_A", "EM_B", "A_A", "A_B", "EM_A", "EM_B", "C_A", "B7_A",
                   "EM_A", "EM_B", "A_A", "A_B", "C_A", "C_B", "B7SUS", "B7_B"]

HOOK = [  # the HEAT CHECK hook (E minor pentatonic / dorian), one string per bar
    "2:B4:1 3:D5:1 4:E5:2 6:E5:1 7:G5:2 10:E5:1 11:D5:1 12:E5:3",
    "1:B4:1 2:D5:2 4:B4:1 5:A4:1 6:G4:2 8:A4:1 9:B4:1 10:E4:4",
    "2:C#5:1 3:E5:1 4:F#5:2 6:F#5:1 7:A5:2 10:F#5:1 11:E5:1 12:F#5:3",
    "1:E5:1 2:C#5:2 4:B4:1 5:A4:1 6:G4:2 8:A4:1 9:C#5:1 10:B4:4",
]
TURN = [  # bars 7-8 answer phrase
    "0:G5:2 2:E5:1 3:D5:1 4:E5:2 6:G5:1 7:B5:3 10:A5:1 11:G5:1 12:E5:4",
    "0:F#5:2 2:D#5:1 3:F#5:1 4:A5:2 6:G5:1 7:F#5:1 8:D#5:2 10:B4:4",
]
BRIDGE = [  # bars 13-16
    "0:E5:3 3:G5:1 4:B5:2 6:A5:1 7:G5:1 8:E5:2 10:D5:1 11:E5:1 12:G5:4",
    "2:E5:1 3:G5:1 4:A5:2 6:B5:1 7:D6:2 9:B5:1 10:A5:1 11:G5:1 12:E5:4",
    "0:F#5:2 2:E5:1 3:F#5:1 4:A5:3 7:B5:1 8:A5:2 10:F#5:1 11:E5:1 12:F#5:4",
    "0:D#5:2 2:F#5:1 3:A5:1 4:B5:2 6:A5:1 7:F#5:1 8:D#5:2 13:E5:1 14:D5:1 15:B4:1",
]
TITLE_LEAD = HOOK + HOOK[:2] + TURN + HOOK + BRIDGE

KICK_A = {0: 1.0, 7: 0.8, 10: 0.95}
KICK_B = {0: 1.0, 7: 0.75, 9: 0.6, 10: 0.9, 14: 0.7}
GHOST_A = {9: 0.22, 15: 0.18}
GHOST_B = {2: 0.15, 9: 0.2, 11: 0.15}
STAB_X = [(2, 1, 0.9), (6, 1, 0.8), (11, 2, 1.0)]
STAB_Y = [(0, 1, 0.8), (3, 2, 0.9), (10, 1, 0.8), (14, 2, 1.0)]   # step 14 anticipates the next chord


def song_title():
    """M_Title: 102 BPM funky arcade / hip-hop groove in E dorian, 16 bars, seamless."""
    g = Groove(102, 16, 0.58)
    r = rng_for("m_title")
    L = g.L
    st = {k: np.zeros((L, 2)) for k in ("kick", "snare", "hats", "perc", "bass", "brass", "organ", "lead", "arp", "fx")}
    kicks = [drum_kick(r, 0.22) for _ in range(2)]
    snares = [drum_snare(r) for _ in range(4)]
    claps = [drum_clap(r) for _ in range(2)]
    hats = [drum_hat(r) for _ in range(6)]
    ohats = [drum_hat(r, True) for _ in range(2)]
    shakers = [drum_shaker(r) for _ in range(4)]
    crash = drum_crash(r)
    put = lambda key, sig, bar, step, gain=1.0, p=0.0: mix_circular(
        st[key], (pan(sig, p) if sig.ndim == 1 else sig) * gain, g.at(bar, step))

    for bar in range(16):
        fill = bar in (7, 15)
        kp = {0: 1.0, 7: 0.8, 10: 0.9} if fill else (KICK_B if bar % 2 else KICK_A)
        for s, v in kp.items():
            put("kick", kicks[bar % 2], bar, s, v)
        sn = {4: 1.0, 12: 1.0}
        sn.update(GHOST_B if bar % 2 else GHOST_A)
        if fill:
            sn.update({12: 1.0, 13: 0.55, 14: 0.75, 15: 0.9})
        for s, v in sn.items():
            put("snare", snares[r.integers(4)], bar, s, v * r.uniform(0.92, 1.05), 0.05)
        for s in (4, 12):
            put("snare", claps[bar % 2], bar, s, 0.45 if bar < 8 else 0.7, -0.12)
        for s in range(16):
            if fill and s >= 12:
                continue
            if s == 14 and bar % 2 == 0:              # open hat, choked by the next closed hat
                gap = g.at(bar, 16) - g.at(bar, 14)
                put("hats", fade(ohats[(bar // 2) % 2][:gap], 0.0, 0.012), bar, s, 0.55, 0.3)
                continue
            v = (0.8 if s % 4 == 0 else 0.62 if s % 2 == 0 else 0.36) * r.uniform(0.85, 1.1)
            put("hats", hats[r.integers(6)], bar, s, v, 0.25)
        if bar >= 8:
            for s in range(1, 16, 2):
                put("perc", shakers[r.integers(4)], bar, s, 0.6 * r.uniform(0.8, 1.1), -0.35)
    put("fx", crash, 0, 0, 1.0)
    put("fx", crash, 8, 0, 0.8)
    M = L - g.at(15, 8)                               # reverse cymbal swelling into the loop point
    mix_circular(st["fx"], fade(crash[::-1][-M:], 0.3, 0.0) * 0.6, L - M)

    for bar, pat in enumerate(TITLE_BASS_FORM):
        for s, m, ln, kind, vel in parse_seq(TITLE_BASS[pat]):
            put("bass", slap_bass(r, m, ln * g.step * 0.92, vel * r.uniform(0.92, 1.05), kind or "T"), bar, s)

    for bar in range(16):
        for s, ln, v in (STAB_Y if bar % 2 else STAB_X):
            chord = [m + 12 for m in CHORDS[FORM[(bar + 1) % 16] if s == 14 else FORM[bar]]]
            put("brass", brass_stab(r, chord, ln * g.step * 0.8, v), bar, s)
    for bar in range(8, 16):
        put("organ", organ(r, CHORDS[FORM[bar]], 16 * g.step * 0.97, 0.8, t_abs=g.time(bar, 0)), bar, 0)

    for bar, phrase in enumerate(TITLE_LEAD):
        for s, m, ln, _, vel in parse_seq(phrase):
            put("lead", lead_synth(r, m, ln * g.step * 0.9, 0.9 * vel), bar, s)
            if 8 <= bar < 12:                          # octave double on the second hook pass
                put("lead", lead_synth(r, m - 12, ln * g.step * 0.9, 0.9 * vel), bar, s, 0.4)
    for bar in range(12, 16):                          # chip arpeggio lift in the bridge
        tones = [m + 24 for m in CHORDS[FORM[bar]]]
        seq = tones + tones[-2:0:-1]
        for s in range(16):
            put("arp", chip_note(r, seq[s % len(seq)], g.step * 0.7, 0.55 if s % 2 == 0 else 0.4), bar, s, 1.0,
                0.35 if s % 2 else -0.35)

    st["lead"] = echo(st["lead"], 3 * g.step, 0.3, 0.22, repeats=4, lp_hz=4000, hp_hz=400, circular=True)
    st["arp"] = echo(st["arp"], 3 * g.step, 0.3, 0.25, repeats=3, circular=True)
    levels = {"kick": -15.0, "snare": -18.5, "hats": -26.0, "perc": -30.0, "bass": -15.5, "brass": -20.5,
              "organ": -26.0, "lead": -18.5, "arp": -29.0, "fx": -27.0}
    for k, d in levels.items():
        st[k] = set_rms(st[k], d)
    send = (0.25 * st["snare"] + 0.3 * st["brass"] + 0.22 * st["lead"] + 0.35 * st["organ"] + 0.2 * st["arp"]
            + 0.15 * st["fx"])
    wet = convolve_circular(send, reverb_ir(rng_for("m_title_ir"), rt60=1.5, length=1.8, predelay=0.02))
    mix = sum(st.values()) + 0.5 * wet
    return master_loop(mix, -6.0), g


def song_halftime():
    """M_Halftime: 90 BPM laid-back reprise of the HEAT CHECK theme (Rhodes, round bass, vibes), 16 bars."""
    g = Groove(90, 16, 0.62)
    r = rng_for("m_halftime")
    L = g.L
    st = {k: np.zeros((L, 2)) for k in ("kick", "snare", "hats", "bass", "keys", "vibes", "vinyl")}
    kicks = [drum_kick(r, 0.3) for _ in range(2)]
    snares = [iir(drum_snare(r, 0.8), biquad("lp", 7000, 0.7)) for _ in range(3)]
    hats = [drum_hat(r) for _ in range(4)]
    put = lambda key, sig, bar, step, gain=1.0, p=0.0: mix_circular(
        st[key], (pan(sig, p) if sig.ndim == 1 else sig) * gain, g.at(bar, step))
    for bar in range(16):
        for s, v in ({0: 1.0, 3: 0.45, 8: 0.6, 10: 0.85} if bar % 2 else {0: 1.0, 10: 0.85}).items():
            put("kick", kicks[bar % 2], bar, s, v)
        for s, v in {4: 0.85, 12: 0.9, 15: 0.15 if bar % 2 else 0.0}.items():
            if v:
                put("snare", snares[r.integers(3)], bar, s, v * r.uniform(0.92, 1.05), 0.05)
        for s in range(16):
            v = 0.5 if s % 2 == 0 else (0.18 if s in (3, 11, 15) else 0.0)
            if v:
                put("hats", hats[r.integers(4)], bar, s, v * r.uniform(0.85, 1.1), 0.2)
        ch, nxt = FORM[bar], FORM[(bar + 1) % 16]
        root = ROOTS[ch]
        for s, m, ln in ((0, root, 5), (7, root + 7, 2), (10, root + 12, 3), (14, ROOTS[nxt] - 1, 2)):
            put("bass", round_bass(r, m, ln * g.step * 0.9, 0.9), bar, s)
        for s, ln, v in ((0, 5, 0.75), (7, 3, 0.55), (11, 4, 0.62)):
            tt = g.time(bar, s)
            y = sum(rhodes(r, m, ln * g.step * 0.95, v * r.uniform(0.9, 1.05)) for m in CHORDS[ch])
            lfo = np.sin(TWO_PI * 4.5 * (T(y.shape[0]) + tt))
            put("keys", np.stack([y * (1 + 0.3 * lfo), y * (1 - 0.3 * lfo)], axis=1), bar, s)
    for bars, phrases in ((range(4, 8), HOOK), (range(12, 16), BRIDGE)):
        for bar, phrase in zip(bars, phrases):
            for s, m, ln, _, vel in parse_seq(phrase):
                put("vibes", vibes(r, m, ln * g.step, 0.8 * vel, t_abs=g.time(bar, s)), bar, s, 1.0, -0.15)
    crk = crackles(r, L, lambda tt: 7.0, big_prob=0.03, circular=True)
    hiss = shaped_noise(r, L, lambda f: m_bp(f, 4000, 0.4))
    st["vinyl"] = pan(fft_filter(crk, lambda f: m_lp(f, 5000, 1), circular=True) + 0.02 * hiss, 0.0)
    levels = {"kick": -16.0, "snare": -21.0, "hats": -29.0, "bass": -16.5, "keys": -19.5, "vibes": -21.5,
              "vinyl": -40.0}
    for k, d in levels.items():
        st[k] = set_rms(st[k], d)
    send = 0.25 * st["snare"] + 0.3 * st["keys"] + 0.4 * st["vibes"]
    wet = convolve_circular(send, reverb_ir(rng_for("m_half_ir"), rt60=1.8, length=2.0, predelay=0.025))
    mix = sum(st.values()) + 0.5 * wet
    mix = fft_filter(mix, lambda f: m_lp(f, 12000, 1), circular=True)
    return master_loop(mix, -6.0), g


# =============================================================================================
# Announcer (macOS `say` -> afconvert -> numpy arena-PA processing)
# =============================================================================================

# Chosen after rendering a test phrase with every installed en_US/en_GB voice (Daniel, Eddy, Reed,
# Rocko, Grandpa, Fred, Ralph, Albert, Junior, Samantha, Aman, Rishi) at rates 180-240 and measuring
# pitch range / bandwidth / micro-prosody: "Daniel" is the most natural male voice installed. The
# [[pbas +5]] nudge raises its median pitch ~130 -> ~154 Hz (a more excited register). Rate scales with
# line length (185 / 200 / 210 wpm) so the short calls land with weight. Requires the Daniel voice.
VO_VOICE = "Daniel"
VO_PITCH = "[[pbas +5]] "


def vo_rate(text):
    words = len(text.split())
    return 185 if words <= 2 else (200 if words <= 4 else 210)


VO_LINES = [
    ("VO_Welcome", "Welcome to Heat Check!"), ("VO_TipOff", "Here we go!"), ("VO_TipOff_02", "Tip off!"),
    ("VO_Dunk_01", "Slam!"), ("VO_Dunk_02", "Throw it down!"), ("VO_Dunk_03", "Posterized!"),
    ("VO_Dunk_04", "Monster slam!"), ("VO_Dunk_05", "Rim rocker!"),
    ("VO_Three_01", "Bang! Three!"), ("VO_Three_02", "Splash! From deep!"), ("VO_Three_03", "Long range bomb!"),
    ("VO_Score_01", "Count it!"), ("VO_Score_02", "Bucket!"), ("VO_Score_03", "Nothing but net!"),
    ("VO_Block_01", "Rejected!"), ("VO_Block_02", "Denied!"), ("VO_Block_03", "Get that outta here!"),
    ("VO_Steal_01", "Stolen!"), ("VO_Steal_02", "Pick pocket!"),
    ("VO_Shove_01", "Flattened!"), ("VO_Shove_02", "Bulldozed!"),
    ("VO_Warm_01", "Getting warm!"), ("VO_Warm_02", "Feeling it!"),
    ("VO_Fire_01", "Scorching hot!"), ("VO_Fire_02", "Somebody call the fire department!"),
    ("VO_Fire_03", "Too hot to handle!"), ("VO_FireOut", "The fire's out!"),
    ("VO_AlleyOop", "Alley oop!"), ("VO_Goaltending", "Goaltending!"), ("VO_ShotClock", "Shot clock violation!"),
    ("VO_Miss_01", "Off the rim!"), ("VO_Miss_02", "Brick!"),
    ("VO_EndQuarter", "End of the quarter!"), ("VO_Halftime", "That's halftime!"), ("VO_FinalBuzzer", "That's the game!"),
    ("VO_Overtime", "We're going to overtime!"), ("VO_Buzzer", "At the buzzer!"),
    ("VO_Team_NEO", "Neon City Voltage!"), ("VO_Team_BAY", "Bay Harbor Krakens!"), ("VO_Team_RRK", "Red Rock Scorpions!"),
    ("VO_Team_FRB", "Frostburg Yetis!"), ("VO_Team_STV", "Steel Valley Forge!"), ("VO_Team_SSC", "Sunset Coast Surge!"),
]


def say_render(text, rate, tmpdir, tag):
    """Render one line with macOS `say` and convert it to 48 kHz 16-bit WAV; returns float mono."""
    aiff = os.path.join(tmpdir, tag + ".aiff")
    wav = os.path.join(tmpdir, tag + ".wav")
    subprocess.run(["say", "-v", VO_VOICE, "-r", str(rate), "-o", aiff, VO_PITCH + text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@48000", "--src-complexity", "bats", "-r", "127",
                    aiff, wav], check=True)
    x, sr = read_wav(wav)
    if sr != SR or x.ndim != 1 or x.shape[0] < N(0.15) or peak(x) < 0.01:
        raise RuntimeError("say produced unusable audio for %r (sr=%s, n=%d)" % (text, sr, x.shape[0]))
    return x


def vo_process(x):
    """Arena PA chain: HPF 120 Hz -> presence EQ -> gentle saturation -> compression -> limiting
    -> short slapback -> arena reverb tail (~0.7 s) -> normalize to -1 dBFS."""
    x = trim_tail(trim_lead(x, -40.0, preroll=0.012), -50.0)
    x = normalize(x, -1.0)
    x = iir(x, biquad("hp", 120, 0.5412), biquad("hp", 120, 1.3066))           # 4th-order Butterworth
    x = iir(x, biquad("peak", 300, 1.0, -2.0), biquad("peak", 3200, 0.9, 3.5), biquad("highshelf", 9000, 0.7, 1.5))
    x = saturate(normalize(x, -1.0), drive=2.2, mix=0.5)
    x = compressor(x, thresh_db=-22.0, ratio=4.0, attack=0.003, release=0.09, knee_db=6.0)
    x = limiter(normalize(x, 1.5), ceiling_db=-1.0, lookahead=0.002, release=0.06)
    d = N(0.085)
    slap = iir(x, biquad("hp", 300, 0.7), biquad("lp", 3500, 0.7))
    y = pad_to(x, x.shape[0] + d)
    y[d:] += 0.22 * slap
    ir = ir_cached("vo_arena", rt60=1.15, length=0.75, predelay=0.02, stereo=False)
    y = add_reverb(y, ir, wet=0.2)
    y = fade(trim_tail(y, -60.0), 0.003, 0.08)
    return normalize(y, -1.0)


# =============================================================================================
# Previews (numpy -> PNG, no matplotlib needed)
# =============================================================================================

FONT = {  # 5x7 bitmap glyphs, one int per row (bit 4 = leftmost pixel)
    "A": (14, 17, 17, 17, 31, 17, 17), "B": (30, 17, 17, 30, 17, 17, 30), "C": (14, 17, 16, 16, 16, 17, 14),
    "D": (28, 18, 17, 17, 17, 18, 28), "E": (31, 16, 16, 30, 16, 16, 31), "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (14, 17, 16, 23, 17, 17, 15), "H": (17, 17, 17, 31, 17, 17, 17), "I": (14, 4, 4, 4, 4, 4, 14),
    "J": (7, 2, 2, 2, 2, 18, 12), "K": (17, 18, 20, 24, 20, 18, 17), "L": (16, 16, 16, 16, 16, 16, 31),
    "M": (17, 27, 21, 21, 17, 17, 17), "N": (17, 17, 25, 21, 19, 17, 17), "O": (14, 17, 17, 17, 17, 17, 14),
    "P": (30, 17, 17, 30, 16, 16, 16), "Q": (14, 17, 17, 17, 21, 18, 13), "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30), "T": (31, 4, 4, 4, 4, 4, 4), "U": (17, 17, 17, 17, 17, 17, 14),
    "V": (17, 17, 17, 17, 17, 10, 4), "W": (17, 17, 17, 21, 21, 21, 10), "X": (17, 17, 10, 4, 10, 17, 17),
    "Y": (17, 17, 17, 10, 4, 4, 4), "Z": (31, 1, 2, 4, 8, 16, 31),
    "0": (14, 17, 19, 21, 25, 17, 14), "1": (4, 12, 4, 4, 4, 4, 14), "2": (14, 17, 1, 2, 4, 8, 31),
    "3": (31, 2, 4, 2, 1, 17, 14), "4": (2, 6, 10, 18, 31, 2, 2), "5": (31, 16, 30, 1, 1, 17, 14),
    "6": (6, 8, 16, 30, 17, 17, 14), "7": (31, 1, 2, 4, 8, 8, 8), "8": (14, 17, 17, 14, 17, 17, 14),
    "9": (14, 17, 17, 15, 1, 2, 12), "_": (0, 0, 0, 0, 0, 0, 31), "-": (0, 0, 0, 31, 0, 0, 0),
    ".": (0, 0, 0, 0, 0, 12, 12), ":": (0, 12, 12, 0, 12, 12, 0), "(": (2, 4, 8, 8, 8, 4, 2),
    ")": (8, 4, 2, 2, 2, 4, 8), "/": (0, 1, 2, 4, 8, 16, 0), "%": (24, 25, 2, 4, 8, 19, 3),
    "=": (0, 0, 31, 0, 31, 0, 0), "+": (0, 4, 4, 31, 4, 4, 0), ",": (0, 0, 0, 0, 12, 4, 8),
    "'": (12, 4, 8, 0, 0, 0, 0), "!": (4, 4, 4, 4, 4, 0, 4), "?": (14, 17, 1, 2, 4, 0, 4),
    "#": (10, 10, 31, 10, 31, 10, 10), "|": (4, 4, 4, 4, 4, 4, 4),
}
INFERNO = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21],
                    [250, 193, 39], [252, 255, 164]], dtype=np.float64)
BG, PANEL, GRID = (18, 19, 24), (28, 30, 38), (55, 58, 70)


def draw_text(img, x, y, text, color=(225, 225, 230), scale=1):
    for chh in text.upper():
        glyph = FONT.get(chh)
        if glyph:
            for row, bits in enumerate(glyph):
                for col in range(5):
                    if bits & (1 << (4 - col)):
                        img[y + row * scale:y + (row + 1) * scale, x + col * scale:x + (col + 1) * scale] = color
        x += 6 * scale


def write_png(path, img):
    img = np.ascontiguousarray(img, dtype=np.uint8)
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _mono(sig):
    return sig[:, 0] if sig.ndim == 2 else sig


def draw_wave(img, x0, y0, w, h, sig, color=(90, 200, 255), span=None, zoom=False):
    """Min/max waveform (+ RMS core). span: seconds represented by the full width (None = fit)."""
    img[y0:y0 + h, x0:x0 + w] = PANEL
    s = _mono(sig)
    n_span = N(span) if span else s.shape[0]
    cols = max(1, min(w, int(round(w * s.shape[0] / n_span))))
    mid = y0 + h // 2
    img[mid, x0:x0 + w] = GRID
    for lvl in (0.5,):
        img[mid - int(lvl * (h // 2 - 1)), x0:x0 + w] = (36, 38, 48)
        img[mid + int(lvl * (h // 2 - 1)), x0:x0 + w] = (36, 38, 48)
    scale = (1.0 / (peak(s) + 1e-12)) if zoom else 1.0
    edges = np.linspace(0, s.shape[0], cols + 1).astype(int)
    for c in range(cols):
        seg = s[edges[c]:max(edges[c + 1], edges[c] + 1)] * scale
        mn, mx = float(seg.min()), float(seg.max())
        r_ = math.sqrt(float(np.mean(seg ** 2)))
        a = int(np.clip(mid - mx * (h // 2 - 1), y0, y0 + h - 1))
        b = int(np.clip(mid - mn * (h // 2 - 1), y0, y0 + h - 1))
        img[a:b + 1, x0 + c] = tuple(int(v * 0.55) for v in color)
        a2 = int(np.clip(mid - r_ * (h // 2 - 1), y0, y0 + h - 1))
        b2 = int(np.clip(mid + r_ * (h // 2 - 1), y0, y0 + h - 1))
        img[a2:b2 + 1, x0 + c] = color


def draw_spec(img, x0, y0, w, h, sig, span=None, fmin=40.0, fmax=20000.0, dyn=80.0):
    """Log-frequency spectrogram (inferno colours), 0 dB = loudest bin of the clip."""
    img[y0:y0 + h, x0:x0 + w] = (0, 0, 4)
    s = _mono(sig)
    n_span = N(span) if span else s.shape[0]
    cols = max(1, min(w, int(round(w * s.shape[0] / n_span))))
    nfft = 2048
    xp = np.pad(s, (nfft // 2, nfft))
    centers = np.linspace(0, s.shape[0] - 1, cols).astype(int)
    idx = centers[:, None] + np.arange(nfft)[None, :]
    S = np.abs(np.fft.rfft(xp[idx] * np.hanning(nfft), axis=1))
    D = 20.0 * np.log10(S + 1e-9)
    D = np.clip((D - (D.max() - dyn)) / dyn, 0.0, 1.0)
    freqs = fmin * (fmax / fmin) ** (np.arange(h)[::-1] / (h - 1))
    bins = np.clip(np.round(freqs / (SR / nfft)).astype(int), 1, nfft // 2)
    V = D[:, bins].T                                    # (h, cols)
    pos = V * (INFERNO.shape[0] - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, INFERNO.shape[0] - 1)
    fr = (pos - lo)[..., None]
    img[y0:y0 + h, x0:x0 + cols] = (INFERNO[lo] * (1 - fr) + INFERNO[hi] * fr).astype(np.uint8)
    for f in (100, 1000, 10000):                        # frequency guides
        yy = y0 + int(round((h - 1) * (1 - math.log(f / fmin) / math.log(fmax / fmin))))
        img[yy, x0:x0 + w:4] = (120, 120, 140)


def preview_grid(path, title, items, mode, cols=4, cw=300, chh=80, span=None):
    """items: [(label, signal, sublabel)] -> one PNG page of waveforms or spectrograms."""
    pad, lab = 10, 26
    rows = (len(items) + cols - 1) // cols
    W = pad + cols * (cw + pad)
    H = 34 + rows * (chh + lab + pad) + pad
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[:] = BG
    draw_text(img, pad, 10, title, (255, 170, 60), 2)
    for k, (label, sig, sub) in enumerate(items):
        x = pad + (k % cols) * (cw + pad)
        y = 34 + (k // cols) * (chh + lab + pad)
        draw_text(img, x, y + 2, label, (235, 235, 240))
        draw_text(img, x, y + 13, sub, (140, 145, 160))
        if mode == "wave":
            draw_wave(img, x, y + lab, cw, chh, sig, span=span)
        else:
            draw_spec(img, x, y + lab, cw, chh, sig, span=span)
    write_png(path, img)


def preview_seams(path, loops):
    """+-20 ms around each loop's wrap point (end -> start), auto-zoomed; red line = seam."""
    pad, cw, chh = 10, 560, 110
    H = 34 + len(loops) * (chh + 36) + pad
    img = np.zeros((H, pad * 2 + cw, 3), dtype=np.uint8)
    img[:] = BG
    draw_text(img, pad, 10, "LOOP SEAMS (+-20 MS, AUTO-ZOOM)", (255, 170, 60), 2)
    for k, (name, sig, sub) in enumerate(loops):
        y = 34 + k * (chh + 36)
        w = N(0.02)
        seg = np.concatenate([sig[-w:], sig[:w]], axis=0)
        draw_text(img, pad, y + 2, name, (235, 235, 240))
        draw_text(img, pad, y + 13, sub, (140, 145, 160))
        draw_wave(img, pad, y + 26, cw, chh, seg, zoom=True)
        img[y + 26:y + 26 + chh, pad + cw // 2] = (230, 60, 60)
    write_png(path, img)


def preview_music(path, tracks):
    pad, cw = 10, 1180
    H = 34 + len(tracks) * (26 + 90 + 6 + 200 + 20) + pad
    img = np.zeros((H, pad * 2 + cw, 3), dtype=np.uint8)
    img[:] = BG
    draw_text(img, pad, 10, "MUSIC LOOPS", (255, 170, 60), 2)
    y = 34
    for name, sig, sub, bars in tracks:
        draw_text(img, pad, y + 2, name, (235, 235, 240))
        draw_text(img, pad, y + 13, sub, (140, 145, 160))
        draw_wave(img, pad, y + 26, cw, 90, sig)
        for b in range(1, bars):                      # bar lines
            img[y + 26:y + 116, pad + int(cw * b / bars)] = (70, 72, 90) if b % 4 else (120, 90, 60)
        draw_spec(img, pad, y + 122, cw, 200, sig)
        y += 26 + 90 + 6 + 200 + 20
    write_png(path, img)


# =============================================================================================
# Verification
# =============================================================================================


def analyze(x, loop):
    a = as2d(x)
    info = {"peak_dbfs": round(amp2db(peak(a)), 2), "rms_dbfs": round(amp2db(rms(a)), 2),
            "clipped_samples": int(np.sum(np.abs(a) >= 32767.0 / 32768.0)),
            "dc_offset": round(float(np.max(np.abs(np.mean(a, axis=0)))), 5)}
    if loop:
        d = np.abs(np.diff(a, axis=0))
        typical = np.percentile(d, 99.9, axis=0) + 1e-9
        info["seam_jump_ratio"] = round(float(np.max(np.abs(a[0] - a[-1]) / typical)), 3)
        w = N(0.1)
        info["seam_rms_db_delta"] = round(abs(amp2db(rms(a[-w:])) - amp2db(rms(a[:w]))), 2)
    else:
        mag = _detector(a)
        info["onset_ms"] = round(1000.0 * int(np.argmax(mag > peak(a) * 0.01)) / SR, 2)
    return info


def verify_entry(e):
    """Re-read a written WAV and check it against its manifest entry. Returns (info, problems)."""
    x, sr = read_wav(os.path.join(OUT_DIR, e["file"]))
    probs = []
    ch = 1 if x.ndim == 1 else x.shape[1]
    if sr != SR:
        probs.append("sample rate %d" % sr)
    if ch != e["channels"]:
        probs.append("channels %d != %d" % (ch, e["channels"]))
    info = analyze(x, e["loop"])
    if info["clipped_samples"] > 0:
        probs.append("%d clipped samples" % info["clipped_samples"])
    if info["peak_dbfs"] > -0.5:
        probs.append("peak too hot")
    if e["loop"] and info["seam_jump_ratio"] > 1.0:
        probs.append("loop seam discontinuity")
    if not e["loop"] and info["onset_ms"] > 2.0 and e["category"] != "vo":
        probs.append("leading silence %.1f ms" % info["onset_ms"])
    if abs(x.shape[0] / SR - e["duration"]) > 1e-3:
        probs.append("duration mismatch")
    return x, info, probs


def preview_pairs(path, title, items, cw=560, chh=90):
    """One row per item: waveform (left) and spectrogram (right)."""
    pad, lab = 10, 26
    H = 34 + len(items) * (chh + lab + pad) + pad
    img = np.zeros((H, pad * 3 + 2 * cw, 3), dtype=np.uint8)
    img[:] = BG
    draw_text(img, pad, 10, title, (255, 170, 60), 2)
    for k, (label, sig, sub) in enumerate(items):
        y = 34 + k * (chh + lab + pad)
        draw_text(img, pad, y + 2, label, (235, 235, 240))
        draw_text(img, pad, y + 13, sub, (140, 145, 160))
        draw_wave(img, pad, y + lab, cw, chh, sig)
        draw_spec(img, 2 * pad + cw, y + lab, cw, chh, sig)
    write_png(path, img)


def render_previews(files, signals):
    def sub(e):
        s = "%.3fS  %dCH  PK %.1f  RMS %.1f" % (e["duration"], e["channels"], e["peak_dbfs"], e["rms_dbfs"])
        return s + ("  LOOP" if e["loop"] else "")

    def items(pred):
        return [(e["name"], signals[e["name"]], sub(e)) for e in files if pred(e) and e["name"] in signals]

    out = []
    one = items(lambda e: e["category"] in ("sfx", "ui") and not e["loop"] and not e["name"].startswith("S_Fire"))
    if one:
        out.append(os.path.join(PREVIEW_DIR, "audio_sfx_waveforms.png"))
        preview_grid(out[-1], "SFX + UI WAVEFORMS (EACH FIT TO WIDTH)", one, "wave", cols=4, cw=300, chh=70)
        out.append(os.path.join(PREVIEW_DIR, "audio_sfx_spectrograms.png"))
        preview_grid(out[-1], "SFX + UI SPECTROGRAMS (40 HZ-20 KHZ LOG, 80 DB)", one, "spec", cols=4, cw=300, chh=90)
    cf = items(lambda e: e["category"] == "crowd" or e["name"].startswith("S_Fire"))
    if cf:
        out.append(os.path.join(PREVIEW_DIR, "audio_crowd_fire.png"))
        preview_pairs(out[-1], "CROWD + FIRE (WAVEFORM | SPECTROGRAM, LEFT CH)", cf)
    vo = items(lambda e: e["category"] == "vo")
    if vo:
        out.append(os.path.join(PREVIEW_DIR, "audio_vo_waveforms.png"))
        preview_grid(out[-1], "ANNOUNCER WAVEFORMS", vo, "wave", cols=4, cw=300, chh=60)
        out.append(os.path.join(PREVIEW_DIR, "audio_vo_spectrograms.png"))
        preview_grid(out[-1], "ANNOUNCER SPECTROGRAMS", vo, "spec", cols=4, cw=300, chh=80)
    mus = [(e["name"], signals[e["name"]], sub(e) + "  %d BPM  %d BARS" % (e["bpm"], e["bars"]), e["bars"])
           for e in files if e["category"] == "music" and e["name"] in signals]
    if mus:
        out.append(os.path.join(PREVIEW_DIR, "audio_music.png"))
        preview_music(out[-1], mus)
    loops = items(lambda e: e["loop"])
    if loops:
        out.append(os.path.join(PREVIEW_DIR, "audio_loop_seams.png"))
        preview_seams(out[-1], [(n, s, t + "  SEAM RATIO %.2f" % next(e["seam_jump_ratio"] for e in files if e["name"] == n))
                                for n, s, t in loops])
    return out


# =============================================================================================
# Catalog + main
# =============================================================================================


def catalog():
    C = []

    def add(name, fn, cat, vol, desc, loop=False, fin=None, **extra):
        C.append(dict(name=name, fn=fn, category=cat, volume=vol, description=desc, loop=loop, fin=fin or {},
                      extra=extra))

    for i in range(3):
        add("S_Bounce_%02d" % (i + 1), lambda i=i: sfx_bounce(i), "sfx", 0.75, "Basketball dribble/bounce on hardwood",
            fin=dict(max_len=0.26, fade_out=0.08))
    for i in range(2):
        add("S_Swish_%02d" % (i + 1), lambda i=i: sfx_swish(i), "sfx", 0.7, "Ball through the net (swish)",
            fin=dict(max_len=0.6, fade_out=0.08))
    for i in range(3):
        add("S_RimHit_%02d" % (i + 1), lambda i=i: sfx_rim(i), "sfx", 0.65, "Ball clanking off the steel rim",
            fin=dict(max_len=0.65, fade_out=0.12))
    add("S_Backboard", sfx_backboard, "sfx", 0.7, "Ball off the backboard (thud + rattle)",
        fin=dict(max_len=0.55, fade_out=0.1))
    add("S_DunkSlam", sfx_dunk, "sfx", 0.9, "Dunk: rim/backboard slam, stanchion boom, rattle",
        fin=dict(max_len=1.1, fade_out=0.25))
    for i in range(4):
        add("S_Squeak_%02d" % (i + 1), lambda i=i: sfx_squeak(i), "sfx", 0.4, "Sneaker squeak",
            fin=dict(max_len=0.25, fade_out=0.03))
    add("S_Pass", sfx_pass, "sfx", 0.5, "Pass whoosh", fin=dict(max_len=0.27, fade_out=0.03))
    add("S_Steal", sfx_steal, "sfx", 0.6, "Steal: hand slap/swipe", fin=dict(max_len=0.22, fade_out=0.05))
    add("S_Block", sfx_block, "sfx", 0.75, "Block: hand smacking the ball", fin=dict(max_len=0.28, fade_out=0.06))
    add("S_Shove", sfx_shove, "sfx", 0.7, "Shove: body-check thump", fin=dict(max_len=0.32, fade_out=0.06))
    add("S_Fall", sfx_fall, "sfx", 0.7, "Player hitting the floor", fin=dict(max_len=0.45, fade_out=0.08))
    add("S_Buzzer", sfx_buzzer, "sfx", 0.8, "End-of-quarter arena horn", fin=dict(max_len=1.65, fade_out=0.25))
    add("S_ShotClock", sfx_shotclock, "sfx", 0.7, "Shot-clock violation buzzer", fin=dict(max_len=0.82, fade_out=0.15))
    add("S_Whistle", sfx_whistle, "sfx", 0.6, "Referee whistle", fin=dict(max_len=0.66, fade_out=0.1))
    add("S_FireIgnite", sfx_fire_ignite, "sfx", 0.8, "Player catches fire: whoosh + crackle",
        fin=dict(max_len=1.5, fade_out=0.3))
    add("S_FireLoop", sfx_fire_loop, "sfx", 0.45, "Seamless crackling fire loop (attach to the on-fire player)",
        loop=True)
    add("S_FireBasket", sfx_fire_basket, "sfx", 0.85, "On-fire made basket: flaming-net fwoosh",
        fin=dict(max_len=1.2, fade_out=0.3))
    add("S_UI_Move", ui_move, "ui", 0.4, "Menu cursor move blip", fin=dict(fade_out=0.01))
    add("S_UI_Select", ui_select, "ui", 0.5, "Menu select / confirm", fin=dict(fade_out=0.03))
    add("S_UI_Back", ui_back, "ui", 0.45, "Menu back / cancel", fin=dict(fade_out=0.02))
    add("S_UI_Start", ui_start, "ui", 0.6, "Press-start arcade jingle", fin=dict(fade_out=0.1))
    add("S_Score", sfx_score, "ui", 0.6, "Made-basket stinger", fin=dict(fade_out=0.06))
    add("S_Countdown", sfx_countdown, "ui", 0.5, "Last-seconds clock tick", fin=dict(fade_out=0.01))
    add("S_CrowdLoop", crowd_loop, "crowd", 0.5, "Seamless arena crowd bed (murmur, claps, distant whoos)", loop=True)
    for i in range(2):
        add("S_CrowdCheer_%02d" % (i + 1), lambda i=i: crowd_cheer(i), "crowd", 0.7, "Crowd cheer swell",
            fin=dict(fade_out=0.4, lead_db=-30.0, fade_in=0.001))
    add("S_CrowdBigCheer", crowd_big_cheer, "crowd", 0.8, "Big crowd roar (dunks, fire, buzzer beaters)",
        fin=dict(fade_out=0.6, lead_db=-30.0, fade_in=0.001))
    add("S_CrowdOoh", crowd_ooh, "crowd", 0.65, "Crowd 'oooh' (blocks, near misses)", fin=dict(fade_out=0.3, lead_db=-30.0, fade_in=0.001))
    add("S_CrowdGroan", crowd_groan, "crowd", 0.6, "Crowd groan", fin=dict(fade_out=0.3, lead_db=-30.0, fade_in=0.001))
    add("M_Title", song_title, "music", 0.7,
        "Title / menus / in-game: 102 BPM funky arcade hip-hop groove, E dorian, 16 bars", loop=True)
    add("M_Halftime", song_halftime, "music", 0.6, "Halftime: 90 BPM laid-back reprise of the theme, 16 bars",
        loop=True)
    for name, text in VO_LINES:
        add(name, None, "vo", 1.0, "Announcer line", text=text)
    return C


def build(item, tmpdir):
    name, cat = item["name"], item["category"]
    extra = dict(item["extra"])
    if cat == "vo":
        rate = vo_rate(extra["text"])
        x = vo_process(say_render(extra["text"], rate, tmpdir, name))
        extra.update(voice=VO_VOICE, rate=rate)
    elif cat == "music":
        x, g = item["fn"]()
        extra.update(bpm=g.bpm, bars=g.bars, swing=g.swing, loop_start_sample=0, loop_end_sample=int(x.shape[0]))
    elif item["loop"]:
        x = normalize(item["fn"](), -3.0)
        extra.update(loop_start_sample=0, loop_end_sample=int(x.shape[0]))
    else:
        x = finalize_oneshot(item["fn"](), **item["fin"])
    write_wav(os.path.join(OUT_DIR, name + ".wav"), x, seed=zlib.crc32(name.encode("utf-8")))
    e = dict(name=name, file=name + ".wav", category=cat, duration=round(x.shape[0] / SR, 4), samples=int(x.shape[0]),
             channels=1 if x.ndim == 1 else int(x.shape[1]), loop=bool(item["loop"]), volume=item["volume"],
             description=item["description"])
    e.update(extra)
    return e


def main():
    ap = argparse.ArgumentParser(description="HEAT CHECK procedural audio generator")
    ap.add_argument("--only", default="", help="comma-separated name prefixes to (re)generate")
    ap.add_argument("--no-vo", action="store_true", help="skip announcer lines")
    ap.add_argument("--no-previews", action="store_true", help="skip PNG previews")
    ap.add_argument("--check", action="store_true", help="only verify existing files")
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    mpath = os.path.join(OUT_DIR, "manifest.json")
    entries = {}
    if os.path.exists(mpath):
        with open(mpath) as fh:
            entries = {e["name"]: e for e in json.load(fh).get("files", [])}
    cat = catalog()
    order = {it["name"]: k for k, it in enumerate(cat)}
    if not args.check:
        prefixes = [p.strip() for p in args.only.split(",") if p.strip()]
        todo = [it for it in cat if not prefixes or any(it["name"].startswith(p) for p in prefixes)]
        if args.no_vo:
            todo = [it for it in todo if it["category"] != "vo"]
        if any(it["category"] == "vo" for it in todo) and not (shutil.which("say") and shutil.which("afconvert")):
            sys.exit("macOS `say`/`afconvert` not found -- rerun with --no-vo")
        t_all = time.time()
        with tempfile.TemporaryDirectory(prefix="hc_vo_") as tmp:
            for k, it in enumerate(todo):
                t0 = time.time()
                e = build(it, tmp)
                entries[e["name"]] = e
                print("[%2d/%d] %-18s %7.3f s  %d ch%s  (%.1f s)" % (k + 1, len(todo), e["name"], e["duration"],
                      e["channels"], "  loop" if e["loop"] else "", time.time() - t0), flush=True)
        print("generated %d assets in %.1f s" % (len(todo), time.time() - t_all))

    files = sorted(entries.values(), key=lambda e: (order.get(e["name"], 10 ** 6), e["name"]))
    signals, failures = {}, 0
    print("\n%-18s %8s %3s %5s %7s %7s  %s" % ("name", "dur(s)", "ch", "loop", "peak", "rms", "checks"))
    for e in files:
        x, info, probs = verify_entry(e)
        signals[e["name"]] = x
        e["peak_dbfs"], e["rms_dbfs"] = info["peak_dbfs"], info["rms_dbfs"]
        if e["loop"]:
            e["seam_jump_ratio"] = info["seam_jump_ratio"]
            check = "seam %.2f (<=1 ok), seam rms delta %.1f dB" % (info["seam_jump_ratio"], info["seam_rms_db_delta"])
        else:
            check = "onset %.2f ms" % info["onset_ms"]
        failures += bool(probs)
        print("%-18s %8.3f %3d %5s %7.2f %7.2f  %s%s" % (e["name"], e["duration"], e["channels"], "yes" if e["loop"] else "",
              info["peak_dbfs"], info["rms_dbfs"], check, ("  !! " + "; ".join(probs)) if probs else ""))
    manifest = {
        "generator": "Tools/gen_audio.py (procedural; deterministic)",
        "format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": SR},
        "conventions": {
            "one_shots": "start at sample 0 (leading silence trimmed) -- trigger exactly at the impact",
            "loops": "sample-accurate: loop the whole file (loop_start_sample..loop_end_sample)",
            "levels": "SFX/UI/crowd one-shots and VO peak -1 dBFS, S_*Loop beds -3 dBFS, music -6 dBFS",
            "volume": "suggested playback volume 0..1 for a balanced default mix",
            "channels": "mono SFX + VO (spatialize in engine); stereo crowd beds/reactions + music (2D)",
        },
        "count": len(files),
        "files": files,
    }
    with open(mpath, "w") as fh:
        json.dump(manifest, fh, indent=2)
    print("\nwrote %s (%d files)%s" % (mpath, len(files), "" if not failures else "  -- %d with problems" % failures))
    if not args.no_previews:
        for p in render_previews(files, signals):
            print("preview:", p)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
