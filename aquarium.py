#!/usr/bin/env python3
"""
Max's Aquarium — a fullscreen virtual fish tank.

A gallery-style 2D aquarium on pure black. Fish are procedurally generated
(species shape, size, colors, pattern, personality) and interact: they make
friends, squabble, school, play with rocks, beg for food, and — if truly
neglected — starve. Clams sit on the sand and slowly breathe. Big toddler
buttons along the bottom add/remove fish, rocks, and clams, raise/lower the
sand, and sprinkle food.

Run:      python3 aquarium.py            (fullscreen)
          python3 aquarium.py --windowed (1280x800 test window)
Keys:     ESC/Q quit (tank auto-saves) · SPACE feed · D debug overlay
Mouse:    tap the water and curious fish come look; tap a fish to see its
          name (it startles); tap a clam and it snaps shut; tap a rock to
          flick a pebble.

State persists in aquarium_save.json — same fish, same personalities, same
friendships next launch. Fish get hungry while you're away (capped), but
nothing dies off-screen.
"""

import argparse
import colorsys
import json
import math
import os
import random
import sys
import time
from pathlib import Path

import pygame

V2 = pygame.math.Vector2
TAU = math.tau

# ----------------------------------------------------------------------------
# Tunables
# ----------------------------------------------------------------------------

FPS               = 60
MAX_FISH          = 30
MAX_ROCKS         = 14
MAX_CLAMS         = 8
SAND_STEPS        = 8          # button presses from bare glass to full sand
MAX_SAND_FRAC     = 0.26       # of water height
MAX_PELLETS       = 90
MAX_ALGAE         = 12
MEAN_EVERY        = 10         # every Nth fish added is a mean one

HUNGER_FULL_S     = 360.0      # seconds from fed to fully hungry
STARVE_GRACE_S    = 240.0      # seconds at full hunger before health drains
STARVE_DPS        = 0.35       # health per second once starving
HEAL_PS           = 0.9        # health per second when fed and safe
EAT_RELIEF        = 0.16       # hunger relieved per pellet
OFFLINE_HUNGER_CAP = 0.95      # fish never die off-screen, just get hungry

FRIEND_AFF        = 0.45       # affinity above this = friends
RIVAL_AFF         = -0.30      # below this = rivals
MAX_FIGHTS        = 4          # simultaneous chases/duels

DEAD_LINGER_S     = 24.0       # dead fish floats this long before fading
SAVE_EVERY_S      = 25.0

N_PHASES          = 14         # pre-rendered tail-sway frames per fish
SS                = 2          # supersample factor for pre-rendered art

SAND_COLOR        = (194, 178, 128)
WATER_TOP         = (26, 84, 110)
WATER_BOTTOM      = (6, 22, 34)

NAMES = [
    "Bubbles", "Sunny", "Pickle", "Ziggy", "Coral", "Finn", "Splash",
    "Goldie", "Pearl", "Nibbles", "Dot", "Peach", "Mango", "Blueberry",
    "Sparky", "Wiggles", "Taco", "Banana", "Cherry", "Pebble", "Squirt",
    "Jelly", "Noodle", "Butters", "Zoomy", "Flash", "Dash", "Momo", "Kiwi",
    "Coco", "Lulu", "Bobo", "Gigi", "Rocket", "Tulip", "Daisy", "Ollie",
    "Ruby", "Waffles", "Chomp", "Bingo", "Sushi", "Marble", "Twinkle",
    "Puddles", "Snickers", "Ducky", "Boop",
]

# archetype: body proportions, fins, and personality priors
ARCHETYPES = {
    #            len range   h/l ratio    tail       tail_len   spread  dorsal      anal        eye
    "tetra":    dict(ln=(32, 74),  ratio=(0.36, 0.46), tail="fork",     tl=(0.30, 0.40), sp=(0.42, 0.55), do=(0.28, 0.40), an=(0.20, 0.30), eye=(0.11, 0.15)),
    "goldfish": dict(ln=(60, 132), ratio=(0.50, 0.62), tail="fan",      tl=(0.38, 0.55), sp=(0.50, 0.65), do=(0.35, 0.50), an=(0.22, 0.32), eye=(0.10, 0.13)),
    "tang":     dict(ln=(68, 142), ratio=(0.60, 0.74), tail="crescent", tl=(0.28, 0.38), sp=(0.55, 0.70), do=(0.30, 0.45), an=(0.28, 0.40), eye=(0.09, 0.12)),
    "angel":    dict(ln=(60, 122), ratio=(0.80, 0.98), tail="fan",      tl=(0.30, 0.42), sp=(0.40, 0.52), do=(0.85, 1.15), an=(0.75, 1.05), eye=(0.08, 0.11)),
    "betta":    dict(ln=(56, 114), ratio=(0.38, 0.50), tail="flowy",    tl=(0.60, 0.90), sp=(0.55, 0.75), do=(0.45, 0.70), an=(0.40, 0.60), eye=(0.10, 0.13)),
    "puffer":   dict(ln=(48, 106),  ratio=(0.82, 0.98), tail="round",    tl=(0.22, 0.30), sp=(0.35, 0.45), do=(0.18, 0.28), an=(0.14, 0.22), eye=(0.16, 0.21)),
    "catfish":  dict(ln=(78, 166), ratio=(0.34, 0.44), tail="fork",     tl=(0.26, 0.34), sp=(0.40, 0.50), do=(0.25, 0.38), an=(0.16, 0.24), eye=(0.09, 0.12)),
    "pleco":    dict(ln=(100, 170), ratio=(0.30, 0.38), tail="fork",    tl=(0.24, 0.32), sp=(0.42, 0.52), do=(0.55, 0.85), an=(0.14, 0.20), eye=(0.09, 0.11)),
}
ARCH_WEIGHTS = {"tetra": 22, "goldfish": 16, "tang": 14, "angel": 12,
                "betta": 10, "puffer": 12, "catfish": 14, "pleco": 8}

# personality priors per archetype: 0..1. Deliberately far apart so each
# species has a strong, recognizable temperament (per-fish jitter is small):
# bettas duel, tetras school, tangs zoom and play, angels are stately bullies,
# puffers are curious clowns (and puff up when startled), goldfish are
# bottomless stomachs, catfish are lazy bottom vacuums.
TRAIT_PRIORS = {
    #            agg   soc   cur   play  greed timid energy
    "tetra":    (0.05, 0.95, 0.50, 0.50, 0.45, 0.80, 0.85),
    "goldfish": (0.10, 0.50, 0.60, 0.40, 1.00, 0.40, 0.45),
    "tang":     (0.50, 0.40, 0.65, 0.70, 0.50, 0.25, 0.90),
    "angel":    (0.65, 0.30, 0.50, 0.25, 0.50, 0.25, 0.45),
    "betta":    (0.97, 0.10, 0.55, 0.30, 0.50, 0.10, 0.55),
    "puffer":   (0.25, 0.30, 0.95, 0.90, 0.70, 0.40, 0.45),
    "catfish":  (0.03, 0.30, 0.40, 0.20, 0.85, 0.65, 0.20),
    "pleco":    (0.02, 0.20, 0.30, 0.10, 0.90, 0.50, 0.15),
}
TRAIT_KEYS = ("agg", "soc", "cur", "play", "greed", "timid", "energy")

# preferred vertical band (fraction of swimmable height)
ZONES = {
    "tetra": (0.10, 0.55), "goldfish": (0.25, 0.80), "tang": (0.15, 0.75),
    "angel": (0.12, 0.70), "betta": (0.08, 0.50), "puffer": (0.30, 0.85),
    "catfish": (0.78, 1.00), "pleco": (0.85, 1.00),
}

CALM_STATES = {"wander", "rest", "investigate", "school", "beg", "play", "to_glass"}


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, clamp(s, 0, 1), clamp(v, 0, 1))
    return [int(r * 255), int(g * 255), int(b * 255)]


def dim(col, f):
    return tuple(min(255, int(c * f)) for c in col[:3])


_FONTS = {}


def font(size):
    f = _FONTS.get(size)
    if f is None:
        f = _FONTS[size] = pygame.font.Font(None, size)
    return f


def blit_rotated(dest, surf, pos, pivot, angle):
    """Blit surf rotated by angle (deg, CCW) so that surf-point `pivot` lands on screen-point `pos`."""
    image_rect = surf.get_rect(topleft=(pos[0] - pivot[0], pos[1] - pivot[1]))
    offset = V2(pos) - V2(image_rect.center)
    rotated_offset = offset.rotate(-angle)
    rotated = pygame.transform.rotate(surf, angle)
    rect = rotated.get_rect(center=(pos[0] - rotated_offset.x, pos[1] - rotated_offset.y))
    dest.blit(rotated, rect)


# ----------------------------------------------------------------------------
# Fish genome + procedural sprite
# ----------------------------------------------------------------------------

def make_genome(rng, arch=None):
    if arch is None:
        names = list(ARCH_WEIGHTS)
        arch = rng.choices(names, weights=[ARCH_WEIGHTS[n] for n in names])[0]
    a = ARCHETYPES[arch]
    g = {
        "arch": arch,
        "len": rng.uniform(*a["ln"]),
        "ratio": rng.uniform(*a["ratio"]),
        "tail": a["tail"],
        "tail_len": rng.uniform(*a["tl"]),
        "tail_spread": rng.uniform(*a["sp"]),
        "dorsal": rng.uniform(*a["do"]),
        "anal": rng.uniform(*a["an"]),
        "eye": rng.uniform(*a["eye"]),
        "whiskers": arch == "catfish",
        "pseed": rng.randrange(1 << 30),
    }
    # ---- colors ----
    if arch in ("catfish", "pleco"):  # earth tones
        hue = rng.uniform(0.06, 0.13)
        sat = rng.uniform(0.35, 0.65)
        val = rng.uniform(0.45, 0.70)
    else:
        hue = rng.random()
        sat = rng.uniform(0.65, 0.95)
        val = rng.uniform(0.78, 1.0)
    patterns = {
        "tetra":    [("hstripe", 5), ("none", 3), ("spots", 2)],
        "goldfish": [("none", 3), ("patches", 4), ("twotone", 3)],
        "tang":     [("none", 3), ("twotone", 4), ("bars", 3)],
        "angel":    [("bars", 6), ("none", 2), ("twotone", 2)],
        "betta":    [("none", 4), ("twotone", 4), ("spots", 2)],
        "puffer":   [("spots", 7), ("none", 3)],
        "catfish":  [("spots", 5), ("none", 4), ("bars", 1)],
        "pleco":    [("spots", 9), ("bars", 1)],
    }[arch]
    names = [p for p, _ in patterns]
    pat = rng.choices(names, weights=[w for _, w in patterns])[0]
    if pat == "patches":  # koi: whitish body, bold patches
        base = hsv(rng.uniform(0.05, 0.12), 0.06, 0.98)
        pat_col = hsv(rng.choice([0.03, 0.06, 0.08]), 0.92, 0.95) if rng.random() < 0.75 else [30, 28, 32]
    else:
        base = hsv(hue, sat, val)
        if rng.random() < 0.5:
            pat_col = hsv(hue, sat * 0.7, val * 0.22)          # dark markings
        else:
            pat_col = hsv(hue + 0.5 + rng.uniform(-0.08, 0.08), 0.85, 0.9)  # complementary
    g["pattern"] = pat
    g["base"] = base
    g["belly"] = hsv(hue + rng.uniform(-0.05, 0.05), sat * 0.25, min(1.0, val * 1.25))
    g["fin"] = hsv(hue + rng.uniform(-0.14, 0.14), sat * 0.8, min(1.0, val * 1.1))
    g["pat_col"] = pat_col
    # ---- personality ----
    priors = TRAIT_PRIORS[arch]
    g["traits"] = {k: round(clamp(p + rng.uniform(-0.10, 0.10), 0.02, 1.0), 3)
                   for k, p in zip(TRAIT_KEYS, priors)}
    g["zone"] = list(ZONES[arch])
    return g


def render_fish_frame(g, phase, scale):
    """One tail-sway frame, right-facing, supersampled then smoothed."""
    L = g["len"] * scale
    bh = L * g["ratio"]
    tail = L * g["tail_len"]
    W = int(L * 1.10 + tail + 8)
    H = int(bh * (1.30 + g["dorsal"] + g["anal"]) + L * 0.20)
    s = pygame.Surface((W * SS, H * SS), pygame.SRCALPHA)
    rng = random.Random(g["pseed"])

    cy = H / 2
    x1 = W - 4.0          # nose
    x0 = x1 - L           # caudal peduncle
    cx = (x0 + x1) / 2
    sway = math.sin(phase)
    flut = math.sin(phase * 2.3 + 1.2)

    def P(x, y):
        return (x * SS, y * SS)

    def poly(col, pts):
        pygame.draw.polygon(s, col, [P(*p) for p in pts])

    def ell(surf, col, x, y, w, h):
        pygame.draw.ellipse(surf, col, pygame.Rect(int((x - w / 2) * SS), int((y - h / 2) * SS),
                                                   max(1, int(w * SS)), max(1, int(h * SS))))

    base = tuple(g["base"])
    fin = tuple(g["fin"]) + (165,)
    fin_dark = dim(g["fin"], 0.65) + (150,)
    outline = dim(base, 0.45)

    # ---- caudal (tail) fin: drawn first, behind body ----
    dy = sway * bh * 0.42
    spread = bh * g["tail_spread"]
    att_top = (x0 + bh * 0.10, cy - bh * 0.17)
    att_bot = (x0 + bh * 0.10, cy + bh * 0.17)
    tt = g["tail"]
    if tt == "fork":
        poly(fin, [att_top, (x0 - tail, cy - spread + dy),
                   (x0 - tail * 0.42, cy + dy * 0.75),
                   (x0 - tail, cy + spread + dy), att_bot])
    elif tt == "crescent":
        poly(fin, [att_top, (x0 - tail, cy - spread * 1.2 + dy),
                   (x0 - tail * 0.24, cy + dy * 0.7),
                   (x0 - tail, cy + spread * 1.2 + dy), att_bot])
    else:  # fan / round / flowy share the fan builder
        def fan_tail(amax, rmul, col, wavy):
            origin = (x0 + bh * 0.06, cy)
            pts = [origin]
            n = 16
            for i in range(n + 1):
                a = -amax + 2 * amax * i / n
                r = tail * rmul * (1 + (0.045 * math.sin(i * 1.3 + phase * 2) if wavy else 0))
                pts.append((x0 - r * math.cos(a),
                            cy + math.sin(a) * r * 0.95 + dy * (0.35 + 0.65 * abs(i / n - 0.5) * 2)))
            poly(col, pts)
        if tt == "flowy":
            fan_tail(1.00, 1.18, fin_dark, True)
            fan_tail(0.80, 0.92, fin, True)
        elif tt == "round":
            fan_tail(0.62, 0.85, fin, False)
        else:  # fan
            fan_tail(0.85, 1.00, fin, False)

    # ---- dorsal + anal fins (roots hidden under body) ----
    dh = bh * g["dorsal"]
    fx = cx - L * 0.30
    ty = cy - bh * 0.30
    poly(fin, [(fx, ty), (fx + L * 0.13, ty - dh + flut * bh * 0.05),
               (fx + L * 0.40, ty - dh * 0.55 + flut * bh * 0.07), (fx + L * 0.52, ty + bh * 0.02)])
    ah = bh * g["anal"]
    ay = cy + bh * 0.30
    poly(fin, [(fx + L * 0.10, ay), (fx + L * 0.22, ay + ah - flut * bh * 0.04),
               (fx + L * 0.44, ay + ah * 0.5), (fx + L * 0.52, ay - bh * 0.02)])

    # ---- body ----
    ell(s, outline, cx, cy, L * 1.03, bh * 1.07)
    ell(s, base, cx, cy, L, bh)

    # masked overlay: belly, top shading, pattern
    mask = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    ell(mask, (255, 255, 255, 255), cx, cy, L, bh)
    ov = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    ell(ov, tuple(g["belly"]) + (170,), cx - L * 0.02, cy + bh * 0.16, L * 0.88, bh * 0.62)
    ell(ov, (0, 0, 25, 55), cx, cy - bh * 0.34, L, bh * 0.5)
    pc = tuple(g["pat_col"])
    pat = g["pattern"]
    if pat == "bars":
        n = rng.randint(3, 6)
        for i in range(n):
            bx = cx - L * 0.34 + i * (L * 0.68 / max(1, n - 1))
            slant = bh * 0.10
            poly_pts = [(bx - L * 0.035 + slant, cy - bh * 0.55), (bx + L * 0.035 + slant, cy - bh * 0.55),
                        (bx + L * 0.035 - slant, cy + bh * 0.55), (bx - L * 0.035 - slant, cy + bh * 0.55)]
            pygame.draw.polygon(ov, pc + (150,), [P(*p) for p in poly_pts])
    elif pat == "hstripe":
        pygame.draw.rect(ov, pc + (205,), pygame.Rect(int((cx - L * 0.48) * SS), int((cy - bh * 0.10) * SS),
                                                      int(L * 0.96 * SS), max(1, int(bh * 0.20 * SS))))
        bright = hsv(rng.random(), 0.25, 1.0)
        pygame.draw.rect(ov, tuple(bright) + (160,), pygame.Rect(int((cx - L * 0.48) * SS), int((cy - bh * 0.22) * SS),
                                                                 int(L * 0.96 * SS), max(1, int(bh * 0.10 * SS))))
    elif pat == "spots":
        for _ in range(rng.randint(6, 13)):
            sx = cx + rng.uniform(-0.42, 0.42) * L
            sy = cy + rng.uniform(-0.38, 0.38) * bh
            r = rng.uniform(0.05, 0.11) * bh
            ell(ov, pc + (165,), sx, sy, r * 2, r * 2)
    elif pat == "patches":
        for _ in range(rng.randint(2, 4)):
            px_ = cx + rng.uniform(-0.35, 0.35) * L
            py_ = cy + rng.uniform(-0.25, 0.25) * bh
            for _ in range(3):
                ell(ov, pc + (235,), px_ + rng.uniform(-0.1, 0.1) * L,
                    py_ + rng.uniform(-0.15, 0.15) * bh, rng.uniform(0.25, 0.5) * bh, rng.uniform(0.2, 0.4) * bh)
    elif pat == "twotone":
        pygame.draw.rect(ov, pc + (150,), pygame.Rect(int((cx - L / 2) * SS), int((cy - bh * 0.55) * SS),
                                                      int(L * SS), int(bh * 0.55 * SS)))
    ov.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    s.blit(ov, (0, 0))

    # ---- head details ----
    pygame.draw.arc(s, dim(base, 0.55), pygame.Rect(int((cx + L * 0.05) * SS), int((cy - bh * 0.42) * SS),
                                                    int(L * 0.30 * SS), int(bh * 0.84 * SS)),
                    -1.1, 1.1, max(1, int(1.2 * SS)))
    mean = g.get("mean")
    ex, ey = cx + L * 0.315, cy - bh * 0.10
    er = bh * g["eye"]
    ell(s, (255, 226, 222) if mean else (238, 238, 232), ex, ey, er * 2.6, er * 2.6)
    ell(s, (198, 22, 26) if mean else (18, 20, 28), ex + er * 0.3, ey, er * 1.7, er * 1.7)
    ell(s, (255, 255, 255), ex + er * 0.55, ey - er * 0.45, er * 0.7, er * 0.7)
    if mean:  # angry brow
        pygame.draw.line(s, (30, 12, 12), P(ex - er * 1.7, ey - er * 2.2), P(ex + er * 1.1, ey - er * 1.1),
                         max(2, int(1.8 * SS)))
    if g["arch"] == "pleco":  # sucker mouth
        ell(s, dim(base, 0.5), x1 - L * 0.05, cy + bh * 0.15, bh * 0.24, bh * 0.17)
        ell(s, tuple(g["belly"]), x1 - L * 0.05, cy + bh * 0.15, bh * 0.13, bh * 0.09)
    else:
        pygame.draw.line(s, dim(base, 0.4), P(x1 - L * 0.055, cy + bh * 0.10), P(x1 - L * 0.005, cy + bh * 0.04),
                         max(1, int(1.4 * SS)))

    # ---- front overlay: pectoral fin, whiskers (kept translucent via blit) ----
    front = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    px_, py_ = cx + L * 0.10, cy + bh * 0.10
    pygame.draw.polygon(front, fin, [P(px_, py_),
                                     P(px_ - L * 0.15, py_ + bh * 0.20 + flut * bh * 0.09),
                                     P(px_ - L * 0.04, py_ + bh * 0.04)])
    if g["whiskers"]:
        for k, (dxm, dym) in enumerate([(0.10, 0.16), (0.08, 0.24)]):
            wx0, wy0 = x1 - L * 0.05, cy + bh * 0.12
            pygame.draw.line(front, dim(base, 0.5) + (220,), P(wx0, wy0),
                             P(wx0 + L * dxm, wy0 + L * dym + flut * 2.5 * (1 + k)), max(1, int(1.3 * SS)))
    s.blit(front, (0, 0))

    return pygame.transform.smoothscale(s, (W, H))


def build_fish_frames(g, scale):
    frames_r = [render_fish_frame(g, i / N_PHASES * TAU, scale) for i in range(N_PHASES)]
    frames_l = [pygame.transform.flip(f, True, False) for f in frames_r]
    return frames_r, frames_l


def build_pleco_belly(g, scale):
    """Front-glass view of a plecostomus: belly, splayed fins, sucker mouth."""
    L = g["len"] * scale
    W = int(L * 0.55)
    H = int(L)
    s = pygame.Surface((W * SS, H * SS), pygame.SRCALPHA)
    rng = random.Random(g["pseed"] ^ 0xB)
    base = dim(g["base"], 0.95)
    fin = tuple(g["fin"]) + (175,)
    cx = W / 2

    def P2(x, y):
        return (x * SS, y * SS)

    def E(col, x, y, w_, h_):
        pygame.draw.ellipse(s, col, pygame.Rect(int((x - w_ / 2) * SS), int((y - h_ / 2) * SS),
                                                max(1, int(w_ * SS)), max(1, int(h_ * SS))))

    for sgn in (-1, 1):   # splayed pectoral + ventral fins
        pygame.draw.polygon(s, fin, [P2(cx + sgn * W * 0.16, H * 0.30),
                                     P2(cx + sgn * W * 0.62, H * 0.22),
                                     P2(cx + sgn * W * 0.50, H * 0.44)])
        pygame.draw.polygon(s, fin, [P2(cx + sgn * W * 0.14, H * 0.60),
                                     P2(cx + sgn * W * 0.52, H * 0.58),
                                     P2(cx + sgn * W * 0.40, H * 0.74)])
    pygame.draw.polygon(s, fin, [P2(cx - W * 0.20, H * 0.86), P2(cx + W * 0.20, H * 0.86),
                                 P2(cx + W * 0.28, H * 0.99), P2(cx - W * 0.28, H * 0.99)])
    E(dim(base, 0.5), cx, H * 0.47, W * 0.70, H * 0.90)
    E(base, cx, H * 0.47, W * 0.66, H * 0.86)
    E(dim(tuple(g["belly"]), 0.95), cx, H * 0.52, W * 0.44, H * 0.60)
    for _ in range(rng.randint(10, 18)):
        E(dim(base, 0.55), cx + rng.uniform(-0.30, 0.30) * W, H * rng.uniform(0.10, 0.85),
          W * 0.055, W * 0.05)
    # sucker mouth at the head end
    E(dim(base, 0.45), cx, H * 0.105, W * 0.36, W * 0.27)
    E((208, 192, 162), cx, H * 0.105, W * 0.26, W * 0.19)
    E(dim(base, 0.35), cx, H * 0.105, W * 0.11, W * 0.085)
    for sgn in (-1, 1):   # little eyes
        E((16, 16, 22), cx + sgn * W * 0.18, H * 0.175, W * 0.075, W * 0.075)
        E((255, 255, 255), cx + sgn * W * 0.18 + W * 0.015, H * 0.170, W * 0.025, W * 0.025)
    return pygame.transform.smoothscale(s, (W, H))


# ----------------------------------------------------------------------------
# Particles
# ----------------------------------------------------------------------------

class Bubble:
    def __init__(self, x, y, r=None, vy=None):
        self.x, self.y = x, y
        self.r = r or random.uniform(1.5, 4.5)
        self.vy = vy or random.uniform(-90, -45)
        self.ph = random.uniform(0, TAU)

    def update(self, dt, w):
        self.ph += dt * 6
        self.y += self.vy * dt
        self.x += math.sin(self.ph) * 14 * dt
        if self.y <= w.waterline + 3:
            w.particles.append(Ripple(self.x, small=True))
            return False
        return True

    def draw(self, s, w):
        pygame.draw.circle(s, (150, 200, 220), (int(self.x), int(self.y)), int(self.r), 1)
        pygame.draw.circle(s, (220, 240, 250), (int(self.x - self.r * 0.3), int(self.y - self.r * 0.3)), 1)


class Ripple:
    def __init__(self, x, small=False):
        self.x = x
        self.t = 0.0
        self.dur = 0.55 if small else 0.9
        self.max_w = 26 if small else 70

    def update(self, dt, w):
        self.t += dt
        return self.t < self.dur

    def draw(self, s, w):
        f = self.t / self.dur
        ww = 6 + self.max_w * f
        col = dim((160, 210, 230), 1 - f * 0.85)
        r = pygame.Rect(int(self.x - ww / 2), int(w.waterline - ww * 0.12), int(ww), max(2, int(ww * 0.24)))
        pygame.draw.ellipse(s, col, r, 1)


class Pebble:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.vx = random.uniform(-45, 45)
        self.vy = random.uniform(-120, -60)
        self.t = 0.0
        self.bounced = False

    def update(self, dt, w):
        self.t += dt
        self.vy += 380 * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        floor = w.sand_top(self.x) - 1
        if self.y >= floor:
            self.y = floor
            if not self.bounced:
                self.vy *= -0.35
                self.vx *= 0.5
                self.bounced = True
            else:
                self.vy = 0
                self.vx = 0
        return self.t < 1.5

    def draw(self, s, w):
        pygame.draw.circle(s, (120, 112, 100), (int(self.x), int(self.y)), 2)


class Grain:  # sand pouring in
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.vy = random.uniform(130, 220)

    def update(self, dt, w):
        self.y += self.vy * dt
        self.x += random.uniform(-20, 20) * dt
        return self.y < w.sand_top(self.x)

    def draw(self, s, w):
        pygame.draw.circle(s, SAND_COLOR, (int(self.x), int(self.y)), 1)


class Puff:  # little cloud when food is eaten / sand settles
    def __init__(self, x, y, col=(200, 210, 200)):
        self.x, self.y = x, y
        self.t = 0.0
        self.col = col
        self.dots = [(random.uniform(-6, 6), random.uniform(-6, 6)) for _ in range(5)]

    def update(self, dt, w):
        self.t += dt
        return self.t < 0.45

    def draw(self, s, w):
        f = self.t / 0.45
        for dx, dy in self.dots:
            pygame.draw.circle(s, dim(self.col, 1 - f),
                               (int(self.x + dx * (1 + f * 2)), int(self.y + dy * (1 + f * 2))), 1)


class Sparkle:  # fight clash
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.t = 0.0

    def update(self, dt, w):
        self.t += dt
        return self.t < 0.3

    def draw(self, s, w):
        f = 1 - self.t / 0.3
        c = dim((255, 240, 200), f)
        r = int(4 + 8 * (1 - f))
        pygame.draw.line(s, c, (self.x - r, self.y), (self.x + r, self.y))
        pygame.draw.line(s, c, (self.x, self.y - r), (self.x, self.y + r))


class Poop:  # ahem. fish happen.
    """A little white worm: squeezes out, trails the fish, detaches, sinks, dissolves."""

    def __init__(self, fish):
        self.fish = fish
        self.len = clamp(fish.size * 0.22, 6, 40)
        self.th = max(2, int(fish.size * 0.035))
        self.out = 0.0            # extruded fraction
        self.attached = True
        self.pos = V2(fish.pos)
        self.ph = random.uniform(0, TAU)
        self.t = 0.0
        self.rest_t = 0.0
        self.col = (232, 229, 218)

    def vent(self):
        f = self.fish
        return V2(f.pos.x - f.facing * f.size * 0.42, f.pos.y + f.fh * 0.10)

    def update(self, dt, w):
        self.t += dt
        self.ph += dt * 2.6
        if self.attached:
            f = self.fish
            if f is None or f.remove or f.state in ("dead", "netted"):
                self.attached = False
                self.fish = None
            else:
                self.out = min(1.0, self.out + dt / 2.2)
                self.pos = self.vent()
                if self.out >= 1.0 and (f.vel.length() > f.cruise * 1.6 or random.random() < dt * 0.8):
                    self.attached = False
                    self.fish = None
            return True
        floor = w.sand_top(self.pos.x) - 3
        if self.pos.y + self.len < floor:
            self.pos.y += 15 * dt
            self.pos.x += math.sin(self.ph * 0.5) * 5 * dt
        else:
            self.rest_t += dt
            if self.rest_t > 5.5:
                w.murk = min(1.0, w.murk + 0.004)
                return False
        return self.t < 40

    def draw(self, s, w):
        L = self.len * (self.out if self.attached else 1.0)
        if L < 2:
            return
        if self.attached and self.fish is not None:
            anchor = self.vent()
            d = V2(-self.fish.facing * 0.8, 0.6).normalize()
        else:
            anchor = self.pos
            d = V2(math.sin(self.ph * 0.35) * 0.18, 1).normalize()
        perp = V2(-d.y, d.x)
        fade = 1.0
        if self.rest_t > 2:
            fade = max(0.15, 1 - (self.rest_t - 2) / 3.5)
        col = dim(self.col, 0.25 + 0.75 * fade)
        n = max(4, int(L / max(3, self.th)))
        for i in range(n):
            tt = i / (n - 1)
            p = anchor + d * (L * tt) + perp * (math.sin(self.ph + tt * 5.0) * self.th * 0.8)
            r = max(1, int(self.th * (1.0 - 0.35 * tt) * (0.4 + 0.6 * fade)))
            pygame.draw.circle(s, col, (int(p.x), int(p.y)), r)


class Tear:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.vx = random.uniform(-8, 8)
        self.t = 0.0

    def update(self, dt, w):
        self.t += dt
        self.y += (24 + self.t * 20) * dt
        self.x += self.vx * dt
        return self.t < 1.3

    def draw(self, s, w):
        f = 1 - self.t / 1.3
        col = dim((160, 215, 255), 0.45 + 0.55 * f)
        pygame.draw.circle(s, col, (int(self.x), int(self.y)), 2)
        pygame.draw.circle(s, dim(col, 1.2), (int(self.x), int(self.y) - 2), 1)


class Halves:
    """A fish bitten clean in half; both halves tumble up to the surface and fade."""
    LINGER = 8.0
    FADE = 2.5

    def __init__(self, img, pos):
        w2 = img.get_width() // 2
        h = img.get_height()
        left = img.subsurface((0, 0, w2, h)).copy()
        right = img.subsurface((w2, 0, img.get_width() - w2, h)).copy()
        self.t = 0.0
        self.parts = []
        for surf, dx, vx in ((left, -w2 * 0.5, -26), (right, w2 * 0.5, 26)):
            self.parts.append({"surf": surf, "pos": V2(pos.x + dx, pos.y),
                               "vx": vx, "vy": random.uniform(-30, -10),
                               "angle": 0.0, "spin": random.uniform(-55, 55),
                               "ph": random.uniform(0, TAU)})

    def update(self, dt, w):
        self.t += dt
        for p in self.parts:
            p["vy"] = max(p["vy"] - 70 * dt, -70)
            p["pos"].x = clamp(p["pos"].x + p["vx"] * dt, w.water.left + 20, w.water.right - 20)
            p["pos"].y += p["vy"] * dt
            p["vx"] *= max(0.0, 1 - 0.7 * dt)
            top = w.waterline + p["surf"].get_height() * 0.22
            if p["pos"].y <= top:
                p["pos"].y = top + math.sin(w.t * 1.4 + p["ph"]) * 2
                p["vy"] = 0
                p["spin"] *= max(0.0, 1 - 1.5 * dt)
            p["angle"] += p["spin"] * dt
        return self.t < self.LINGER + self.FADE

    def draw(self, s, w):
        alpha = 255
        if self.t > self.LINGER:
            alpha = max(0, int(255 * (1 - (self.t - self.LINGER) / self.FADE)))
        for p in self.parts:
            img = pygame.transform.rotate(p["surf"], p["angle"])
            if alpha < 255:
                img.set_alpha(alpha)
            s.blit(img, (int(p["pos"].x - img.get_width() / 2), int(p["pos"].y - img.get_height() / 2)))


# ----------------------------------------------------------------------------
# Food
# ----------------------------------------------------------------------------

class Pellet:
    COLORS = [(196, 148, 92), (176, 120, 70), (150, 128, 60), (188, 100, 70)]

    def __init__(self, x, y):
        self.pos = V2(x, y)
        self.vy = random.uniform(16, 30)
        self.ph = random.uniform(0, TAU)
        self.r = random.choice((2, 2, 3))
        self.col = random.choice(self.COLORS)
        self.eaten = False
        self.resting = False
        self.rest_t = random.uniform(45, 95)

    def update(self, dt, w):
        if self.eaten:
            return False
        if self.resting:
            self.rest_t -= dt
            if self.rest_t <= 0:
                w.murk = min(1.0, w.murk + 0.035)
                w.particles.append(Puff(self.pos.x, self.pos.y, (140, 150, 110)))
                return False
            return True
        self.ph += dt * 2
        if self.pos.y < w.waterline:            # falling through the air gap
            self.pos.y += 90 * dt
        else:
            self.pos.y += self.vy * dt
            self.pos.x += math.sin(self.ph) * 9 * dt
        floor = w.sand_top(self.pos.x) - self.r
        if self.pos.y >= floor:
            self.pos.y = floor
            self.resting = True
        return True

    def draw(self, s, w):
        if self.pos.y > w.waterline - 2:
            pygame.draw.circle(s, self.col, (int(self.pos.x), int(self.pos.y)), self.r)


# ----------------------------------------------------------------------------
# Rocks
# ----------------------------------------------------------------------------

class Rock:
    def __init__(self, x_frac, size, seed, front):
        self.x_frac = x_frac
        self.size = size
        self.seed = seed
        self.front = front
        self.surf = None
        self.w = self.h = 0

    def build(self):
        rng = random.Random(self.seed)
        kind = rng.random()
        if kind < 0.4:
            col = hsv(rng.uniform(0.06, 0.12), rng.uniform(0.15, 0.35), rng.uniform(0.30, 0.50))
        elif kind < 0.7:
            col = hsv(0.0, 0.0, rng.uniform(0.28, 0.48))
        else:
            col = hsv(rng.uniform(0.55, 0.62), rng.uniform(0.10, 0.25), rng.uniform(0.28, 0.45))
        if not self.front:        # background rocks sit deeper: dimmer, hazier
            col = dim(col, 0.74)
        if rng.random() < 0.28:   # occasionally a tall standing stone
            rx = self.size * rng.uniform(0.22, 0.30)
            ry = self.size * rng.uniform(0.52, 0.72)
        else:
            rx = self.size / 2
            ry = rx * rng.uniform(0.55, 0.80)
        n = rng.randint(9, 13)
        pts = []
        for i in range(n):
            a = i / n * TAU
            r = rng.uniform(0.72, 1.0)
            pts.append((rx + math.cos(a) * rx * r, ry * 1.1 + math.sin(a) * ry * r))
        W, H = int(rx * 2 + 4), int(ry * 2.3 + 4)
        s = pygame.Surface((W * SS, H * SS), pygame.SRCALPHA)
        sp = [(int(x * SS), int(y * SS)) for x, y in pts]
        pygame.draw.polygon(s, dim(col, 0.45), sp)
        inner = [(int((rx + (x - rx) * 0.90 - self.size * 0.02) * SS),
                  (int((ry * 1.1 + (y - ry * 1.1) * 0.90 - self.size * 0.045) * SS)))
                 for x, y in pts]
        pygame.draw.polygon(s, col, inner)
        lit = [(int((rx + (x - rx) * 0.62 - self.size * 0.05) * SS),
                (int((ry * 1.1 + (y - ry * 1.1) * 0.62 - self.size * 0.08) * SS)))
               for x, y in pts]
        pygame.draw.polygon(s, dim(col, 1.28), lit)
        for _ in range(rng.randint(6, 14)):
            sx = rng.uniform(rx * 0.3, rx * 1.7)
            sy = rng.uniform(ry * 0.5, ry * 1.7)
            pygame.draw.circle(s, dim(col, rng.choice((0.6, 1.5))), (int(sx * SS), int(sy * SS)), SS)
        self.surf = pygame.transform.smoothscale(s, (W, H))
        self.w, self.h = W, H

    def center(self, w):
        x = w.water.left + self.x_frac * w.water.w
        y = w.sand_top(x) + self.h * 0.10
        return x, y

    def draw(self, s, w):
        if self.surf is None:
            self.build()
        x, y = self.center(w)
        s.blit(self.surf, (int(x - self.w / 2), int(y - self.h)))


# ----------------------------------------------------------------------------
# Clams
# ----------------------------------------------------------------------------

class Clam:
    def __init__(self, x_frac, size, seed):
        self.x_frac = x_frac
        self.size = size
        self.seed = seed
        rng = random.Random(seed)
        self.facing = rng.choice((-1, 1))
        self.has_pearl = rng.random() < 0.45
        hue = rng.choice([0.08, 0.55, 0.70, 0.95])
        self.col = hsv(hue, rng.uniform(0.15, 0.40), rng.uniform(0.50, 0.78))
        self.ph = rng.uniform(0, TAU)
        self.open = 0.3
        self.t = rng.uniform(0, 20)
        self.snap_t = 0.0
        self.wide_t = 0.0
        self.next_wide = rng.uniform(6, 18)
        self.shell = None
        self.next_bubble = rng.uniform(4, 12)

    def build(self):
        R = self.size
        W, H = int(R + 8), int(R * 1.7 + 6)
        s = pygame.Surface((W * SS, H * SS), pygame.SRCALPHA)
        pivot = (4.0, H / 2)
        rng = random.Random(self.seed)
        pts = [pivot]
        n = 12
        for i in range(n + 1):
            a = math.radians(-52 + 104 * i / n)
            r = R * (1 + 0.05 * math.sin(i * 2.6))
            pts.append((pivot[0] + math.cos(a) * r, pivot[1] + math.sin(a) * r))
        sp = [(int(x * SS), int(y * SS)) for x, y in pts]
        pygame.draw.polygon(s, dim(self.col, 0.5), sp)
        inner = [(int((pivot[0] + (x - pivot[0]) * 0.93) * SS), int((pivot[1] + (y - pivot[1]) * 0.93) * SS))
                 for x, y in pts]
        pygame.draw.polygon(s, tuple(self.col), inner)
        for i in range(1, n, 2):  # ridges
            x, y = pts[i + 1]
            pygame.draw.line(s, dim(self.col, 0.62),
                             (int((pivot[0] + (x - pivot[0]) * 0.15) * SS), int((pivot[1] + (y - pivot[1]) * 0.15) * SS)),
                             (int((pivot[0] + (x - pivot[0]) * 0.92) * SS), int((pivot[1] + (y - pivot[1]) * 0.92) * SS)),
                             SS)
        self.shell = pygame.transform.smoothscale(s, (W, H))
        self.pivot = (4.0 if self.facing > 0 else W - 4.0, H / 2)
        if self.facing < 0:
            self.shell = pygame.transform.flip(self.shell, True, False)

    def hinge(self, w):
        x = w.water.left + self.x_frac * w.water.w
        y = w.sand_top(x) - self.size * 0.06
        return x, y

    def mouth(self, w):
        hx, hy = self.hinge(w)
        return hx + self.facing * self.size * 0.55, hy - self.size * 0.30

    def snap(self):
        self.snap_t = random.uniform(1.6, 3.0)

    def update(self, dt, w):
        self.t += dt
        if self.snap_t > 0:
            self.snap_t -= dt
            self.open = max(0.0, self.open - dt * 5)
        else:
            if self.wide_t > 0:
                self.wide_t -= dt
                target = 0.95
            else:
                self.next_wide -= dt
                if self.next_wide <= 0:
                    self.wide_t = random.uniform(1.5, 3.0)
                    self.next_wide = random.uniform(8, 22)
                target = 0.28 + 0.26 * math.sin(self.t * 0.35 + self.ph)
            prev = self.open
            self.open += (target - self.open) * min(1, dt * 0.9)
            if self.open > prev + 0.001:
                self.next_bubble -= dt
                if self.next_bubble <= 0:
                    mx, my = self.mouth(w)
                    w.particles.append(Bubble(mx, my, r=random.uniform(1.5, 3)))
                    self.next_bubble = random.uniform(5, 16)
        # startled by fast fish passing close
        for f in w.fish:
            if f.state in ("dead", "netted"):
                continue
            hx, hy = self.hinge(w)
            if abs(f.pos.x - hx) < self.size * 1.2 and abs(f.pos.y - hy) < self.size * 1.1 \
                    and f.vel.length_squared() > 70 * 70 and self.snap_t <= 0 and self.open > 0.3:
                self.snap()
                break

    def draw(self, s, w):
        if self.shell is None:
            self.build()
        hx, hy = self.hinge(w)
        base_tilt = 14
        # mouth interior
        if self.open > 0.12:
            mid = math.radians((base_tilt + self.open * 46) / 2 - base_tilt)
            r = self.size * 0.8
            a0 = math.radians(-base_tilt + 6)
            a1 = -math.radians(base_tilt + self.open * 46 - 6)
            pts = [(hx, hy)]
            for a in (a0, (a0 + a1) / 2, a1):
                pts.append((hx + self.facing * math.cos(a) * r, hy + math.sin(a) * r))
            pygame.draw.polygon(s, (146, 90, 100), [(int(x), int(y)) for x, y in pts])
            if self.has_pearl and self.open > 0.5:
                px = hx + self.facing * math.cos(mid) * r * 0.5
                py = hy + math.sin(mid) * r * 0.5
                pygame.draw.circle(s, (235, 230, 225), (int(px), int(py)), max(2, int(self.size * 0.10)))
                pygame.draw.circle(s, (255, 255, 255), (int(px - 1), int(py - 1)), 1)
        blit_rotated(s, self.shell, (hx, hy), self.pivot, self.facing * -base_tilt)
        top = pygame.transform.flip(self.shell, False, True)
        blit_rotated(s, top, (hx, hy), self.pivot, self.facing * (base_tilt + self.open * 46))


# ----------------------------------------------------------------------------
# Fish
# ----------------------------------------------------------------------------

class Fish:
    def __init__(self, w, g, name, fid, hunger=0.15, health=100.0, age=0.0, pos=None):
        self.w_ref = w
        self.g = g
        self.name = name
        self.id = fid
        self.traits = g["traits"]
        self.arch = g["arch"]
        self.hunger = hunger
        self.health = health
        self.age = age
        self.rebuild_sprites()
        if pos is None:
            pos = V2(random.uniform(w.water.left + 100, w.water.right - 100),
                     random.uniform(w.waterline + 60, w.water.bottom - 120))
        self.pos = V2(pos)
        self.vel = V2(random.uniform(-20, 20), 0)
        self.facing = 1 if self.vel.x >= 0 else -1
        self.force_face = None
        self.pitch = 0.0
        self.phase = random.uniform(0, TAU)
        self.state = "wander"
        self.until = 0.0
        self.wander_pt = None
        self.wander_until = 0.0
        self.target = None        # pellet or fish or point, by state
        self.partner = None
        self.rock = None
        self.point = None
        self.threat = None
        self.threat_pos = None
        self.starve_t = 0.0
        self.eat_pause = 0.0
        self.cool = {}
        self.death_t = 0.0
        self.remove = False
        self.next_poop = random.uniform(40, 160)
        self.beg_pt = None
        self.beg_next = 0.0
        self.puff = 1.0           # puffer inflation factor
        self.cry_t = 0.0
        self.turn = 2.2 + self.traits["energy"] * 1.3
        self._ckey = None
        self._csurf = None

    def rebuild_sprites(self):
        """(Re)generate frames and speed from the genome — also after growth spurts."""
        w = self.w_ref
        g = self.g
        growth = 1 + min(self.age / 86400 / 10, 1.0) * 0.18
        self.scale = w.fish_scale * growth * g.get("mult", 1.0)
        cap = w.water.h * 0.35
        if g["len"] * self.scale > cap:
            self.scale = cap / g["len"]
        self.size = g["len"] * self.scale
        self.frames_r, self.frames_l = build_fish_frames(g, self.scale)
        self.fw = self.frames_r[0].get_width()
        self.fh = self.frames_r[0].get_height()
        self.mouth_dx = self.fw / 2 - 5
        e = self.traits["energy"]
        self.cruise = (26 + self.size * 0.45) * (0.6 + e * 0.8) * g.get("speed_mult", 1.0)
        self.burst = self.cruise * 2.7
        self.belly = None
        self._ckey = None
        self._csurf = None

    def grow(self, factor):
        """Mean-duel prize: bigger and faster (capped so it stays on screen)."""
        self.g["mult"] = round(min(self.g.get("mult", 1.0) * factor, 4.0), 2)
        self.g["speed_mult"] = round(min(self.g.get("speed_mult", 1.0) * factor, 6.0), 2)
        self.rebuild_sprites()
        self.w_ref.dirty = True

    # ---------------- state helpers ----------------
    def set_state(self, name, dur, target=None, partner=None, rock=None, point=None, threat=None):
        self.state = name
        self.until = self.w_ref.t + dur
        self.target = target
        self.partner = partner
        self.rock = rock
        self.point = V2(point) if point is not None else None
        if threat is not None:
            self.threat = threat
            self.threat_pos = V2(threat.pos)
        self.force_face = None
        if name == "circle":
            self.circle_a = random.uniform(0, TAU)

    def calm(self):
        return self.state in CALM_STATES

    def gone(self):
        return self.remove or self.state in ("dead", "netted")

    def die(self, w):
        if self.state == "dead":
            return
        if self.partner and self.partner.partner is self:
            self.partner.partner = None
            self.partner.set_state("wander", 1)
        self.state = "dead"
        self.death_t = 0.0
        self.vel = V2(random.uniform(-8, 8), -15)
        for _ in range(6):
            w.particles.append(Bubble(self.pos.x + random.uniform(-8, 8), self.pos.y, r=random.uniform(1.5, 3.5)))
        w.murk = min(1.0, w.murk + 0.04)
        w.dirty = True

    def zone_band(self, w):
        top = w.waterline + 30
        floor = w.water.bottom - w.sand_cur * w.max_sand - 24
        lo, hi = self.g["zone"]
        h = max(60, floor - top)
        return top + lo * h, top + hi * h

    # ---------------- per-frame ----------------
    def update(self, dt, w):
        self.age += dt
        if self.state == "netted":
            self.pos.y -= 300 * dt
            self.pos.x += self.vel.x * dt * 0.2
            if self.pos.y < w.water.top - self.fh:
                self.remove = True
            return
        if self.state == "dead":
            self.death_t += dt
            surf_y = w.waterline + self.fh * 0.30
            if self.pos.y > surf_y:
                self.vel.y = max(self.vel.y - 60 * dt, -75)
                self.pos += self.vel * dt
                self.vel.x *= 0.995
            else:
                self.pos.y = surf_y + math.sin(w.t * 1.5 + self.id) * 2
                self.pos.x += math.sin(w.t * 0.4 + self.id) * 6 * dt
            self.pos.x = clamp(self.pos.x, w.water.left + 30, w.water.right - 30)
            if self.death_t > DEAD_LINGER_S + 3.5:
                self.remove = True
            return

        # hunger / health
        self.hunger = min(1.0, self.hunger + dt / HUNGER_FULL_S)
        if self.hunger >= 0.999:
            self.starve_t += dt
            if self.starve_t > STARVE_GRACE_S:
                self.health -= STARVE_DPS * dt
        else:
            self.starve_t = max(0.0, self.starve_t - dt * 2)
        if self.hunger < 0.5 and self.health < 100:
            self.health = min(100.0, self.health + HEAL_PS * dt)
        if self.health <= 0:
            self.die(w)
            return
        weak = self.health < 30
        if self.eat_pause > 0:
            self.eat_pause -= dt
        if self.arch == "puffer":  # puff up when startled or fleeing
            tgt = 1.25 if self.state in ("flee", "startle") else 1.0
            self.puff += (tgt - self.puff) * min(1, dt * 5)
        if self.next_poop > 0:
            self.next_poop -= dt
            if self.next_poop <= 0:
                w.particles.append(Poop(self))
                self.next_poop = random.uniform(90, 240)
        if self.cry_t > 0:
            self.cry_t -= dt
            if random.random() < dt * 3.0:
                w.particles.append(Tear(self.pos.x + self.facing * self.size * 0.26,
                                        self.pos.y - self.fh * 0.10))

        # pleco latched onto the front glass, rasping algae
        if self.state == "suck":
            self.vel = V2(0, 0)
            spot = self.target
            if not any(sp is spot for sp in w.algae):
                spot = w.nearest_algae(self.pos)
                self.target = spot
            if spot is not None:
                goal = V2(spot["x"], spot["y"])
                d = goal - self.pos
                if d.length() > 6:
                    self.pos += d.normalize() * min(30 * dt, d.length())
                else:
                    spot["r"] -= 1.4 * dt
                    self.hunger = max(0.0, self.hunger - dt * 0.03)
                    if spot["r"] <= 3:
                        w.algae.remove(spot)
                        w.particles.append(Puff(self.pos.x, self.pos.y, (110, 150, 100)))
                        self.target = None
            if w.t > self.until or (spot is None and random.random() < dt * 0.2):
                for _ in range(3):
                    w.particles.append(Bubble(self.pos.x + random.uniform(-6, 6), self.pos.y))
                self.set_state("wander", 1)
            self.phase += dt * 1.2
            return

        # threat interrupt: someone is charging me
        if self.state not in ("flee", "display", "hide"):
            for f in w.fish:
                if f.state == "chase" and f.target is self and f.pos.distance_to(self.pos) < 240:
                    self.set_state("flee", 2.5, threat=f)
                    break

        desired = self.steer(dt, w)

        # gentle separation from other fish
        if self.state not in ("display", "circle", "school"):
            for f in w.fish:
                if f is self or f.gone():
                    continue
                d = self.pos - f.pos
                dist = d.length()
                lim = (self.size + f.size) * 0.36
                if 0 < dist < lim:
                    desired += d / dist * (lim - dist) * 3.0

        # wall / floor / surface avoidance
        m = 70
        top_b = w.waterline + max(20, self.fh * 0.35)
        if self.state == "beg":
            top_b = w.waterline + 8
        floor_b = w.sand_top(self.pos.x) - self.size * (0.10 if self.arch == "catfish" else 0.25)
        if self.pos.x < w.water.left + m:
            desired.x += (1 - (self.pos.x - w.water.left) / m) * 260
        if self.pos.x > w.water.right - m:
            desired.x -= (1 - (w.water.right - self.pos.x) / m) * 260
        if self.pos.y < top_b + m * 0.6:
            desired.y += (1 - (self.pos.y - top_b) / (m * 0.6)) * 200
        if self.pos.y > floor_b - m * 0.6:
            desired.y -= (1 - (floor_b - self.pos.y) / (m * 0.6)) * 200

        if self.eat_pause > 0:
            desired *= 0.12
        if weak:
            desired *= 0.4

        turn = self.turn * (1.8 if self.state in ("flee", "chase") else 1.0)
        self.vel = self.vel.lerp(desired, min(1.0, turn * dt))
        limit = self.burst if self.state in ("flee", "chase", "startle") else self.cruise * 1.6
        if weak:
            limit *= 0.45
        spd = self.vel.length()
        if spd > limit:
            self.vel.scale_to_length(limit)
        self.pos += self.vel * dt
        self.pos.x = clamp(self.pos.x, w.water.left + 12, w.water.right - 12)
        self.pos.y = clamp(self.pos.y, w.waterline + 8, max(w.waterline + 9, floor_b))

        # facing with hysteresis
        if self.force_face:
            self.facing = self.force_face
        elif self.vel.x > 9:
            self.facing = 1
        elif self.vel.x < -9:
            self.facing = -1

        tp = clamp(math.degrees(math.atan2(-self.vel.y, abs(self.vel.x) + 26)), -26, 26)
        if weak:
            tp -= 9
        self.pitch += (tp - self.pitch) * min(1, dt * 6)
        rate = 3.2 + self.vel.length() * 0.05
        if self.state == "display":
            rate *= 2.2
        if weak:
            rate *= 0.5
        self.phase += rate * dt

    # ---------------- steering by state ----------------
    def steer(self, dt, w):
        s = self.state
        t = w.t

        def seek(pt, speed):
            d = V2(pt) - self.pos
            L = d.length()
            if L < 1:
                return V2(0, 0)
            arrive = clamp(L / 110, 0.15, 1.0)
            return d / L * speed * arrive

        if s == "arriving":
            for _ in range(1) if random.random() < dt * 6 else []:
                w.particles.append(Bubble(self.pos.x, self.pos.y))
            if self.pos.y > w.waterline + 90 or t > self.until:
                self.set_state("wander", 1)
            return V2(0, 90)

        if s == "startle":
            if t > self.until:
                self.set_state("wander", 1)
            return self.vel * 1.0

        if s == "to_glass":
            spot = self.target
            if not (isinstance(spot, dict) and any(sp is spot for sp in w.algae)) or t > self.until:
                self.set_state("wander", 1)
                return V2(0, 0)
            goal = V2(spot["x"], spot["y"])
            if self.pos.distance_to(goal) < 26:
                self.set_state("suck", random.uniform(60, 150), target=spot)
                return V2(0, 0)
            return seek(goal, self.cruise * 1.2)

        if s == "seek_food":
            p = self.target
            if p is None or p.eaten:
                p = w.nearest_pellet(self.pos, prefer_resting=(self.arch in ("catfish", "pleco")))
                self.target = p
            if p is None or self.hunger < 0.06:
                self.set_state("wander", 1)
                return V2(0, 0)
            return seek(p.pos, self.cruise * 1.6)

        if s == "beg":
            if t > self.until:
                self.set_state("wander", 1)
            if self.beg_pt is None or t > self.beg_next:
                self.beg_pt = V2(clamp(self.pos.x + random.uniform(-260, 260), w.water.left + 60, w.water.right - 60),
                                 w.waterline + random.uniform(12, 44))
                self.beg_next = t + random.uniform(0.9, 1.6)
                if random.random() < 0.4:
                    w.particles.append(Ripple(self.pos.x, small=True))
            return seek(self.beg_pt, self.cruise * 1.4)

        if s == "chase":
            v = self.target
            mean = self.g.get("mean")
            if v is None or v.gone() or v.state == "suck" or t > self.until:
                if mean:
                    self.cool["hunt"] = t + random.uniform(10, 18)
                else:
                    self.cool["agg"] = t + random.uniform(10, 22)
                self.set_state("wander", 1)
                return V2(0, 0)
            if self.pos.distance_to(v.pos) < self.size * 0.5 + v.size * 0.25:
                if mean and not v.g.get("mean"):
                    w.bite(self, v)
                else:
                    w.nip(self, v)
                    self.cool["agg"] = t + random.uniform(14, 30)
                self.set_state("wander", 1)
                return V2(0, 0)
            return seek(v.pos, self.burst)

        if s == "flee":
            if self.threat is not None and not self.threat.gone():
                self.threat_pos = V2(self.threat.pos)
            away = self.pos - (self.threat_pos or self.pos)
            if away.length_squared() < 1:
                away = V2(random.uniform(-1, 1), 0)
            if t > self.until or away.length() > 430:
                self.threat = None
                if self.health < 30 and w.rocks and self.traits["timid"] > 0.35:
                    r = max(w.rocks, key=lambda rk: rk.size)
                    self.set_state("hide", random.uniform(5, 9), rock=r)
                else:
                    self.set_state("wander", 1)
                return V2(0, 0)
            d = away.normalize() * self.burst
            if self.traits["timid"] > 0.6 and w.rocks:
                r = max(w.rocks, key=lambda rk: rk.size)
                rx, ry = r.center(w)
                d = d * 0.5 + seek((rx, ry - r.h * 0.5), self.burst) * 0.5
            return d

        if s == "hide":
            if self.rock not in w.rocks:
                self.set_state("wander", 1)
                return V2(0, 0)
            rx, ry = self.rock.center(w)
            if t > self.until and self.health > 25:
                self.set_state("wander", 1)
            return seek((rx, ry - self.rock.h * 0.45), self.cruise * 0.8)

        if s == "display":
            p = self.partner
            if p is None or p.gone() or p.partner is not self:
                self.set_state("wander", 1)
                return V2(0, 0)
            if t > self.until:
                if self.id < p.id:
                    w.resolve_duel(self, p)
                return V2(0, 0)
            self.force_face = 1 if p.pos.x > self.pos.x else -1
            gap = (self.size + p.size) * 0.42
            dirv = self.pos - p.pos
            if dirv.length_squared() < 1:
                dirv = V2(1, 0)
            anchor = p.pos + dirv.normalize() * gap
            anchor.y += math.sin(t * 9 + self.id) * 7
            return seek(anchor, self.cruise * 1.8)

        if s == "circle":
            p = self.partner
            if p is None or p.gone() or t > self.until:
                if p is not None and not p.gone() and self.id > p.id:
                    w.rel_add(self, p, +0.08)
                self.set_state("wander", 1)
                return V2(0, 0)
            self.circle_a += dt * 2.6
            ctr = (self.pos + p.pos) / 2 if p.partner is not self else self.point
            if self.point is not None:
                ctr = self.point
            r = (self.size + p.size) * 0.55
            pt = V2(ctr.x + math.cos(self.circle_a) * r, ctr.y + math.sin(self.circle_a) * r * 0.6)
            return seek(pt, self.cruise * 1.6)

        if s == "play":
            if self.rock not in w.rocks or t > self.until:
                self.cool["play"] = t + random.uniform(25, 70)
                self.set_state("wander", 1)
                return V2(0, 0)
            rx, ry = self.rock.center(w)
            self.circle_a = getattr(self, "circle_a", 0.0) + dt * 2.2
            r = self.rock.w * 0.62 + self.size * 0.42
            pt = V2(rx + math.cos(self.circle_a) * r, ry - self.rock.h * 0.4 + math.sin(self.circle_a) * r * 0.5)
            if random.random() < dt * 0.7:
                w.particles.append(Pebble(rx + random.uniform(-8, 8), ry - self.rock.h * 0.8))
            return seek(pt, self.cruise * 1.3)

        if s == "investigate":
            if t > self.until or self.point is None:
                self.set_state("wander", 1)
                return V2(0, 0)
            pt = self.point + V2(math.sin(t * 3 + self.id) * 12, math.cos(t * 2.4 + self.id) * 8)
            return seek(pt, self.cruise * 1.1)

        if s == "rest":
            if t > self.until:
                self.set_state("wander", 1)
            if self.point is None:
                self.point = V2(self.pos.x + random.uniform(-60, 60),
                                w.sand_top(self.pos.x) - self.size * (0.16 if self.arch == "catfish" else 0.6))
            d = seek(self.point, self.cruise * 0.5)
            if self.arch == "catfish" and self.pos.distance_to(self.point) < 20:
                return V2(0, 6)
            return d

        if s == "school":
            ldr = self.target
            if ldr is None or ldr.gone() or t > self.until:
                self.set_state("wander", 1)
                return V2(0, 0)
            off = V2(-ldr.facing * (ldr.size * 0.8 + 14), math.sin(t * 1.7 + self.id) * 16)
            return seek(ldr.pos + off, min(self.cruise * 1.5, ldr.vel.length() + 60))

        # ---- wander (default) ----
        if self.wander_pt is None or t > self.wander_until or self.pos.distance_to(self.wander_pt) < 34:
            zlo, zhi = self.zone_band(w)
            self.wander_pt = V2(random.uniform(w.water.left + 60, w.water.right - 60),
                                random.uniform(zlo, zhi))
            self.wander_until = t + random.uniform(3, 7)
        d = seek(self.wander_pt, self.cruise * random.uniform(0.85, 1.0))
        if self.arch == "tetra":  # loose schooling with other tetras
            coh = V2(); ali = V2(); sep = V2(); n = 0
            for f in w.fish:
                if f is self or f.arch != "tetra" or f.gone():
                    continue
                dist = self.pos.distance_to(f.pos)
                if dist < 250:
                    coh += f.pos; ali += f.vel; n += 1
                    if dist < 55 and dist > 0:
                        sep += (self.pos - f.pos) / dist * (55 - dist)
            if n:
                d += ((coh / n) - self.pos) * 0.35 + (ali / n - self.vel) * 0.4 + sep * 1.4
        return d

    # ---------------- drawing ----------------
    def mouth_pos(self):
        return V2(self.pos.x + self.facing * self.mouth_dx * 0.92, self.pos.y)

    def draw(self, s, w):
        if self.state == "suck":   # pleco belly-first on the front glass
            if self.belly is None:
                self.belly = build_pleco_belly(self.g, self.scale)
            img = self.belly
            s.blit(img, (int(self.pos.x - img.get_width() / 2), int(self.pos.y - img.get_height() / 2)))
            mr = max(3, int(img.get_width() * 0.15 + math.sin(w.t * 6 + self.id) * 1.5))
            pygame.draw.circle(s, (215, 200, 170),
                               (int(self.pos.x), int(self.pos.y - img.get_height() * 0.395)), mr, 2)
            return
        idx = int(self.phase / TAU * N_PHASES) % N_PHASES
        dead = self.state == "dead"
        alpha = 255
        if dead and self.death_t > DEAD_LINGER_S:
            alpha = max(0, int(255 * (1 - (self.death_t - DEAD_LINGER_S) / 3.5)))
        elif self.health < 45 and not dead:
            alpha = int(150 + 105 * self.health / 45)
        angle = round((self.pitch * self.facing) / 4) * 4
        if dead:
            angle = round(math.sin(w.t * 0.9 + self.id) * 8 / 4) * 4
        pf = round(self.puff, 2)
        key = (idx, self.facing, angle, alpha // 16, dead, pf)
        if key != self._ckey:
            img = self.frames_r[idx] if self.facing > 0 else self.frames_l[idx]
            if dead:
                img = pygame.transform.flip(img, False, True)
            img = pygame.transform.rotate(img, angle)
            if pf > 1.02:
                img = pygame.transform.smoothscale_by(img, pf)
            if alpha < 255:
                img = img.copy()
                img.set_alpha(alpha)
            self._ckey = key
            self._csurf = img
        img = self._csurf
        s.blit(img, (int(self.pos.x - img.get_width() / 2), int(self.pos.y - img.get_height() / 2)))

    # ---------------- persistence ----------------
    def to_dict(self, w):
        return {
            "id": self.id, "name": self.name, "genome": self.g,
            "hunger": round(self.hunger, 4), "health": round(self.health, 2),
            "age": round(self.age, 1),
            "xf": round((self.pos.x - w.water.left) / w.water.w, 4),
            "yf": round((self.pos.y - w.water.top) / w.water.h, 4),
        }


# ----------------------------------------------------------------------------
# The tank
# ----------------------------------------------------------------------------

class Aquarium:
    def __init__(self, screen_size, save_path, seed=None, reset=False):
        self.W, self.H = screen_size
        self.save_path = Path(save_path)
        self.t = 0.0
        self.murk = 0.0
        self.dirty = False
        self.next_id = 1
        self.fish = []
        self.rocks = []
        self.clams = []
        self.pellets = []
        self.particles = []
        self.corpses = []        # bitten-in-half fish floating up
        self.algae = []          # spots growing on the front glass
        self.algae_next = random.uniform(6, 14)
        self.fish_added = 0      # lifetime count; every MEAN_EVERYth is mean
        self.pills = []          # (fish, until)
        self.rels = {}
        self.sand_frac = 0.5
        self.sand_cur = 0.5
        self.social_timer = 0.0
        self.save_timer = SAVE_EVERY_S
        self.airstone_next = 0.0
        self.layout()
        loaded = False
        if not reset and self.save_path.exists():
            try:
                with open(self.save_path) as f:
                    self.from_dict(json.load(f))
                loaded = True
            except Exception as e:
                print(f"save file unreadable ({e}); starting a fresh tank", file=sys.stderr)
        if not loaded:
            self.seed = seed if seed is not None else random.randrange(1 << 30)
            self._seed_layout()
            self.starter_tank()
        else:
            self._seed_layout()

    # ---------------- layout ----------------
    def layout(self):
        b = max(12, round(min(self.W, self.H) * 0.035))
        self.border = b
        bar_h = clamp(int(self.H * 0.13), 96, 150)
        self.bar_h = bar_h
        gt = max(5, b // 3)
        self.glass = gt
        self.tank = pygame.Rect(b, b, self.W - 2 * b, self.H - 2 * b - bar_h - b // 2)
        self.water = self.tank.inflate(-2 * gt, -2 * gt)
        self.water.center = self.tank.center
        self.waterline = self.water.top + int(self.water.h * 0.05)
        self.max_sand = self.water.h * MAX_SAND_FRAC
        self.fish_scale = clamp(self.water.w / 1800, 0.55, 1.5)
        # pre-rendered water gradient
        self.water_bg = pygame.Surface(self.water.size)
        for y in range(0, self.water.h, 2):
            f = y / self.water.h
            col = [int(lerp(WATER_TOP[i], WATER_BOTTOM[i], f)) for i in range(3)]
            pygame.draw.rect(self.water_bg, col, (0, y, self.water.w, 2))
        # light ray sprite: soft-edged, premultiplied for additive blit
        rw = max(50, int(self.water.w * 0.055))
        rh = self.water.h + 60
        small = pygame.Surface((28, 90))
        for yy in range(90):
            va = (1 - yy / 90) ** 1.6
            for xx in range(28):
                ha = max(0.0, 1 - abs(xx - 13.5) / 13.5) ** 1.5
                a = 24 * va * ha
                small.set_at((xx, yy), (int(200 * a / 255), int(230 * a / 255), int(255 * a / 255)))
        ray = pygame.transform.smoothscale(small, (rw, rh))
        self.ray_surf = pygame.transform.rotate(ray, -16)
        self.murk_surf = pygame.Surface((self.water.w, self.water.h - (self.waterline - self.water.top)))
        self.murk_surf.fill((64, 82, 38))
        # playful plaque: per-letter colored glyphs + little fish bookends
        pal = [(255, 138, 128), (255, 209, 102), (128, 222, 234),
               (206, 147, 216), (165, 214, 167), (255, 171, 145), (129, 212, 250)]
        psz = int(clamp(b * 1.1, 26, 56))
        pfont = font(psz)
        self.plaque = []
        x = 0.0
        ci = 0
        for ch in "MAX'S AQUARIUM":
            if ch == " ":
                x += psz * 0.45
                continue
            gs = pfont.render(ch, True, pal[ci % len(pal)])
            self.plaque.append((gs, x, ci))
            x += gs.get_width() + psz * 0.10
            ci += 1
        self.plaque_w = x - psz * 0.10
        self.plaque_h = pfont.get_height()
        fh = int(psz * 0.95)
        bk = pygame.Surface((int(fh * 1.7), fh), pygame.SRCALPHA)
        icon_fish(bk, bk.get_rect(), (255, 209, 102))
        self.plaque_fish_l = bk                                    # faces right
        self.plaque_fish_r = pygame.transform.flip(bk, True, False)

    def _seed_layout(self):
        rng = random.Random(self.seed)
        self.dune = [(rng.uniform(0.004, 0.008), rng.uniform(0, TAU)),
                     (rng.uniform(0.010, 0.016), rng.uniform(0, TAU))]
        self.speckles = [(rng.random(), rng.random(), rng.choice((0.82, 1.14))) for _ in range(260)]
        self.airstone_x = self.water.left + self.water.w * rng.choice((0.06, 0.94))
        # glass streaks
        st = pygame.Surface(self.water.size, pygame.SRCALPHA)
        for i in range(2):
            x0 = self.water.w * rng.uniform(0.1, 0.8)
            wdt = self.water.w * rng.uniform(0.03, 0.06)
            pts = [(x0, 0), (x0 + wdt, 0),
                   (x0 + wdt - self.water.h * 0.35, self.water.h), (x0 - self.water.h * 0.35, self.water.h)]
            pygame.draw.polygon(st, (255, 255, 255, 7), pts)
        self.streaks = st

    def sand_top(self, x):
        if self.sand_cur <= 0.015:
            return self.water.bottom
        lvl = self.sand_cur * self.max_sand
        d = 0.0
        for i, (f, p) in enumerate(self.dune):
            amp = lvl * (0.10 if i == 0 else 0.05) + 2
            d += math.sin(x * f + p) * amp
        return clamp(self.water.bottom - lvl + d, self.waterline + 40, self.water.bottom)

    # ---------------- populate ----------------
    def starter_tank(self):
        self.sand_frac = self.sand_cur = 0.5
        rng = random.Random(self.seed ^ 0x5EED)
        for _ in range(3):
            self.add_rock(quiet=True)
        for _ in range(2):
            self.add_clam(quiet=True)
        for arch in ("tetra", "tetra", "goldfish", "tang", "catfish"):
            self.add_fish(arch=arch, quiet=True)
        self.seed_algae(3)
        self.dirty = True

    def _pick_name(self):
        used = {f.name for f in self.fish}
        avail = [n for n in NAMES if n not in used]
        if avail:
            return random.choice(avail)
        return random.choice(NAMES) + " " + str(random.randint(2, 9))

    def add_fish(self, arch=None, quiet=False):
        if len([f for f in self.fish if not f.gone()]) >= MAX_FISH:
            return None
        self.fish_added += 1
        mean = self.fish_added % MEAN_EVERY == 0
        if arch is None and not mean and self.algae \
                and random.random() < 0.10 + 0.30 * len(self.algae) / MAX_ALGAE:
            arch = "pleco"   # a dirty tank attracts plecos
        if mean and arch in (None, "pleco"):   # mean fish are swimmers
            names = [n for n in ARCH_WEIGHTS if n != "pleco"]
            arch = random.choices(names, weights=[ARCH_WEIGHTS[n] for n in names])[0]
        g = make_genome(random.Random(random.randrange(1 << 30)), arch=arch)
        if mean:
            g["mean"] = True
            g["speed_mult"] = 1.5
            g["traits"].update(agg=1.0, timid=0.02, soc=0.05,
                               energy=max(0.8, g["traits"]["energy"]))
        f = Fish(self, g, self._pick_name(), self.next_id)
        self.next_id += 1
        self.fish.append(f)
        if not quiet:
            f.pos = V2(random.uniform(self.water.left + 150, self.water.right - 150), self.waterline - 18)
            f.set_state("arriving", 2.5)
            self.particles.append(Ripple(f.pos.x))
            for _ in range(4):
                self.particles.append(Bubble(f.pos.x + random.uniform(-10, 10), self.waterline + 12))
            self.announce(V2(f.pos.x, self.waterline + 120), kind="newfish", newcomer=f)
        # rival seed: two bettas is a standoff waiting to happen
        if g["arch"] == "betta":
            for other in self.fish:
                if other is not f and other.arch == "betta":
                    self.rels[self._rk(f.id, other.id)] = -0.45
        self.dirty = True
        return f

    def remove_fish(self, pick=None):
        if pick is None:
            dead = [f for f in self.fish if f.state == "dead"]
            pick = dead[0] if dead else next((f for f in reversed(self.fish) if not f.gone()), None)
        if pick is None:
            return
        if pick.partner and pick.partner.partner is pick:
            pick.partner.partner = None
        pick.state = "netted"
        self.particles.append(Ripple(pick.pos.x))
        self.dirty = True

    def add_rock(self, quiet=False):
        if len(self.rocks) >= MAX_ROCKS:
            return
        best, best_d = None, -1
        for _ in range(10):
            xf = random.uniform(0.06, 0.94)
            d = min([abs(xf - r.x_frac) for r in self.rocks] + [1.0])
            if d > best_d:
                best, best_d = xf, d
        size = min(random.uniform(40, 300) * self.fish_scale, self.water.h * 0.35)
        r = Rock(best, size, random.randrange(1 << 30), front=random.random() < 0.4)
        self.rocks.append(r)
        if not quiet:
            x = self.water.left + r.x_frac * self.water.w
            self.announce(V2(x, self.sand_top(x) - 60), kind="object")
            for _ in range(3):
                self.particles.append(Puff(x + random.uniform(-20, 20), self.sand_top(x) - 6, dim(SAND_COLOR, 0.9)))
        self.dirty = True

    def remove_rock(self, rock=None):
        if not self.rocks:
            return
        r = rock if rock in self.rocks else self.rocks[-1]
        self.rocks.remove(r)
        x = self.water.left + r.x_frac * self.water.w
        for _ in range(4):
            self.particles.append(Puff(x + random.uniform(-16, 16), self.sand_top(x) - 8, dim(SAND_COLOR, 0.9)))
        self.dirty = True

    def add_clam(self, quiet=False):
        if len(self.clams) >= MAX_CLAMS:
            return
        best, best_d = None, -1
        for _ in range(10):
            xf = random.uniform(0.08, 0.92)
            d = min([abs(xf - c.x_frac) for c in self.clams] + [abs(xf - r.x_frac) * 1.5 for r in self.rocks] + [1.0])
            if d > best_d:
                best, best_d = xf, d
        c = Clam(best, random.uniform(42, 72) * self.fish_scale, random.randrange(1 << 30))
        self.clams.append(c)
        if not quiet:
            x = self.water.left + c.x_frac * self.water.w
            self.announce(V2(x, self.sand_top(x) - 50), kind="object")
        self.dirty = True

    def remove_clam(self, clam=None):
        if not self.clams:
            return
        c = clam if clam in self.clams else self.clams[-1]
        self.clams.remove(c)
        hx, hy = c.hinge(self)
        for _ in range(3):
            self.particles.append(Bubble(hx + random.uniform(-8, 8), hy - 10))
        self.dirty = True

    def sand_up(self):
        if self.sand_frac < 0.999:
            self.sand_frac = min(1.0, self.sand_frac + 1 / SAND_STEPS)
            self.dirty = True

    def sand_down(self):
        if self.sand_frac > 0.001:
            self.sand_frac = max(0.0, self.sand_frac - 1 / SAND_STEPS)
            self.dirty = True

    def feed(self):
        if len(self.pellets) >= MAX_PELLETS:
            return
        n = random.randint(10, 16) if len(self.pellets) < 60 else 4
        cx = random.uniform(self.water.left + self.water.w * 0.18, self.water.right - self.water.w * 0.18)
        for _ in range(n):
            self.pellets.append(Pellet(clamp(cx + random.gauss(0, 60), self.water.left + 10, self.water.right - 10),
                                       self.waterline - random.uniform(4, 60)))
        self.particles.append(Ripple(cx))

    # ---------------- algae ----------------
    def spawn_algae(self):
        x = random.uniform(self.water.left + 40, self.water.right - 40)
        y = random.uniform(self.waterline + 40, self.water.bottom - 30)
        mr = random.uniform(16, 55) * clamp(self.fish_scale, 0.7, 1.4)
        self.algae.append(self._make_spot(x, y, 4.0, mr, random.uniform(0.15, 0.40),
                                          random.randrange(1 << 30)))
        self.dirty = True

    def seed_algae(self, n):
        """Guarantee some already-visible growth (fresh tanks, old saves)."""
        while len(self.algae) < n:
            self.spawn_algae()
            a = self.algae[-1]
            a["r"] = a["max_r"] * random.uniform(0.45, 0.85)

    @staticmethod
    def _make_spot(x, y, r, max_r, rate, seed):
        rng = random.Random(seed)
        blobs = [(rng.uniform(-0.65, 0.65), rng.uniform(-0.65, 0.65), rng.uniform(0.35, 0.85))
                 for _ in range(rng.randint(4, 6))]
        return {"x": x, "y": y, "r": r, "max_r": max_r, "rate": rate,
                "seed": seed, "blobs": blobs}

    def nearest_algae(self, pos):
        best, bd = None, 1e18
        for a in self.algae:
            d = (pos - V2(a["x"], a["y"])).length_squared()
            if d < bd:
                best, bd = a, d
        return best

    # ---------------- relationships ----------------
    @staticmethod
    def _rk(a, b):
        return f"{min(a, b)}-{max(a, b)}"

    def rel(self, a, b):
        k = self._rk(a.id, b.id)
        if k in self.rels:
            return self.rels[k]
        if a.arch == "betta" and b.arch == "betta":
            return -0.45
        if a.arch == "tetra" and b.arch == "tetra":
            return 0.3
        return 0.0

    def rel_add(self, a, b, delta):
        k = self._rk(a.id, b.id)
        self.rels[k] = clamp(self.rel(a, b) + delta, -1.0, 1.0)

    # ---------------- fish interactions ----------------
    def fights_active(self):
        return sum(1 for f in self.fish if f.state in ("chase", "display"))

    def bite(self, att, vic):
        """A mean fish bites a victim clean in half."""
        if vic.gone():
            return
        if vic.partner and vic.partner.partner is vic:
            vic.partner.partner = None
        idx = int(vic.phase / TAU * N_PHASES) % N_PHASES
        img = vic.frames_r[idx] if vic.facing > 0 else vic.frames_l[idx]
        self.corpses.append(Halves(img, vic.pos))
        vic.remove = True
        att.hunger = 0.0
        att.eat_pause = 0.6
        att.cool["hunt"] = self.t + random.uniform(35, 65)
        mid = V2(vic.pos)
        self.particles.append(Sparkle(mid.x, mid.y))
        self.particles.append(Ripple(mid.x))
        for _ in range(7):
            self.particles.append(Bubble(mid.x + random.uniform(-14, 14), mid.y + random.uniform(-10, 10)))
        self.murk = min(1.0, self.murk + 0.02)
        # every other fish sheds a few tears; the nearby ones scatter
        for f in self.fish:
            if f is att or f is vic or f.gone() or f.g.get("mean"):
                continue
            f.cry_t = max(f.cry_t, random.uniform(1.2, 2.2))
            if f.state != "suck" and f.pos.distance_to(mid) < 520 \
                    and random.random() < 0.5 + f.traits["timid"] * 0.5:
                f.set_state("flee", random.uniform(1.5, 3.0))
                f.threat = None
                f.threat_pos = V2(mid)
        self.dirty = True

    def nip(self, att, vic):
        dmg = random.uniform(3, 8)
        vic.health -= dmg
        self.rel_add(att, vic, -0.15)
        mid = (att.pos + vic.pos) / 2
        self.particles.append(Sparkle(mid.x, mid.y))
        if vic.health <= 0:
            vic.die(self)
        else:
            vic.set_state("flee", 2.2, threat=att)
            away = vic.pos - att.pos
            if away.length_squared() > 1:
                vic.vel = away.normalize() * vic.burst
        self.dirty = True

    def resolve_duel(self, a, b):
        def score(f):
            return f.size * 0.5 + f.traits["agg"] * 40 + f.health * 0.3 + random.uniform(0, 30)
        winner, loser = (a, b) if score(a) >= score(b) else (b, a)
        a.partner = b.partner = None
        if a.g.get("mean") and b.g.get("mean"):
            # mean-on-mean: winner takes all, and doubles
            self.bite(winner, loser)
            winner.grow(2)
            for _ in range(6):
                self.particles.append(Sparkle(winner.pos.x + random.uniform(-30, 30),
                                              winner.pos.y + random.uniform(-20, 20)))
            winner.cool["hunt"] = self.t + random.uniform(45, 80)
            winner.set_state("wander", 1)
            return
        self.rel_add(a, b, -0.22)
        self.nip(winner, loser)
        winner.cool["agg"] = self.t + random.uniform(18, 40)
        winner.cool["duel"] = self.t + random.uniform(25, 60)
        loser.cool["duel"] = self.t + random.uniform(40, 80)
        winner.set_state("wander", 1)

    def nearest_pellet(self, pos, prefer_resting=False):
        best, bd = None, 1e18
        for p in self.pellets:
            if p.eaten or p.pos.y < self.waterline:
                continue
            d = pos.distance_squared_to(p.pos)
            if prefer_resting and p.resting:
                d *= 0.25
            if d < bd:
                best, bd = p, d
        return best

    def announce(self, pos, kind="tap", newcomer=None):
        chance = {"tap": 0.8, "object": 0.5, "newfish": 0.55}[kind]
        for f in self.fish:
            if f.gone() or not f.calm() or f is newcomer:
                continue
            if f.pos.distance_to(pos) > 700:
                continue
            if random.random() < f.traits["cur"] * chance:
                pt = pos + V2(random.uniform(-50, 50), random.uniform(-30, 30))
                f.set_state("investigate", random.uniform(2.0, 4.0), point=pt)
                if newcomer is not None:
                    self.rel_add(f, newcomer, 0.06)

    # ---------------- the social brain (every ~0.6 s) ----------------
    def social_tick(self):
        t = self.t
        alive = [f for f in self.fish if not f.gone()]
        # hungry fish notice food
        for f in alive:
            hthr = 0.42 - f.traits["greed"] * 0.22
            if f.hunger > hthr and f.state in CALM_STATES | {"circle"}:
                p = self.nearest_pellet(f.pos, prefer_resting=(f.arch in ("catfish", "pleco")))
                if p is not None:
                    if f.partner and f.partner.partner is f:
                        f.partner.partner = None
                    f.set_state("seek_food", 9, target=p)
        # friendships build on proximity (mean fish have no friends)
        for i, f in enumerate(alive):
            if not f.calm() or f.g.get("mean"):
                continue
            for f2 in alive[i + 1:]:
                if not f2.calm() or f2.g.get("mean"):
                    continue
                if f.pos.distance_to(f2.pos) < 140:
                    self.rel_add(f, f2, 0.010 * (f.traits["soc"] + f2.traits["soc"]))
        # impulses
        for f in alive:
            if f.state not in CALM_STATES:
                continue
            tr = f.traits
            if f.g.get("mean"):
                # mean fish don't make friends; they hunt
                if t > f.cool.get("hunt", 0) and self.fights_active() < MAX_FIGHTS + 2:
                    others = [v for v in alive if v is not f and v.calm()]
                    means = [v for v in others if v.g.get("mean")]
                    prey = [v for v in others if not v.g.get("mean")]
                    small = [v for v in prey if v.size <= f.size * 1.5] or prey
                    if means and (not small or random.random() < 0.3):
                        m = random.choice(means)
                        dur = random.uniform(2.5, 4.0)
                        f.set_state("display", dur, partner=m)
                        m.set_state("display", dur, partner=f)
                        f.partner, m.partner = m, f
                    elif small:
                        f.set_state("chase", 6, target=random.choice(small))
                continue
            if f.arch == "pleco" and f.state in ("wander", "rest") and self.algae \
                    and random.random() < 0.45:
                spot = max(self.algae, key=lambda a: a["r"])
                f.set_state("to_glass", 25, target=spot)
                continue
            r = random.random()
            # aggression
            if r < tr["agg"] * 0.09 and t > f.cool.get("agg", 0) and self.fights_active() < MAX_FIGHTS:
                victims = [v for v in alive
                           if v is not f and v.calm() and v.size < f.size * 1.7
                           and f.pos.distance_to(v.pos) < 520]
                rivals = [v for v in victims if self.rel(f, v) < RIVAL_AFF]
                pool = rivals or (victims if tr["agg"] > 0.62 else [])
                if pool:
                    v = random.choice(pool)
                    if (v.traits["agg"] > 0.5 and self.rel(f, v) < 0.05
                            and abs(v.size - f.size) < f.size * 0.4
                            and t > f.cool.get("duel", 0) and t > v.cool.get("duel", 0)):
                        dur = random.uniform(2.2, 3.6)
                        f.set_state("display", dur, partner=v)
                        v.set_state("display", dur, partner=f)
                        f.partner, v.partner = v, f
                    else:
                        f.set_state("chase", 3.5, target=v)
                continue
            # friendship: school with or circle a friend
            if r < tr["soc"] * 0.12:
                friends = [v for v in alive if v is not f and v.calm() and self.rel(f, v) > FRIEND_AFF
                           and f.pos.distance_to(v.pos) < 620]
                if friends:
                    buddy = max(friends, key=lambda v: self.rel(f, v))
                    if self.rel(f, buddy) > 0.7 and random.random() < 0.3:
                        dur = random.uniform(2.2, 3.2)
                        ctr = (f.pos + buddy.pos) / 2
                        f.set_state("circle", dur, partner=buddy, point=ctr)
                        buddy.set_state("circle", dur, partner=f, point=ctr)
                        f.partner, buddy.partner = buddy, f
                    else:
                        f.set_state("school", random.uniform(5, 10), target=buddy)
                    continue
            # play with rocks
            if r < tr["play"] * 0.08 and self.rocks and t > f.cool.get("play", 0):
                f.set_state("play", random.uniform(3.5, 6.5), rock=random.choice(self.rocks))
                continue
            # visit a clam
            if r < tr["cur"] * 0.035 and self.clams:
                c = random.choice(self.clams)
                mx, my = c.mouth(self)
                f.set_state("investigate", random.uniform(2, 4), point=(mx, my - 40))
                continue
            # beg at the surface when hungry and there's nothing to eat
            if f.hunger > 0.7 and not self.pellets and r < 0.28:
                f.set_state("beg", random.uniform(4, 7))
                continue
            # rest
            if f.state == "wander" and r < (1 - tr["energy"]) * 0.10:
                f.set_state("rest", random.uniform(4, 9))

    # ---------------- update ----------------
    def update(self, dt):
        self.t += dt
        # sand animates toward target
        if abs(self.sand_cur - self.sand_frac) > 0.001:
            rising = self.sand_frac > self.sand_cur
            step = 0.22 * dt
            self.sand_cur += clamp(self.sand_frac - self.sand_cur, -step, step)
            if rising and random.random() < dt * 30:
                self.particles.append(Grain(random.uniform(self.water.left + 10, self.water.right - 10),
                                            self.waterline + 4))
            elif not rising and random.random() < dt * 10:
                x = random.uniform(self.water.left + 20, self.water.right - 20)
                self.particles.append(Puff(x, self.sand_top(x) - 4, dim(SAND_COLOR, 0.85)))

        for c in self.clams:
            c.update(dt, self)

        # pellets: sink, get eaten
        for p in self.pellets:
            if p.eaten:
                continue
            if p.pos.y > self.waterline:
                # clams filter-feed
                for c in self.clams:
                    if c.open > 0.45:
                        mx, my = c.mouth(self)
                        if abs(p.pos.x - mx) < c.size * 0.5 and abs(p.pos.y - my) < c.size * 0.5:
                            p.eaten = True
                            c.snap_t = 1.2
                            self.particles.append(Puff(mx, my))
                            break
                if p.eaten:
                    continue
                # fish eat: targeted or bumped into
                for f in self.fish:
                    if f.gone():
                        continue
                    reach = max(10, f.size * 0.14) + p.r * 2
                    near_mouth = f.mouth_pos().distance_to(p.pos) < reach
                    bumped = f.pos.distance_to(p.pos) < f.size * 0.18
                    if (f.state == "seek_food" and near_mouth) or bumped:
                        p.eaten = True
                        f.hunger = max(0.0, f.hunger - EAT_RELIEF)
                        f.health = min(100.0, f.health + 1.2)
                        f.eat_pause = 0.25
                        if random.random() < 0.3:   # digestion is prompt
                            f.next_poop = min(f.next_poop, random.uniform(15, 50))
                        self.particles.append(Puff(p.pos.x, p.pos.y))
                        break
        self.pellets = [p for p in self.pellets if p.update(dt, self)]

        for f in list(self.fish):
            f.update(dt, self)
        removed = [f for f in self.fish if f.remove]
        if removed:
            gone_ids = {f.id for f in removed}
            self.fish = [f for f in self.fish if not f.remove]
            self.rels = {k: v for k, v in self.rels.items()
                         if not (set(map(int, k.split("-"))) & gone_ids)}
            self.dirty = True

        self.particles = [p for p in self.particles if p.update(dt, self)]
        if len(self.particles) > 260:
            self.particles = self.particles[-260:]
        self.corpses = [c for c in self.corpses if c.update(dt, self)]

        # algae creeps across the glass
        for a in self.algae:
            if a["r"] < a["max_r"]:
                a["r"] = min(a["max_r"], a["r"] + a["rate"] * dt)
        self.algae_next -= dt
        if self.algae_next <= 0:
            if len(self.algae) < MAX_ALGAE:
                self.spawn_algae()
            self.algae_next = random.uniform(12, 26)

        # ambient bubbles: airstone + occasional fish bubble
        self.airstone_next -= dt
        if self.airstone_next <= 0:
            self.particles.append(Bubble(self.airstone_x + random.uniform(-4, 4),
                                         self.sand_top(self.airstone_x) - 6))
            self.airstone_next = random.uniform(0.35, 1.1)
        if self.fish and random.random() < dt * 0.5:
            f = random.choice(self.fish)
            if not f.gone():
                self.particles.append(Bubble(f.mouth_pos().x, f.pos.y - 4, r=random.uniform(1.2, 2.4)))

        self.murk = max(0.0, self.murk - 0.0045 * dt)
        self.pills = [(f, u) for f, u in self.pills if self.t < u and not f.remove]

        self.social_timer -= dt
        if self.social_timer <= 0:
            self.social_tick()
            self.social_timer = 0.6

        self.save_timer -= dt
        if self.save_timer <= 0:
            self.save()
            self.save_timer = SAVE_EVERY_S

    # ---------------- clicks ----------------
    def click(self, pos):
        pos = V2(pos)
        if not self.water.collidepoint(pos):
            return
        # a fish?
        for f in sorted(self.fish, key=lambda f: f.pos.distance_to(pos)):
            if f.gone():
                continue
            if f.pos.distance_to(pos) < max(30, f.size * 0.55):
                self.pills.append((f, self.t + 3.0))
                away = f.pos - pos
                if away.length_squared() < 1:
                    away = V2(1, 0)
                f.vel = away.normalize() * f.burst * 0.9
                if f.state in CALM_STATES:
                    f.set_state("startle", 0.5)
                return
        # a clam?
        for c in self.clams:
            hx, hy = c.hinge(self)
            if abs(pos.x - hx) < c.size and abs(pos.y - hy + c.size * 0.4) < c.size:
                c.snap()
                return
        # a rock?
        for r in self.rocks:
            rx, ry = r.center(self)
            if abs(pos.x - rx) < r.w * 0.5 and ry - r.h < pos.y < ry:
                self.particles.append(Pebble(rx + random.uniform(-6, 6), ry - r.h))
                return
        # open water: ripple + curious fish
        if pos.y < self.waterline + 40:
            self.particles.append(Ripple(pos.x))
        for _ in range(3):
            self.particles.append(Bubble(pos.x + random.uniform(-8, 8), pos.y + random.uniform(-6, 6),
                                         r=random.uniform(1.2, 2.6)))
        self.announce(pos, kind="tap")

    def right_click(self, pos):
        """Design mode: remove exactly the fish, clam, or rock under the cursor."""
        pos = V2(pos)
        if not self.water.collidepoint(pos):
            return
        for f in sorted(self.fish, key=lambda f: f.pos.distance_to(pos)):
            if f.remove or f.state == "netted":
                continue
            if f.pos.distance_to(pos) < max(30, f.size * 0.55):
                self.remove_fish(pick=f)
                return
        for c in self.clams:
            hx, hy = c.hinge(self)
            if abs(pos.x - hx) < c.size and abs(pos.y - hy + c.size * 0.4) < c.size:
                self.remove_clam(clam=c)
                return
        for r in self.rocks:
            rx, ry = r.center(self)
            if abs(pos.x - rx) < r.w * 0.5 and ry - r.h < pos.y < ry:
                self.remove_rock(rock=r)
                return

    # ---------------- drawing ----------------
    def draw(self, screen):
        t = self.t
        prev_clip = screen.get_clip()
        screen.set_clip(self.water)
        screen.blit(self.water_bg, self.water.topleft)
        for i in range(3):
            x = self.water.left + self.water.w * (0.2 + 0.3 * i) \
                + math.sin(t * (0.05 + 0.02 * i) + i * 2.1) * self.water.w * 0.06 \
                - self.ray_surf.get_width() / 2
            screen.blit(self.ray_surf, (int(x), self.water.top - 30), special_flags=pygame.BLEND_RGB_ADD)
        self.draw_sand(screen)
        for r in self.rocks:
            if not r.front:
                r.draw(screen, self)
        for c in self.clams:
            c.draw(screen, self)
        for p in self.pellets:
            p.draw(screen, self)
        for f in self.fish:
            if f.state != "suck":
                f.draw(screen, self)
        for c in self.corpses:
            c.draw(screen, self)
        for p in self.particles:
            p.draw(screen, self)
        for r in self.rocks:
            if r.front:
                r.draw(screen, self)
        if self.murk > 0.02:
            self.murk_surf.set_alpha(int(self.murk * 46))
            screen.blit(self.murk_surf, (self.water.left, self.waterline))
        # algae on the front glass, and plecos rasping at it
        self.draw_algae(screen)
        for f in self.fish:
            if f.state == "suck":
                f.draw(screen, self)
        # air gap + waterline
        pygame.draw.rect(screen, (8, 11, 15),
                         (self.water.left, self.water.top, self.water.w, self.waterline - self.water.top))
        pts = [(x, self.waterline + math.sin(x * 0.02 + t * 1.8) * 1.8)
               for x in range(self.water.left, self.water.right + 12, 12)]
        pygame.draw.lines(screen, (110, 160, 185), False, pts, 2)
        pygame.draw.lines(screen, (60, 95, 115), False, [(x, y + 3) for x, y in pts], 1)
        screen.blit(self.streaks, self.water.topleft)
        screen.set_clip(prev_clip)
        # glass frame
        pygame.draw.rect(screen, (46, 56, 64), self.tank, self.glass)
        pygame.draw.rect(screen, (96, 116, 128), self.tank, 1)
        pygame.draw.rect(screen, (118, 142, 155), self.tank.inflate(-2 * self.glass + 2, -2 * self.glass + 2), 1)
        # plaque: bobbing rainbow letters with fish bookends
        px0 = self.tank.centerx - self.plaque_w / 2
        py = self.tank.bottom + 4
        for gs, xo, ci in self.plaque:
            bob = math.sin(t * 1.6 + ci * 0.7) * 2.2
            screen.blit(gs, (int(px0 + xo), int(py + bob)))
        fy = py + self.plaque_h * 0.22
        screen.blit(self.plaque_fish_l,
                    (int(px0 - self.plaque_fish_l.get_width() - 16), int(fy + math.sin(t * 1.3) * 2)))
        screen.blit(self.plaque_fish_r,
                    (int(px0 + self.plaque_w + 16), int(fy + math.sin(t * 1.3 + 1.5) * 2)))
        # name pills
        for f, until in self.pills:
            self.draw_pill(screen, f, until)

    def draw_algae(self, screen):
        for a in self.algae:
            ri = int(a["r"])
            if ri < 2:
                continue
            if a.get("surf_r") != ri:   # re-render only when it has visibly grown
                d = ri * 2
                surf = pygame.Surface((d * 2, d * 2), pygame.SRCALPHA)
                for dxf, dyf, rf in a["blobs"]:
                    pygame.draw.circle(surf, (66, 148, 60, 118),
                                       (int(d + dxf * ri), int(d + dyf * ri)), max(1, int(rf * ri)))
                for dxf, dyf, rf in a["blobs"][:3]:
                    pygame.draw.circle(surf, (46, 108, 44, 95),
                                       (int(d + dxf * ri * 0.6), int(d + dyf * ri * 0.6)),
                                       max(1, int(rf * ri * 0.45)))
                for dxf, dyf, rf in a["blobs"][1:4]:   # bright flecks so it reads as algae
                    pygame.draw.circle(surf, (110, 190, 92, 130),
                                       (int(d + dxf * ri * 0.8), int(d - abs(dyf) * ri * 0.7)),
                                       max(1, int(rf * ri * 0.22)))
                a["surf"] = surf
                a["surf_r"] = ri
            s_ = a["surf"]
            screen.blit(s_, (int(a["x"] - s_.get_width() / 2), int(a["y"] - s_.get_height() / 2)))

    def draw_sand(self, screen):
        if self.sand_cur <= 0.015:
            return
        step = 16
        top_pts = [(x, self.sand_top(x)) for x in range(self.water.left, self.water.right + step, step)]
        poly = top_pts + [(self.water.right, self.water.bottom), (self.water.left, self.water.bottom)]
        pygame.draw.polygon(screen, SAND_COLOR, [(int(x), int(y)) for x, y in poly])
        pygame.draw.lines(screen, dim(SAND_COLOR, 1.14), False,
                          [(int(x), int(y)) for x, y in top_pts], 2)
        for xf, df, sh in self.speckles:
            x = self.water.left + xf * self.water.w
            st = self.sand_top(x)
            depth = self.water.bottom - st
            if depth < 6:
                continue
            y = st + 3 + df * (depth - 4)
            screen.fill(dim(SAND_COLOR, sh), (int(x), int(y), 2, 2))

    def draw_pill(self, screen, f, until):
        fade = clamp((until - self.t) / 0.4, 0, 1)
        txt = font(26).render(f.name, True, (235, 240, 245))
        pw, ph = txt.get_width() + 18, txt.get_height() + 8
        pill = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(pill, (10, 14, 18, 185), (0, 0, pw, ph), border_radius=ph // 2)
        pill.blit(txt, (9, 4))
        pill.set_alpha(int(255 * fade))
        x = clamp(f.pos.x - pw / 2, self.water.left + 6, self.water.right - pw - 6)
        y = clamp(f.pos.y - f.fh / 2 - ph - 8, self.water.top + 4, self.water.bottom - ph)
        screen.blit(pill, (int(x), int(y)))

    # ---------------- persistence ----------------
    def to_dict(self):
        return {
            "version": 1,
            "saved_at": time.time(),
            "tank_seed": self.seed,
            "next_id": self.next_id,
            "sand_frac": round(self.sand_frac, 4),
            "murk": round(self.murk, 4),
            "fish_added": self.fish_added,
            "algae": [{"xf": round((a["x"] - self.water.left) / self.water.w, 4),
                       "yf": round((a["y"] - self.water.top) / self.water.h, 4),
                       "r": round(a["r"], 1), "max_r": round(a["max_r"], 1),
                       "rate": a["rate"], "seed": a["seed"]} for a in self.algae],
            "fish": [f.to_dict(self) for f in self.fish if not f.gone()],
            "rels": {k: round(v, 3) for k, v in self.rels.items()},
            "rocks": [{"xf": round(r.x_frac, 4), "size": round(r.size, 1),
                       "seed": r.seed, "front": r.front} for r in self.rocks],
            "clams": [{"xf": round(c.x_frac, 4), "size": round(c.size, 1),
                       "seed": c.seed} for c in self.clams],
        }

    def from_dict(self, d):
        self.seed = d["tank_seed"]
        self.next_id = d["next_id"]
        self.sand_frac = self.sand_cur = d["sand_frac"]
        self.murk = d.get("murk", 0.0)
        self.fish_added = d.get("fish_added", d["next_id"] - 1)
        for ad in d.get("algae", []):
            self.algae.append(self._make_spot(
                self.water.left + ad["xf"] * self.water.w,
                self.water.top + ad["yf"] * self.water.h,
                ad["r"], ad["max_r"], max(ad["rate"], 0.15), ad["seed"]))
        self.seed_algae(3)   # older tanks get visible growth too
        self.rels = dict(d.get("rels", {}))
        elapsed = max(0.0, time.time() - d.get("saved_at", time.time()))
        extra_hunger = min(elapsed / HUNGER_FULL_S * 0.5, 1.0)
        for rd in d.get("rocks", []):
            self.rocks.append(Rock(rd["xf"], rd["size"], rd["seed"], rd["front"]))
        for cd in d.get("clams", []):
            self.clams.append(Clam(cd["xf"], cd["size"], cd["seed"]))
        for fd in d.get("fish", []):
            pos = V2(self.water.left + fd["xf"] * self.water.w,
                     self.water.top + fd["yf"] * self.water.h)
            pos.x = clamp(pos.x, self.water.left + 30, self.water.right - 30)
            pos.y = clamp(pos.y, self.waterline + 30, self.water.bottom - 40)
            f = Fish(self, fd["genome"], fd["name"], fd["id"],
                     hunger=min(OFFLINE_HUNGER_CAP, fd["hunger"] + extra_hunger),
                     health=fd["health"], age=fd["age"] + min(elapsed, 86400 * 2), pos=pos)
            self.fish.append(f)

    def save(self):
        try:
            tmp = self.save_path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(self.to_dict(), f)
            os.replace(tmp, self.save_path)
            self.dirty = False
        except Exception as e:
            print(f"save failed: {e}", file=sys.stderr)


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------

ICON = (208, 218, 228)
ICON_DIM = (95, 104, 114)


def icon_fish(s, r, col):
    cx, cy = r.centerx + r.w * 0.04, r.centery
    bw, bh = r.w * 0.42, r.h * 0.26
    pygame.draw.ellipse(s, col, (cx - bw / 2, cy - bh / 2, bw, bh))
    pygame.draw.polygon(s, col, [(cx - bw * 0.48, cy), (cx - bw * 0.78, cy - bh * 0.55),
                                 (cx - bw * 0.78, cy + bh * 0.55)])
    pygame.draw.circle(s, (30, 36, 44), (int(cx + bw * 0.26), int(cy - bh * 0.12)), max(2, int(bh * 0.14)))


def icon_rock(s, r, col):
    cx, cy = r.centerx, r.centery + r.h * 0.06
    w, h = r.w * 0.46, r.h * 0.30
    pygame.draw.polygon(s, col, [(cx - w * 0.5, cy + h * 0.5), (cx - w * 0.42, cy - h * 0.2),
                                 (cx - w * 0.12, cy - h * 0.55), (cx + w * 0.3, cy - h * 0.4),
                                 (cx + w * 0.5, cy + h * 0.1), (cx + w * 0.38, cy + h * 0.5)])


def icon_sand(s, r, col, up):
    cx, cy = r.centerx, r.centery + r.h * 0.16
    w = r.w * 0.5
    pygame.draw.arc(s, col, (cx - w * 0.55, cy - r.h * 0.10, w * 0.62, r.h * 0.22), 0, math.pi, 3)
    pygame.draw.arc(s, col, (cx - w * 0.05, cy - r.h * 0.10, w * 0.62, r.h * 0.22), 0, math.pi, 3)
    pygame.draw.line(s, col, (cx - w * 0.55, cy + r.h * 0.012), (cx + w * 0.57, cy + r.h * 0.012), 3)
    ax, ay = cx, cy - r.h * 0.30
    d = 1 if up else -1
    pygame.draw.line(s, col, (ax, ay + d * r.h * 0.09), (ax, ay - d * r.h * 0.09), 3)
    pygame.draw.polygon(s, col, [(ax - 7, ay - d * r.h * 0.04), (ax + 7, ay - d * r.h * 0.04),
                                 (ax, ay - d * r.h * 0.14)])


def icon_clam(s, r, col):
    cx, cy = r.centerx, r.centery + r.h * 0.12
    w = r.w * 0.44
    pygame.draw.polygon(s, col, [(cx, cy), (cx - w * 0.5, cy - r.h * 0.06), (cx - w * 0.36, cy - r.h * 0.22),
                                 (cx, cy - r.h * 0.30), (cx + w * 0.36, cy - r.h * 0.22),
                                 (cx + w * 0.5, cy - r.h * 0.06)])
    for a in (-0.5, 0, 0.5):
        pygame.draw.line(s, (30, 36, 44), (cx, cy),
                         (cx + math.sin(a) * w * 0.42, cy - r.h * 0.26 * math.cos(a) - r.h * 0.02), 2)
    pygame.draw.line(s, col, (cx - w * 0.5, cy + r.h * 0.05), (cx + w * 0.5, cy + r.h * 0.05), 2)


def icon_food(s, r, col):
    cx, cy = r.centerx, r.centery - r.h * 0.06
    w, h = r.w * 0.26, r.h * 0.34
    can = pygame.Rect(0, 0, w, h)
    can.center = (cx, cy)
    pts = [(can.left, can.top), (can.right, can.top), (can.right + 3, can.bottom), (can.left - 3, can.bottom)]
    pts = [(x - cx, y - cy) for x, y in pts]
    a = math.radians(-24)
    pts = [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in pts]
    pygame.draw.polygon(s, col, pts)
    lidc = ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
    pygame.draw.circle(s, (200, 90, 70), (int(lidc[0]), int(lidc[1])), int(w * 0.42))
    for i, (dx, dy) in enumerate([(-14, 16), (-4, 24), (-18, 30), (-8, 38)]):
        pygame.draw.circle(s, col, (int(cx + dx), int(cy + dy)), 2)


class Button:
    def __init__(self, icon, label, badge, action, enabled_fn, accent=False):
        self.icon = icon
        self.label = label
        self.badge = badge
        self.action = action
        self.enabled_fn = enabled_fn
        self.accent = accent
        self.rect = pygame.Rect(0, 0, 10, 10)
        self.press_t = -9

    def draw(self, s, t):
        en = self.enabled_fn()
        r = self.rect
        pressed = t - self.press_t < 0.14
        if self.accent:
            base = (86, 58, 30) if not pressed else (128, 88, 46)
            border = (196, 140, 66)
        else:
            base = (30, 38, 46) if not pressed else (58, 74, 88)
            border = (72, 90, 104)
        if not en:
            base = (20, 24, 29)
            border = (42, 50, 58)
        rad = max(10, r.w // 6)
        pygame.draw.rect(s, base, r, border_radius=rad)
        pygame.draw.rect(s, border, r, 2, border_radius=rad)
        col = ICON if en else ICON_DIM
        icon_r = pygame.Rect(r.x, r.y, r.w, r.h - 18)
        self.icon(s, icon_r, col)
        lbl = font(16).render(self.label, True, (128, 138, 148) if en else (70, 78, 86))
        s.blit(lbl, (r.centerx - lbl.get_width() // 2, r.bottom - 19))
        if self.badge:
            br = max(9, r.w // 8)
            bx, by = r.right - br - 5, r.top + br + 5
            bcol = (72, 160, 82) if self.badge == "+" else (196, 84, 72)
            if not en:
                bcol = dim(bcol, 0.45)
            pygame.draw.circle(s, bcol, (bx, by), br)
            pygame.draw.line(s, (245, 248, 250), (bx - br * 0.45, by), (bx + br * 0.45, by), 3)
            if self.badge == "+":
                pygame.draw.line(s, (245, 248, 250), (bx, by - br * 0.45), (bx, by + br * 0.45), 3)


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------

class App:
    def __init__(self, windowed=False, size=(1280, 800), seed=None, save_path=None, reset=False, debug=False):
        pygame.init()
        pygame.display.set_caption("Max's Aquarium")
        if windowed:
            self.screen = pygame.display.set_mode(size)
        else:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        if save_path is None:
            save_path = Path(__file__).resolve().parent / "aquarium_save.json"
        self.aq = Aquarium(self.screen.get_size(), save_path, seed=seed, reset=reset)
        self.clock = pygame.time.Clock()
        self.debug = debug
        self.running = True
        self.held = None
        self.held_t = 0.0
        self.mouse_idle = 0.0
        self.frame_n = 0
        self.build_ui()

    def build_ui(self):
        aq = self.aq
        self.buttons = [
            Button(icon_fish, "FISH", "+", aq.add_fish,
                   lambda: len([f for f in aq.fish if not f.gone()]) < MAX_FISH),
            Button(icon_fish, "FISH", "-", aq.remove_fish,
                   lambda: any(not f.gone() or f.state == "dead" for f in aq.fish)),
            Button(icon_rock, "ROCK", "+", aq.add_rock, lambda: len(aq.rocks) < MAX_ROCKS),
            Button(icon_rock, "ROCK", "-", aq.remove_rock, lambda: len(aq.rocks) > 0),
            Button(lambda s, r, c: icon_sand(s, r, c, True), "SAND", "+", aq.sand_up,
                   lambda: aq.sand_frac < 0.999),
            Button(lambda s, r, c: icon_sand(s, r, c, False), "SAND", "-", aq.sand_down,
                   lambda: aq.sand_frac > 0.001),
            Button(icon_clam, "CLAM", "+", aq.add_clam, lambda: len(aq.clams) < MAX_CLAMS),
            Button(icon_clam, "CLAM", "-", aq.remove_clam, lambda: len(aq.clams) > 0),
            Button(icon_food, "FEED", None, aq.feed,
                   lambda: len(aq.pellets) < MAX_PELLETS, accent=True),
        ]
        n = len(self.buttons)
        bh = self.aq.bar_h
        size = min(int(bh * 0.82), (self.screen.get_width() - 40) // n - 14)
        gap = max(10, size // 6)
        groups_extra = gap  # extra space before FEED
        total = n * size + (n - 1) * gap + groups_extra
        x = (self.screen.get_width() - total) // 2
        y = self.aq.tank.bottom + (self.screen.get_height() - self.aq.tank.bottom - size) * 0.62
        for i, b in enumerate(self.buttons):
            extra = groups_extra if i == n - 1 else 0
            b.rect = pygame.Rect(int(x + i * (size + gap) + extra), int(y), size, size)

    # ---------------- events ----------------
    def handle_events(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    self.running = False
                elif ev.key == pygame.K_SPACE:
                    self.aq.feed()
                elif ev.key == pygame.K_d:
                    self.debug = not self.debug
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                self.mouse_idle = 0
                hit = None
                for b in self.buttons:
                    if b.rect.collidepoint(ev.pos):
                        hit = b
                        break
                if hit is not None:
                    if hit.enabled_fn():
                        hit.press_t = self.aq.t
                        hit.action()
                    self.held = hit
                    self.held_t = self.aq.t + 0.5
                else:
                    self.aq.click(ev.pos)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3:
                self.mouse_idle = 0
                self.aq.right_click(ev.pos)
            elif ev.type == pygame.MOUSEBUTTONUP:
                self.held = None
            elif ev.type == pygame.MOUSEMOTION:
                self.mouse_idle = 0

    def update_held(self):
        if self.held is None:
            return
        if not pygame.mouse.get_pressed()[0]:
            self.held = None
            return
        if self.aq.t >= self.held_t and self.held.rect.collidepoint(pygame.mouse.get_pos()):
            if self.held.enabled_fn():
                self.held.press_t = self.aq.t
                self.held.action()
            self.held_t = self.aq.t + 0.33

    # ---------------- main loop ----------------
    def run(self, frames=None, shot=None, on_frame=None):
        try:
            while self.running:
                dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
                self.handle_events()
                self.update_held()
                self.mouse_idle += dt
                pygame.mouse.set_visible(self.mouse_idle < 4.0)
                self.aq.update(dt)
                self.draw()
                pygame.display.flip()
                self.frame_n += 1
                if on_frame:
                    on_frame(self.frame_n, self)
                if frames is not None and self.frame_n >= frames:
                    if shot:
                        pygame.image.save(self.screen, shot)
                    self.running = False
        finally:
            self.aq.save()
            pygame.mouse.set_visible(True)
            _FONTS.clear()
            pygame.quit()

    def screenshot(self, path):
        pygame.image.save(self.screen, path)

    def draw(self):
        self.screen.fill((0, 0, 0))
        self.aq.draw(self.screen)
        for b in self.buttons:
            b.draw(self.screen, self.aq.t)
        if self.debug:
            aq = self.aq
            alive = len([f for f in aq.fish if not f.gone()])
            txt = (f"{self.clock.get_fps():4.0f} fps  fish {alive}  pellets {len(aq.pellets)}  "
                   f"particles {len(aq.particles)}  murk {aq.murk:.2f}  "
                   f"fights {aq.fights_active()}")
            s = font(20).render(txt, True, (120, 200, 120))
            self.screen.blit(s, (aq.tank.left + 8, 4))


# ----------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Max's Aquarium")
    ap.add_argument("--windowed", action="store_true", help="1280x800 window instead of fullscreen")
    ap.add_argument("--reset", action="store_true", help="start a brand-new tank (ignores the save)")
    ap.add_argument("--seed", type=int, default=None, help="tank seed for a fresh tank")
    ap.add_argument("--debug", action="store_true", help="show fps/entity overlay")
    ap.add_argument("--save-file", default=None, help="alternate save file path")
    ap.add_argument("--frames", type=int, default=None, help="(dev) run N frames then exit")
    ap.add_argument("--shot", default=None, help="(dev) save a screenshot on exit with --frames")
    args = ap.parse_args(argv)
    app = App(windowed=args.windowed, seed=args.seed, save_path=args.save_file,
              reset=args.reset, debug=args.debug)
    app.run(frames=args.frames, shot=args.shot)


if __name__ == "__main__":
    main()
