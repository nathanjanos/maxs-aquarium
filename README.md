# Max's Aquarium

A fullscreen virtual aquarium for Max. A black gallery wall, a glass tank,
and a growing cast of colorful fish — every one procedurally generated with
its own shape, colors, name, and personality. They make friends, squabble,
school together, play with the rocks, beg at the surface when hungry, and
clams on the sand slowly breathe in and out.

The tank is persistent: quit and relaunch, and the same fish (and their
friendships) are still there.

## Setup

```
python3 -m venv .venv
.venv/bin/pip install pygame-ce
```

## Run

```
.venv/bin/python3 aquarium.py              # fullscreen
.venv/bin/python3 aquarium.py --windowed   # 1280x800 window
.venv/bin/python3 aquarium.py --reset      # start a brand-new tank
```

## Playing

Big buttons along the bottom:

- **FISH + / −** — a new random fish drops in with a splash / the net
  scoops one out (it takes any floaters first)
- **ROCK + / −** — add or remove rocks (fish hide behind and play with them)
- **SAND + / −** — raise or lower the sand bed
- **CLAM + / −** — add or remove clams (they filter-feed and snap shut if
  you startle them)
- **FEED** — sprinkle flakes on the surface (SPACE works too)

Tap the water and curious fish come investigate. Tap a fish to see its
name. Tap a clam to make it snap. Tap a rock to flick a pebble.

**Right-click** (two-finger click on the trackpad) a fish, rock, or clam
to take exactly that one out — handy for designing the tank.

## Beware the mean fish

Every 10th fish that joins the tank is a **mean fish** — you'll know it by
the red eyes. Mean fish patrol fast, and they bite other fish clean in
half (the halves float sadly to the surface while every other fish sheds
a few tears). If two mean fish go after each other they fight it out, and
the winner comes out twice as big and twice as fast. The net (or a
right-click) works on mean fish too, if the reign of terror needs ending.

## Algae and the plecostomus

Green algae spots grow on the front glass (a fresh tank already has a
few patches going). Plecostomus catfish —
which show up more often in an algae-covered tank — latch onto the glass
belly-first, sucker mouth working, and rasp the spots clean.

Fish really do get hungry — feed them or they'll crowd the surface begging,
and a truly neglected fish will not make it. (Away from the keyboard the
tank is merciful: fish get hungry while the app is closed, but nothing ever
dies off-screen.) Overfeeding clouds the water, so go easy.

And yes — the fish poop: little white worms, proportional to the fish,
that squeeze out, sink to the sand, and dissolve. Max will notice.

**ESC** or **Q** quits; the tank saves itself.
