"""Перфоманс-тести Dynamic Island: мікробенчі + сценарій expand/collapse. Пише perf_report.json."""
import sys, time, json
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QPixmap, QPainter, QColor

from profiler import PROF
import island as M


def microbench():
    out = {}
    # маска S2
    t0 = time.perf_counter()
    for _ in range(200):
        M._mask_region(371, 208, 34)
    out["mask_S2_200x_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    # маска compact
    t0 = time.perf_counter()
    for _ in range(200):
        M._mask_region(348, 52, 26)
    out["mask_S1_200x_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    # rounded pixmap
    px = QPixmap(128, 128)
    px.fill(QColor("#1ED760"))
    t0 = time.perf_counter()
    for _ in range(100):
        M.rounded_pixmap(px, 14, 64)
    out["rounded_pixmap_100x_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    # elide
    from PyQt6.QtGui import QFont
    f = QFont("Segoe UI", 11)
    t0 = time.perf_counter()
    for _ in range(2000):
        M.elide_text(f, "Revolution in your Heart — Lyn ft. Some Very Long Artist Name", 263)
    out["elide_2000x_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    # spring-симуляція 550мс @180Гц
    import math
    t0 = time.perf_counter()
    for _ in range(100):
        p, v, k, c, dt = 0.0, 0.0, 170.0, 2 * 0.95 * math.sqrt(170.0), 1 / 180
        for _ in range(99):
            a = k * (1 - p) - c * v
            v += a * dt
            p += v * dt
    out["spring_sim_100x_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


def scenario():
    app = QApplication(sys.argv)
    w = M.DynamicIsland()
    w.set_track("Revolution in your Heart", "Lyn", None)
    w.set_playing(True)
    w.set_position(148_000, 256_000)

    steps = []
    for i in range(6):
        steps += [("expand", 700), ("collapse", 600)]
    steps += [("track", 400), ("seek", 400), ("done", 1500)]
    idx = {"i": 0}

    def run():
        i = idx["i"]
        if i >= len(steps):
            return
        act, wait = steps[i]
        idx["i"] += 1
        if act == "expand":
            w.expand()
        elif act == "collapse":
            w.collapse()
        elif act == "track":
            w.set_track("Blinding Lights — Extra Long Title For Elide Test", "The Weeknd", None)
        elif act == "seek":
            w.set_position(30_000, 256_000)
        elif act == "done":
            rep = {"scenario": "6x expand/collapse + track + seek", "profiler": PROF.summary()}
            with open("perf_report.json", "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False, indent=1)
            print("=== PERF REPORT ===")
            print(json.dumps(rep, ensure_ascii=False, indent=1))
            app.quit()
            return
        QTimer.singleShot(wait, run)

    QTimer.singleShot(800, run)
    app.exec()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "micro":
        app = QApplication(sys.argv)
        print(json.dumps(microbench(), ensure_ascii=False, indent=1))
    else:
        scenario()
