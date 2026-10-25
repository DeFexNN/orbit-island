"""ORBIT — a native-widget product film. No application files are modified.

python cinematic/render.py --preview
python cinematic/render.py --render
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "2")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QImage,
                        QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient)
from PyQt6.QtWidgets import QApplication

W, H, FPS, DURATION = 1920, 1080, 60, 32
IVORY = "#F4F1ED"
MUTED = "#9C9AAE"
LILAC = "#C3AEF5"


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smooth(x):
    x = clamp(x)
    return x * x * x * (x * (x * 6 - 15) + 10)


def ramp(t, start, duration=0.7):
    return smooth((t - start) / duration)


def mix(a, b, k):
    return a + (b - a) * k


def window(t, start, end, attack=.6, release=.4):
    return ramp(t, start, attack) * (1 - ramp(t, end - release, release))


def color(hex_color, alpha=1.):
    c = QColor(hex_color)
    c.setAlphaF(clamp(alpha))
    return c


class Film:
    def __init__(self, app):
        from native import NativeCapture
        self.app = app
        self.source = NativeCapture(app)
        self.fonts = {}
        self.stars = []
        rng = random.Random(273)
        for _ in range(84):
            self.stars.append((rng.uniform(0, W), rng.uniform(0, H),
                               rng.uniform(.5, 1.5), rng.uniform(.08, .3), rng.random() * 6.28))
        # Stationary sub-code-value texture prevents flat dark gradients banding.
        yy, xx = np.mgrid[0:H, 0:W]
        v = np.exp(-(((xx - 1130) / 1200) ** 2 + ((yy - 480) / 850) ** 2))
        noise = np.random.default_rng(73).uniform(-.8, .8, (H, W))
        self.bg = np.empty((H, W, 4), np.uint8)
        for j, (base, strength) in enumerate(((11, 7), (7, 4), (5, 4))):
            self.bg[:, :, j] = np.clip(base + v * strength + noise, 0, 255).astype(np.uint8)
        self.bg[:, :, 3] = 255
        self.background = QImage(self.bg.data, W, H, W * 4, QImage.Format.Format_RGB32).copy()
        self.last_pose = None

    def font(self, size, weight=QFont.Weight.Normal, tracking=0, family="Segoe UI"):
        key = (size, weight, tracking, family)
        if key not in self.fonts:
            f = QFont(family)
            f.setPixelSize(round(size))
            f.setWeight(weight)
            if tracking:
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
            self.fonts[key] = f
        return self.fonts[key]

    def text(self, p, text, x, y, size=30, ink=IVORY, alpha=1, weight=QFont.Weight.Normal,
             tracking=0, align="left", reveal=1):
        if alpha < .001:
            return
        f = self.font(size, weight, tracking)
        fm = QFontMetricsF(f)
        width = fm.horizontalAdvance(text)
        if align == "center":
            x -= width / 2
        elif align == "right":
            x -= width
        p.save()
        p.setOpacity(clamp(alpha))
        p.setFont(f)
        p.setPen(QColor(ink))
        if reveal < 1:
            p.setClipRect(QRectF(x - 8, y - size * 1.4, (width + 20) * reveal, size * 2))
        p.drawText(QPointF(x, y), text)
        p.restore()

    def glow(self, p, cx, cy, rx, ry, rgb, strength):
        if strength < .001:
            return
        p.save()
        p.translate(cx, cy)
        p.scale(rx, ry)
        g = QRadialGradient(QPointF(0, 0), 1)
        g.setColorAt(0, QColor(*rgb, round(255 * clamp(strength))))
        g.setColorAt(.28, QColor(*rgb, round(255 * clamp(strength * .55))))
        g.setColorAt(.65, QColor(*rgb, round(255 * clamp(strength * .14))))
        g.setColorAt(1, QColor(*rgb, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QRectF(-1, -1, 2, 2))
        p.restore()

    def title(self, p, text, x, baseline, size, t, cue, alpha=1, align="left", tracking=-4):
        """Optically spaced glyphs arrive as one travelling, damped gesture."""
        f = self.font(size, QFont.Weight.Light, tracking)
        fm = QFontMetricsF(f)
        if align == "center":
            x -= fm.horizontalAdvance(text) / 2
        for i, char in enumerate(text):
            k = ramp(t, cue + i*.018, .64)
            self.text(p, char, x, baseline + (1-k)*38, size, IVORY, alpha*k,
                      weight=QFont.Weight.Light, tracking=tracking)
            x += fm.horizontalAdvance(char)

    def orbit(self, p, t, cx, cy, radius, tilt, rot, alpha, index=0):
        """A continuous perspective orbit; light is integrated along its tangent."""
        n = 160
        pts, depths = [], []
        cr, sr = math.cos(rot), math.sin(rot)
        for i in range(n + 1):
            a = 2 * math.pi * i / n
            x, y, z = radius * math.cos(a), radius * math.sin(a) * math.sin(tilt), radius * math.sin(a) * math.cos(tilt)
            persp = 1800 / (1800 + z)
            pts.append(QPointF(cx + (x * cr - y * sr) * persp, cy + (x * sr + y * cr) * persp))
            depths.append(z / radius)
        for i in range(n):
            light = .5 + .5 * math.cos(i / n * math.tau - t * .55 - index * 1.8)
            near = (1 - depths[i]) / 2
            aa = alpha * (.08 + .62 * light ** 9 + .3 * near ** 3)
            q = QColor(round(mix(102, 247, light)), round(mix(86, 218, light)), round(mix(173, 236, light)))
            q.setAlphaF(clamp(aa))
            p.setPen(QPen(q, .7 + 1.2 * light ** 7))
            p.drawLine(pts[i], pts[i+1])
            if light > .94:
                q.setAlphaF(clamp(aa * .13))
                p.setPen(QPen(q, 7))
                p.drawLine(pts[i], pts[i+1])
        # A single travelling light gives the orbit an identifiable direction.
        a = (t * .125 + index * .31) % 1
        pt = pts[int(a * n)]
        self.glow(p, pt.x(), pt.y(), 25, 25, (226, 199, 255), alpha * .22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color("#FBE5FF", alpha * .8))
        p.drawEllipse(pt, 1.6, 1.6)

    def environment(self, p, t):
        p.drawImage(0, 0, self.background)
        controls = ramp(t, 8.4, .9) * (1 - ramp(t, 14.1, .8))
        floating = ramp(t, 18.2, .8) * (1 - ramp(t, 21.5, .8))
        finale = ramp(t, 25.9, .9)
        origin = 1 - ramp(t, 4.6, 1.0)
        cx = mix(1010, 1260, max(controls, floating, finale))
        cy = mix(515, 545, controls)
        self.glow(p, cx, cy + 60, 800, 560, (107, 62, 173), .12 + .06 * math.sin(t * .25))
        self.glow(p, 1400 + math.sin(t * .12) * 90, 250, 620, 440, (71, 76, 148), .09)
        self.glow(p, 620, 900, 650, 260, (131, 59, 100), .055)
        # The atmospheric marks belong to the film, never to the interface.
        for x, y, r, a, ph in self.stars:
            a *= .6 + .4 * math.sin(t * .19 + ph) ** 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(200, 195, 228, round(a * 255)))
            p.drawEllipse(QPointF((x + t * (1 + r) * .8) % W, (y + math.sin(t * .09 + ph) * 6) % H), r * .6, r * .6)
        ring_alpha = .65 * ramp(t, .45, 1.8)
        radius = mix(620, 530, max(controls, floating))
        radius = mix(radius, 510, finale)
        radius *= mix(1.2, 1., ramp(t, 0, 5.2))
        tilt = .30 + .09 * math.sin(t * .13)
        turn = (.4*ramp(t,3.2,2) - .4*ramp(t,5.2,1)
                + .22*ramp(t,21.8,2) - .22*ramp(t,26.4,1))
        rotation = -.38 + .065 * math.sin(t * .2) + turn
        for i, mul in enumerate((1., 1.045, 1.16)):
            self.orbit(p, t, cx, cy, radius * mul, tilt + i * .045,
                       rotation + i * .032, ring_alpha * (1 if i == 0 else .3), i)
        # A restrained sweeping light marks the two big reveals.
        for cue, strength in ((5.2, .30), (26.4, .43)):
            u = t - cue
            if 0 <= u < 1.8:
                self.glow(p, cx + (u - .3) * 240, cy, 1150, 80 + u * 85,
                          (182, 139, 227), strength * math.exp(-3 * u))
        # Grazing caustic: a curved, dispersing sheet of light at each reveal.
        # It shares the cover's violet/pink palette and never covers UI ink.
        for cue, strength in ((.8,.55),(5.2,1.),(14.4,.65),(26.4,1.)):
            u = t-cue
            if 0 <= u < 1.9:
                k = smooth(u/1.9)
                p.save()
                p.translate(cx,cy)
                p.rotate(-21+turn*25)
                r = mix(65,920,k)
                op = math.sin(math.pi*k)**1.5 * .18 * strength
                p.setBrush(Qt.BrushStyle.NoBrush)
                for offset in range(8):
                    p.setPen(QPen(QColor(193+offset*6,153+offset*8,232+offset*3,
                                        round(op*(1-offset/9)*255)),.6+offset*.25))
                    p.drawEllipse(QRectF(-r-offset*5,-r*.26-offset*2,
                                             2*r+offset*10,2*r*.26+offset*4))
                p.restore()
        # Thin editorial corner marks, persistent and deliberately low contrast.
        self.text(p, "DYNAMIC ISLAND", 94, 78, 15, MUTED, .6 * ramp(t, 1.4), tracking=3)
        self.text(p, "A WINDOWS MUSIC COMPANION", 1826, 78, 12, MUTED,
                  .55 * ramp(t, 1.8), tracking=2.1, align="right")

    def editorial(self, p, t):
        a = window(t, 1.25, 5.15, .9, .55)
        self.text(p, "A LITTLE SPACE.", 960, 270 + 18 * (1-a), 20, LILAC, a, tracking=5.5, align="center")
        self.text(p, "A different orbit.", 960, 755 + 22 * (1-a), 91, IVORY, a,
                  weight=QFont.Weight.Light, tracking=-2.5, align="center")
        self.text(p, "FOR YOUR MUSIC", 960, 813, 16, MUTED, a, tracking=4.2, align="center")

        a = window(t, 5.2, 8.45, .72, .38)
        self.title(p, "Dynamic Island", 960, 350, 138, t, 5.2, a, align="center", tracking=-5)
        self.text(p, "F O R   W I N D O W S", 960, 415 + 20 * (1-a), 20, LILAC, a, align="center")
        self.text(p, "Your music. A little closer.", 960, 830, 28, MUTED, a,
                  weight=QFont.Weight.Light, align="center")

        a = window(t, 8.55, 14.45, .65, .4)
        self.text(p, "01  /  CONTROL", 158, 236, 17, LILAC, a, tracking=3.2)
        for i, line in enumerate(("Your music.", "At your", "fingertips.")):
            k = ramp(t, 8.6 + i * .09, .65) * (1 - ramp(t, 14.05, .4))
            self.text(p, line, 152, 358 + i * 112 + (1-k) * 28, 103, IVORY, k,
                      weight=QFont.Weight.Light, tracking=-3)
        self.text(p, "Play. Seek. Set the level.", 160, 764, 28, MUTED, a, weight=QFont.Weight.Light)
        active = 0 if t < 11.2 else (1 if t < 12.4 else 2)
        for i, (s, x) in enumerate((("PLAY / PAUSE", 160), ("SEEK", 340), ("VOLUME", 440))):
            self.text(p, s, x, 817, 13, LILAC if i == active else MUTED,
                      a * (1 if i == active else .42), tracking=1.4)
        self.text(p, "NATIVE PLAYER CONTROLS", 1280, 887, 13, MUTED, a * .75, tracking=2.1, align="center")

        a = window(t, 14.55, 18.25, .8, .36)
        self.text(p, "02  /  LYRICS", 960, 239, 17, LILAC, a, tracking=3.2, align="center")
        self.text(p, "Let the words move you.", 960, 356 + (1-a)*30, 88, IVORY, a,
                  weight=QFont.Weight.Light, tracking=-2.6, align="center")
        self.text(p, "Synced lyrics. In the island.", 960, 745, 30, MUTED, a,
                  weight=QFont.Weight.Light, align="center")

        a = window(t, 18.3, 21.85, .6, .36)
        self.text(p, "03  /  FOLLOW", 160, 230, 17, LILAC, a, tracking=3.2)
        for i, line in enumerate(("Give every", "word room.")):
            self.text(p, line, 153, 352 + i*105 + (1-a)*28, 96, IVORY, a,
                      weight=QFont.Weight.Light, tracking=-3)
        self.text(p, "Floating lyrics companion.", 160, 747, 28, MUTED, a, weight=QFont.Weight.Light)

        a = window(t, 21.9, 26.4, .65, .42)
        self.text(p, "04  /  MAKE SPACE", 960, 235, 17, LILAC, a, tracking=3.2, align="center")
        self.text(p, "There when you need it.", 960, 365 + (1-a)*24, 86, IVORY, a,
                  weight=QFont.Weight.Light, tracking=-2.8, align="center")
        self.text(p, "DRAG UP TO TUCK AWAY", 940, 779, 15, LILAC if t < 23.8 else MUTED,
                  a * (1.0 if t < 23.8 else .5), tracking=2, align="right")
        self.text(p, "/", 972, 779, 15, MUTED, a*.4, align="center")
        self.text(p, "CLICK TO RETURN", 1004, 779, 15, LILAC if t >= 23.8 else MUTED,
                  a * (1.0 if t >= 23.8 else .5), tracking=2)

        a = ramp(t, 26.4, .85)
        self.text(p, "FOR WINDOWS", 162, 231, 18, LILAC, a, tracking=4.8)
        for i, line in enumerate(("Dynamic", "Island")):
            k = ramp(t, 26.4 + .09*i, .9)
            self.title(p, line, 147, 427 + i*170, 170, t, 26.4+i*.09, a, tracking=-6)
        self.text(p, "Your music. A little closer.", 160, 751, 33, MUTED, a, weight=QFont.Weight.Light)
        self.text(p, "SMALL BY DESIGN.", 162, 821, 13, LILAC, a*.85, tracking=3.3)

    def pose(self, t):
        # Continuous camera, independent of the app's real spring geometry.
        poses = [
            (0, 960, 490, 4.2, -2.5),
            (4.65, 960, 500, 3.25, 0),
            (6.05, 960, 620, 2.65, 0),
            (8.35, 960, 620, 2.65, 0),
            (9.15, 1280, 540, 1.72, 0),
            (13.95, 1280, 540, 1.72, 0),
            (15.2, 960, 555, 2.8, 0),
            (17.85, 960, 555, 2.8, 0),
            (18.95, 540, 590, 1.85, 0),
            (21.45, 540, 590, 1.85, 0),
            (22.5, 960, 565, 2.8, 0),
            (25.8, 960, 565, 2.8, 0),
            (27.3, 1320, 549, 1.92, -3.3),
            (32, 1330, 541, 2.0, -2.2),
        ]
        for i in range(len(poses)-1):
            a, b = poses[i], poses[i+1]
            if a[0] <= t <= b[0]:
                k = smooth((t-a[0])/(b[0]-a[0]))
                return tuple(mix(a[j], b[j], k) for j in range(1,5))
        return poses[-1][1:]

    def native(self, p, sample, t):
        cx, cy, scale, roll = self.pose(t)
        alpha = ramp(t, .8, 1.3)
        width, height = sample["width"], sample["height"]
        # Pool + soft shadow retain the real alpha edge of the unaltered widget.
        self.glow(p, cx, cy + height*scale*.45, width*scale*.75, 90 + height*scale*.18,
                  (104, 71, 163), alpha*.13)
        self.glow(p, cx, cy + height*scale*.38, width*scale*.6, 45 + height*scale*.13,
                  (0, 0, 0), alpha*.7)
        p.save()
        p.setOpacity(alpha)
        p.translate(cx, cy)
        p.rotate(roll)
        p.scale(scale, scale)
        p.drawImage(QRectF(-width/2, -height/2, width, height), sample["image"])
        p.restore()
        self.last_pose = (cx, cy, scale, roll)

        if 18.2 <= t < 21.8 and sample.get("floating") is not None:
            k = ramp(t, 18.2, .8)
            out = 1-ramp(t, 21.45, .35)
            image = sample["floating"]
            fw = image.width() / image.devicePixelRatio()
            fh = image.height() / image.devicePixelRatio()
            s = 1.43
            fx, fy = 1370, 550 + (1-k) * 95
            self.glow(p, fx, fy + fh*s*.35, 480, 280, (105, 68, 162), .15*k*out)
            p.save()
            p.setOpacity(k*out)
            p.translate(fx, fy)
            p.scale(s, s)
            p.drawImage(QRectF(-fw/2, -fh/2, fw, fh), image)
            p.restore()

        # Intentional interaction marks at actual widget control coordinates.
        for cue, key, duration in ((10.2, "play", .65), (11.2, "seek", .9), (12.4, "volume", 1.0)):
            u = t-cue
            if 0 <= u < duration and key in sample.get("controls", {}):
                px, py = sample["controls"][key]
                x = cx + (px-width/2)*scale
                y = cy + (py-height/2)*scale
                op = math.sin(math.pi * u/duration)**.7
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(color("#F6E9FF", op*.75), 1.4))
                p.drawEllipse(QPointF(x,y), 12+u*18, 12+u*18)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color("#FFFFFF", op))
                p.drawEllipse(QPointF(x,y), 3.2, 3.2)

    def footer(self, p, t):
        a = .6 * ramp(t, 5.3, .8)
        self.text(p, "OFFLINE UI DEMO  /  AUTHORED LRC TIMING", 94, 1003,
                  11, MUTED, a, tracking=1.55)
        self.text(p, "ORBIT  /  2026", 1826, 1003, 11, MUTED, a*.75, tracking=2, align="right")
        p.setPen(QPen(color("#B3A7CC", .12*ramp(t, 1.8)), 1))
        p.drawLine(QPointF(94, 954), QPointF(1826, 954))
        p.setPen(QPen(color("#C9B4ED", .40*ramp(t, 1.8)), 1))
        p.drawLine(QPointF(94,954), QPointF(94+1732*clamp(t/DURATION),954))

    def frame(self, frame, draw=True):
        sample = self.source.sample(frame)
        if not draw:
            return None
        t = frame / FPS
        image = QImage(W, H, QImage.Format.Format_RGB32)
        p = QPainter(image)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing |
                         QPainter.RenderHint.SmoothPixmapTransform)
        self.environment(p, t)
        self.editorial(p, t)
        self.native(p, sample, t)
        self.footer(p, t)
        fade = (1-ramp(t, 0, .7)) + ramp(t, 30.8, 1.2)
        if fade > 0:
            p.fillRect(0,0,W,H,color("#030308", clamp(fade)))
        p.end()
        return image

    def close(self):
        self.source.close()


def contact_sheet(paths, output):
    from PIL import Image, ImageDraw, ImageFont
    thumb_w, thumb_h = 640, 360
    cols, rows = 3, math.ceil(len(paths)/3)
    board = Image.new("RGB", (cols*thumb_w, rows*(thumb_h+40)), "#08090f")
    d = ImageDraw.Draw(board)
    font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 17)
    for i,path in enumerate(paths):
        x,y = (i%cols)*thumb_w, (i//cols)*(thumb_h+40)
        im = Image.open(path).convert("RGB").resize((thumb_w,thumb_h),Image.Resampling.LANCZOS)
        board.paste(im,(x,y))
        d.text((x+16,y+thumb_h+9),path.stem.replace("frame_","")+" s",font=font,fill="#b6abc9")
    board.save(output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT/"output"/"Dynamic_Island_ORBIT.mp4")
    args=parser.parse_args()
    app=QApplication([])
    for name in ("segoeui.ttf","segoeuil.ttf","seguisb.ttf","segoeuib.ttf"):
        path=Path(r"C:\Windows\Fonts")/name
        if path.exists(): QFontDatabase.addApplicationFont(str(path))
    film=Film(app)
    out=args.out.resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    proof=ROOT/"output"/"frames"
    proof.mkdir(parents=True,exist_ok=True)
    times=[2.8,5.9,7.5,9.6,11.5,13.3,15.7,17.2,19.8,22.9,24.8,28.5]
    proof_frames={round(t*FPS):t for t in times}
    ffmpeg=shutil.which("ffmpeg")
    proc=None
    log=None
    started=time.perf_counter()
    paths=[]
    if args.render:
        if not ffmpeg: raise RuntimeError("FFmpeg is required on PATH")
        audio=ROOT/"audio"/"soundtrack.wav"
        if not audio.exists(): raise RuntimeError("Run cinematic/audio/sound_design.py first")
        log=out.with_suffix(".ffmpeg.log").open("w",encoding="utf-8")
        command=[ffmpeg,"-y","-hide_banner","-loglevel","warning",
                 "-f","rawvideo","-pixel_format","bgra","-video_size",f"{W}x{H}","-framerate",str(FPS),
                 "-i","pipe:0","-i",str(audio),"-map","0:v:0","-map","1:a:0",
                 "-c:v","libx264","-preset","medium","-crf","17","-pix_fmt","yuv420p",
                 "-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709",
                 "-c:a","aac","-b:a","320k","-ar","48000","-t",str(DURATION),
                 "-movflags","+faststart","-metadata","title=ORBIT — Dynamic Island for Windows",
                 "-metadata","comment=Original procedural film and score. Actual native Qt widgets; offline demo.",str(out)]
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
    try:
        for f in range(DURATION*FPS):
            im=film.frame(f,draw=args.render or f in proof_frames)
            if im is not None:
                if f in proof_frames:
                    path=proof/f"frame_{proof_frames[f]:04.1f}.png"
                    im.save(str(path))
                    paths.append(path)
                if proc:
                    bits=im.constBits()
                    bits.setsize(im.sizeInBytes())
                    proc.stdin.write(bytes(bits))
            if f%180==0:
                print(f"{f}/{DURATION*FPS} frames | {time.perf_counter()-started:.1f}s",flush=True)
        if proc:
            proc.stdin.close()
            if proc.wait()!=0: raise RuntimeError(f"FFmpeg failed; see {out.with_suffix('.ffmpeg.log')}")
            log.close()
        contact_sheet(paths,ROOT/"output"/"storyboard.jpg")
        if proc:
            meta={"file":str(out),"width":W,"height":H,"fps":FPS,"frames":DURATION*FPS,"duration_seconds":DURATION,
                  "sha256":hashlib.sha256(out.read_bytes()).hexdigest(),"render_seconds":round(time.perf_counter()-started,2),
                  "visuals":"Procedural QPainter motion; actual unmodified DynamicIsland Qt widgets at 2x device pixel ratio",
                  "audio":"Original stereo synthesis; no third-party recordings","application_modified":False}
            (out.parent/"render_manifest.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
        print(out if proc else ROOT/"output"/"storyboard.jpg",flush=True)
    finally:
        film.close()
        if proc:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=15)
        if log and not log.closed:
            log.close()


if __name__=="__main__":
    main()
