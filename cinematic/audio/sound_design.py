"""Original, deterministic 32-second cinematic score for Dynamic Island.

Only Python's standard library and NumPy are required. No samples, prerecorded
music, voices, or third-party musical material are used. Transition revision:
soft tonal swells only; no noise risers, air beds, or noisy impact transients.
Run from any directory:
    python sound_design.py
"""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
import subprocess
import wave

import numpy as np

SR = 48_000
DURATION = 32.0
N = int(SR * DURATION)
OUT = Path(__file__).resolve().parent
RNG = np.random.default_rng(311024)
MIX = np.zeros((N, 2), dtype=np.float64)
# Preserve the prior score's gain: removing noise must not turn up its music.
REFERENCE_PREMASTER_PEAK = 0.37229110076801486
REFERENCE_FINAL_DENOMINATOR = 0.8527497867376799


def midi(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def env(t, duration, attack=0.05, release=0.5):
    return smoothstep(t / attack) * smoothstep((duration - t) / release)


def pan(x, position=0.0):
    p = np.asarray(position)
    angle = (p + 1.0) * np.pi / 4.0
    return np.column_stack((x * np.cos(angle), x * np.sin(angle)))


def add(start, sound, gain=1.0):
    offset = int(round(start * SR))
    a, b = max(0, offset), min(N, offset + len(sound))
    if b > a:
        MIX[a:b] += sound[a - offset:b - offset] * gain


def time_for(duration):
    return np.arange(int(round(duration * SR)), dtype=np.float64) / SR


def echo(stereo, delay=0.18, decay=0.35, repeats=4, cross=True):
    samples = int(delay * SR)
    out = np.zeros((len(stereo) + samples * repeats, 2), dtype=np.float64)
    out[:len(stereo)] = stereo
    for i in range(1, repeats + 1):
        source = stereo[:, ::-1] if cross and i % 2 else stereo
        out[samples * i:samples * i + len(stereo)] += source * decay ** i
    return out


def room(stereo, amount=0.22):
    """Sparse diffuse original delays; no impulse response or external reverb."""
    tail = int(1.37 * SR)
    wet = np.zeros((len(stereo) + tail, 2), dtype=np.float64)
    wet[:len(stereo)] += stereo
    for delay, level in [(0.071, .22), (.113, .19), (.179, .16),
                         (.263, .125), (.397, .092), (.617, .06),
                         (.887, .039), (1.271, .018)]:
        d = int(delay * SR)
        wet[d:d+len(stereo)] += stereo[:, ::-1] * level * amount
    return wet


def pad(start, duration, notes, gain, movement=0.0, attack=1.0, release=1.3):
    t = time_for(duration)
    left, right = np.zeros_like(t), np.zeros_like(t)
    for index, note in enumerate(notes):
        f = midi(note)
        phase = RNG.uniform(0, 2 * np.pi)
        amp = 1.0 / (1.0 + index * .13)
        for harmonic, weight in [(1, 1.0), (2, .18), (3, .065), (4, .018)]:
            lfo = .22 * np.sin(2*np.pi * (.039 + index*.009)*t + phase)
            left += amp * weight * np.sin(2*np.pi*f*harmonic*(1-.0012)*t + phase + lfo)
            right += amp * weight * np.sin(2*np.pi*f*harmonic*(1+.0012)*t + phase - lfo)
    stereo = np.column_stack((left, right)) / math.sqrt(len(notes))
    breathe = .87 + .13*np.sin(2*np.pi*.11*t + movement)
    stereo *= (env(t, duration, attack, release) * breathe * gain)[:, None]
    add(start, room(stereo, .28))


def sub(start, duration, note, gain=.14, attack=.04, release=.4):
    t = time_for(duration)
    f = midi(note)
    signal = np.sin(2*np.pi*f*t) + .10*np.sin(2*np.pi*f*2*t)
    signal *= env(t, duration, attack, release) * gain
    add(start, pan(signal))


def glass(start, note, duration=1.8, gain=.04, position=0.0, bright=1.0):
    t = time_for(duration)
    f = midi(note)
    x = np.sin(2*np.pi*f*t) * np.exp(-t/0.66)
    x += .23*bright*np.sin(2*np.pi*f*2.002*t) * np.exp(-t/.31)
    x += .07*bright*np.sin(2*np.pi*f*3.98*t) * np.exp(-t/.13)
    x *= env(t, duration, .006, .4) * gain
    add(start, echo(pan(x, position), .3, .29, 5))


def tonal_glide(target, lead=.8, tail=.65, gain=.08, direction=1, note=57):
    """Quiet warm harmonic swell; its envelope lands on the exact picture cue.

    The fundamental moves just two semitones in the low midrange, like a gently
    bowed glass note. Continuous phase, weak partials, and a narrow pan avoid
    hiss, whistles, siren sweeps, or conspicuous synthetic effects.
    """
    duration = lead + tail
    t = time_for(duration)
    progress = smoothstep(t / max(lead, .001))
    semitones = -direction * 2.0 * (1.0-progress)
    semitones -= direction * .18 * smoothstep((t-lead)/max(tail, .001))
    frequency = midi(note) * 2**(semitones/12.0)
    phase = 2*np.pi*np.cumsum(frequency)/SR
    tone = np.sin(phase) + .16*np.sin(2*phase + .08)
    tone += .035*np.sin(3*phase + .16) + .12*np.sin(.5*phase)
    contour = np.where(t < lead, smoothstep(t/max(lead, .001))**1.45,
                       np.exp(-(t-lead)/max(tail*.28, .01)))
    contour *= env(t, duration, min(.06, lead*.3), min(.18, tail*.4))
    travel = (.42*progress-.21)*direction
    stereo = pan(tone * contour * gain * .62, travel)
    add(target-lead, room(stereo, .10))


def impact(at, strength=.2, note=26, accent=.025):
    duration = 2.4
    t = time_for(duration)
    f = midi(note)
    phase = 2*np.pi*(f*t + (34/17)*(1-np.exp(-17*t)))
    x = np.sin(phase)*np.exp(-t/0.65)
    x += .16*np.sin(2*np.pi*f*2*t)*np.exp(-t/.28)
    x *= env(t, duration, .009, .45) * strength
    add(at, pan(x))
    tn = time_for(.38)
    # Keep the original low impact body, replace its noise edge with a soft
    # resonant tap below 400 Hz. It contains only clean harmonic oscillators.
    transient = (np.sin(2*np.pi*f*4*tn) + .20*np.sin(2*np.pi*f*7*tn))
    transient *= env(tn, .38, .006, .20) * np.exp(-tn/.08) * accent * .72
    add(at, room(pan(transient), .35))


def tick(at, pitch=1400, gain=.027, position=0.0):
    t = time_for(.16)
    x = (np.sin(2*np.pi*pitch*t) + .24*np.sin(2*np.pi*pitch*1.5*t))
    x *= np.exp(-t/.017)*env(t, .16, .0018, .05)*gain
    add(at, echo(pan(x, position), .085, .18, 2))


def pulse(at, note, gain=.05, position=0.0):
    t = time_for(.54)
    f = midi(note)
    x = np.sin(2*np.pi*f*t + .32*np.sin(2*np.pi*f*2*t)*np.exp(-t/.12))
    x += .14*np.sin(2*np.pi*2*f*t)
    x *= np.exp(-t/.19) * env(t, .54, .013, .13) * gain
    add(at, echo(pan(x, position), .15, .24, 3))


def shimmer(at, duration=2.0, gain=.014):
    notes = [74, 81, 86, 88, 93]
    for i, note in enumerate(notes):
        glass(at + .055*i, note, duration, gain/(1+i*.16),
              -.7+i*.35, .6)


def write_pcm24(path, stereo):
    values = np.rint(np.clip(stereo, -1.0, 1.0-2**-23) * (2**23)).astype(np.int32)
    interleaved = values.reshape(-1)
    packed = np.empty((len(interleaved), 3), dtype=np.uint8)
    packed[:, 0] = interleaved & 255
    packed[:, 1] = (interleaved >> 8) & 255
    packed[:, 2] = (interleaved >> 16) & 255
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(2)
        stream.setsampwidth(3)
        stream.setframerate(SR)
        stream.writeframes(packed.tobytes())


def main():
    # Wide, restrained suspended harmony. Musical time is 100 BPM (0.6 s beat).
    # D minor/add9 -> Bb major7/D -> Dm9 -> Fmaj9/C -> Gm9 -> Dm/add9.
    pad(0.0, 5.15, [50, 57, 64, 69], .023, attack=2.0, release=1.2)
    pad(3.2, 6.05, [46, 53, 57, 62, 65], .032, .4, 1.25, 1.5)
    pad(7.7, 7.4, [50, 57, 60, 64, 69], .030, .8, .9, 1.4)
    pad(13.8, 8.5, [48, 53, 57, 60, 67], .037, 1.2, 1.3, 1.6)
    pad(20.9, 6.3, [43, 50, 57, 58, 65], .030, .3, 1.0, .9)
    pad(26.4, 5.4, [50, 57, 62, 64, 69], .041, .8, .12, 2.1)

    # Clean center bass, short phrases leave room around every visual cue.
    sub(1.0, 3.3, 26, .035, 1.0, 1.0)
    sub(5.2, 2.5, 34, .061, .18, .8)
    sub(8.4, 2.1, 26, .074, .09, .7)
    sub(10.8, 1.35, 29, .064, .07, .55)
    sub(12.6, 1.6, 33, .063, .07, .6)
    sub(14.4, 3.1, 29, .055, .25, 1.1)
    sub(18.0, 3.2, 24, .054, .25, 1.1)
    sub(21.8, 1.7, 31, .068, .09, .5)
    sub(23.8, 2.2, 33, .065, .08, .5)
    sub(26.4, 4.6, 26, .089, .025, 1.65)

    # Sparse original glass motif, developed rather than looped verbatim.
    for at, note, gain, pos in [(.8, 81, .021, -.18),
        (3.2, 76, .024, .3), (4.4, 77, .024, -.35),
        (5.2, 74, .051, .0), (5.8, 81, .025, .4),
        (6.7, 76, .023, -.4), (7.6, 77, .021, .22),
        (8.4, 74, .036, -.12), (10.8, 76, .026, .35),
        (12.6, 81, .027, -.3),
        (14.4, 77, .038, -.27), (15.3, 81, .025, .3),
        (16.2, 79, .039, .1), (17.4, 76, .021, -.4),
        (18.2, 84, .031, .33), (19.4, 81, .024, -.25),
        (20.6, 79, .022, .35), (21.8, 74, .031, .0),
        (23.8, 76, .035, -.22), (25.0, 81, .032, .25),
        (26.4, 74, .052, -.14), (27.0, 81, .033, .35),
        (28.2, 86, .026, -.3), (29.4, 88, .017, .3)]:
        glass(at, note, 2.1, gain, pos, .75)

    # Controlled acceleration under the interaction chapter; soft transient edges.
    for i, at in enumerate(np.arange(8.4, 14.1, .6)):
        pulse(float(at), [50, 57, 62, 57, 53, 60, 65, 60, 57, 64][i],
              .023 if i % 2 else .034, -.28 if i % 2 else .28)
    for i, at in enumerate(np.arange(21.8, 26.3, .3)):
        pulse(float(at), [55, 62, 67, 69, 57, 64, 69, 72][i % 8],
              .022 + .009*(i % 4 == 0), .36*np.sin(i*1.2))

    # Picture-synchronous detailed sound design.
    tick(.8, 2100, .018, -.1)
    tonal_glide(3.2, 1.1, .7, .021, 1, 57)
    tonal_glide(5.2, 1.25, .9, .048, 1, 57)
    impact(5.2, .16, 26, .017)
    shimmer(5.2, 2.4, .012)
    tonal_glide(8.4, .48, .48, .037, -1, 62)
    impact(8.4, .12, 26, .017)
    tick(10.2, 1320, .025, -.13)
    tick(10.28, 1760, .013, .13)
    tonal_glide(11.2, .15, .28, .018, 1, 64)
    tick(11.2, 1580, .017, .3)
    # Volume gesture ascends gently, avoiding a clinical beep.
    for j in range(4):
        tick(12.22+j*.06, 1160+j*120, .009+j*.0015, -.24+j*.16)
    tonal_glide(12.4, .2, .25, .013, 1, 64)
    tonal_glide(14.4, .7, .95, .040, -1, 65)
    shimmer(14.4, 2.8, .011)
    tick(16.2, 1480, .013, .18)
    shimmer(18.2, 2.7, .018)
    tonal_glide(18.2, .55, .65, .019, 1, 60)
    tonal_glide(21.8, .42, .52, .039, -1, 55)
    impact(21.8, .102, 31, .016)
    tonal_glide(23.8, .55, .5, .036, 1, 57)
    impact(23.8, .09, 33, .013)
    # The final warm harmonic swell resolves into the original low impact.
    tonal_glide(26.4, 1.0, 1.3, .064, 1, 50)
    impact(26.4, .26, 26, .027)
    shimmer(26.4, 3.7, .021)
    tonal_glide(30.5, .3, 1.25, .016, -1, 57)

    # No noise bed: preserve a clean musical floor and fade out by 31.8 s.
    t = time_for(DURATION)

    # Remove numerical/sub-Hz offset and master with an exceptionally soft knee.
    MIX[:] -= np.mean(MIX, axis=0)
    MIX[:] = np.tanh(MIX * 1.16) / 1.16
    MIX[:] *= smoothstep(t/.025)[:, None]
    MIX[:] *= smoothstep((31.8-t)/1.15)[:, None]
    MIX[t >= 31.8] = 0
    MIX[:] *= 10**(-2.3/20) / REFERENCE_PREMASTER_PEAK
    # Gentle memoryless analog-style mastering rounds only the loudest summits.
    # This raises the beds naturally without pumping, and keeps the low impact warm.
    MIX[:] = np.tanh(MIX * 1.65)
    MIX[:] *= 10**(-1.9/20) / REFERENCE_FINAL_DENOMINATOR
    # TPDF dither at one 24-bit LSB; keep deliberate closing silence exact.
    dither = (RNG.random(MIX.shape)-RNG.random(MIX.shape)) / 2**24
    MIX[t < 31.8] += dither[t < 31.8]
    output = OUT/'soundtrack.wav'
    write_pcm24(output, MIX)

    cues = [
        (0.8,'Tiny ignition: close glass spark and delicate UI tick'),
        (3.2,'Warm bowed-glass anticipation swell, suspended harmony'),
        (5.2,'Hero reveal: warm D impact, harmonic swell, glass bloom'),
        (8.4,'Expansion: soft impact and rhythmic control chapter'),
        (10.2,'Pause/play: restrained paired UI ticks'),
        (11.2,'Seek: short soft tonal gesture and tiny tick'),
        (12.4,'Volume: gentle ascending tonal UI gesture'),
        (14.4,'Lyric morph: soft F harmonic glide, opening Fmaj9 harmony'),
        (16.2,'Lyric accent: warm glass note and delicate transient'),
        (18.2,'Floating lyric reveal: glass shimmer and warm harmonic swell'),
        (21.8,'Collapse: descending warm tone, short bass impact, kinetic pulse'),
        (23.8,'Restore: soft rising harmonic gesture and lifted glass motif'),
        (26.4,'Finale: largest controlled low impact, D minor/add9 resolution'),
        (30.5,'Closing soft glass release, fading fully to silence by 31.8'),
    ]
    metrics = {
        'duration_seconds': DURATION,
        'sample_rate_hz': SR,
        'channels': 2,
        'pcm_bits': 24,
        'sample_frames': N,
        'peak_dbfs': round(20*math.log10(float(np.max(np.abs(MIX)))), 3),
        'rms_dbfs': round(20*math.log10(float(np.sqrt(np.mean(MIX*MIX)))), 3),
        'left_right_correlation': round(float(np.corrcoef(MIX.T)[0,1]), 5),
        'mean_dc_per_channel': [float(x) for x in np.mean(MIX, axis=0)],
        'closing_silence_seconds': .2,
        'clipped_samples': int(np.count_nonzero(np.abs(MIX)>=1)),
        'all_samples_finite': bool(np.all(np.isfinite(MIX))),
        'peak_time_seconds': round(int(np.argmax(np.max(np.abs(MIX), axis=1)))/SR,6),
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'tempo_bpm': 100,
        'seed': 311024,
        'cues': [{'time_seconds': at, 'frame_at_60fps': round(at*60), 'description': description} for at,description in cues],
        'revision': 'Tonal transitions: all broadband-noise swells, background air, and noisy impact edges removed; original music, UI cues, low impacts, and timing preserved.',
        'master_gain': 'Fixed to previous score reference; removing noise does not raise the music level.',
        'provenance': '100% original procedural synthesis. No external samples, music, recordings, or impulse responses.',
        'license': 'CC0-1.0: the generated score and sound-design source are dedicated to the public domain to the extent permitted by law; free commercial and noncommercial use without attribution.',
    }
    # Read-only EBU R128/true-peak analysis. ffmpeg is optional for regeneration.
    try:
        result = subprocess.run(['ffmpeg','-hide_banner','-i',str(output),
            '-af','loudnorm=I=-17:TP=-2.3:LRA=11:print_format=json',
            '-f','null','-'],capture_output=True,text=True,check=True)
        last = result.stderr.rfind('{')
        measured, _ = json.JSONDecoder().raw_decode(result.stderr[last:])
        metrics['ffmpeg_loudness_analysis'] = {
            'integrated_lufs': float(measured['input_i']),
            'true_peak_dbtp': float(measured['input_tp']),
            'loudness_range_lu': float(measured['input_lra']),
            'threshold_lufs': float(measured['input_thresh']),
        }
        # Test a practical final-delivery codec as well as the PCM master.
        preview = OUT/'soundtrack_preview.m4a'
        subprocess.run(['ffmpeg','-hide_banner','-y','-i',str(output),
            '-c:a','aac','-b:a','256k',str(preview)],
            capture_output=True,text=True,check=True)
        encoded = subprocess.run(['ffmpeg','-hide_banner','-i',str(preview),
            '-af','loudnorm=I=-17:TP=-1.5:LRA=11:print_format=json',
            '-f','null','-'],capture_output=True,text=True,check=True)
        encoded_data, _ = json.JSONDecoder().raw_decode(
            encoded.stderr[encoded.stderr.rfind('{'):])
        metrics['aac_256k_roundtrip'] = {
            'integrated_lufs': float(encoded_data['input_i']),
            'true_peak_dbtp': float(encoded_data['input_tp']),
            'passes_minus_1_5_dbtp': float(encoded_data['input_tp']) <= -1.5,
        }
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError):
        metrics['ffmpeg_loudness_analysis'] = 'unavailable'
    (OUT/'soundtrack_metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in metrics.items() if k not in ['cues','license']}, indent=2))


if __name__ == '__main__':
    main()
