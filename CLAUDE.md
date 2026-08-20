# CLAUDE.md — Max's Aquarium

## What this project is

A fullscreen 2D virtual aquarium for Nathan's son Max (age 3–5): black
gallery background, glass tank, procedurally generated fish with
personalities, big icon-first buttons along the bottom. Fun but as
realistic as a 2D toy can be — including the full circle of life (fish can
starve or lose bad fights; they float up and fade away). Runs on macOS for
now; same stack as the weather-frame project.

## Files

- `aquarium.py` — the whole app (pygame-ce). `--windowed` for a 1280x800
  test window, `--reset` for a fresh tank, `--seed N`, `--debug` (fps/counts
  overlay, toggle with D at runtime), `--save-file PATH`, and dev flags
  `--frames N --shot PATH` (run N frames headless-friendly, screenshot,
  exit). Keys: SPACE feed, D debug, ESC/Q quit. Right-click removes the
  specific fish/rock/clam under the cursor (design mode); the − buttons
  remove floaters-first/newest.
- `aquarium_save.json` — persistent tank state (gitignored). Written
  atomically every 25 s and on quit.
- `.venv` — python3 + **pygame-ce** (NOT stock pygame: it has no wheels for
  Python 3.14 on macOS and fails to build; pygame-ce is the maintained fork,
  imports as `pygame`).

## Architecture (all in aquarium.py)

- Tunables live in the constants block at the top.
- **Genome** (`make_genome`): archetype (tetra/goldfish/tang/
  angel/betta/puffer/catfish/pleco/clown — clowns always orange with
  white "clownbars") → body proportions, tail type, fins, HSV-derived colors,
  pattern (bars/hstripe/spots/koi patches/twotone), personality traits
  (agg/soc/cur/play/greed/timid/energy — priors strongly species-typed,
  jitter ±0.10; puffers inflate ~25% when startled/fleeing), preferred
  depth zone. Pure JSON
  primitives so saved fish rebuild identically (`pseed` seeds detail RNG).
- **Sprites**: `render_fish_frame` draws each fish at 2x supersample and
  smoothscales down; N_PHASES=14 tail-sway frames pre-rendered per fish at
  spawn (plus flipped set). Runtime = frame pick + rotate (cached per fish).
  Translucent detail must be drawn onto empty overlay surfaces and blitted
  (pygame.draw writes alpha, it does not blend — direct translucent draws on
  the sprite punch holes).
- **Fish brain**: `Aquarium.social_tick` (every 0.6 s) hands out impulses
  (chase/duel/school/circle-a-friend/play-with-rock/investigate/rest/beg)
  weighted by traits; `Fish.steer` implements per-state steering with
  seek/arrive, wall avoidance, mild separation, and tetra boids. Pairwise
  affinity lives in `Aquarium.rels` ("minid-maxid" keys): proximity builds
  friendship, nips and duels destroy it; >0.45 = friends (school, circle),
  <-0.30 = rivals. Two bettas start at -0.45 by species.
- **Life/death**: hunger 0→1 in ~6 min, then a 4 min grace, then health
  drains (~13 min total to starve); losing fights costs health; health<30 =
  visibly weak (slow, droopy, faded). Dead fish float up belly-up, linger
  ~24 s, fade. Offline time only adds hunger (capped 0.95) — no off-screen
  death, by design.
- **Mean fish**: every `MEAN_EVERY`th (10th) fish added has `g["mean"]` —
  red eyes + angry brow, 1.5x speed, no friendships. They hunt on a
  cooldown (`cool["hunt"]`); catching a normal fish calls `Aquarium.bite`:
  the victim's current frame is split into a `Halves` corpse (tumbles to
  the surface, fades ~10 s), every non-mean fish gets `cry_t` (Tear
  particles) and nearby ones scatter. Mean-vs-mean duels reuse the display
  state; the loser is bitten, the winner `grow(2)`s (size and speed double,
  capped: mult ≤ 4, body ≤ 35% of water height — `rebuild_sprites`).
- **Pleco + algae**: algae spots grow on the front glass (`Aquarium.algae`,
  spawn ~20 s apart, growth 0.15-0.40 px/s, cap MAX_ALGAE; `seed_algae`
  guarantees 3 visible patches on fresh tanks AND loaded saves — algae is
  drawn over fish because it is on the viewer's glass); plecos take `to_glass` → `suck`
  states, drawn belly-first (`build_pleco_belly`) in the glass layer above
  the algae, shrinking spots as they eat. Sucking plecos can't be hunted. Every meal (algae seconds, pellets)
  feeds `Fish.feed_growth`: `g["fed"]` -> `g["mult"]` (PLECO_GROW per
  food unit), body capped at PLECO_MAX_FRAC (0.3) of tank width;
  sprites rebuild at ~5% size steps, giants drop to 8 anim frames.
- **Seaweed** (`Seaweed`, PLANT buttons, MAX_PLANTS=10): 1-3 tapered
  stalks with triangular leaf blades, per-stalk sine sway drawn each frame
  (no pre-render); 35% front layer; persisted like rocks. `sway_at(w, hfrac)`
  exposes the stalk offset for hitchhikers.
- **Seahorses**: custom sprite (`render_seahorse` — upright, tube snout,
  fluttering dorsal, curled tail; pitch damped to ±8°, half cruise). Pair
  for life via `g["mate"]` ids (persisted); pairs stay close, hitch side
  by side on seaweed (`hitch` state rides `sway_at`), and every ~4-8 min
  the lower-id dad gets `fry`: 15 tiny babies orbiting his belly for a
  few minutes (transient, not saved). Widows may re-pair. Excluded from
  mean rolls; hitched seahorses can't be hunted.
- **Anti-clump**: each fish keeps a position EMA + crowd timer; ~1 min of
  loitering near ≥2 neighbors triggers `Aquarium.scatter` — a dart away
  from the local centroid toward the far side of the tank (staggered
  per-fish limits so huddles pop one fish at a time).
- Algae/pleco gotchas (each cost a debug session): spots must spawn ABOVE
  the sand line and pleco spot-selection must filter unreachable ones
  (body clearance) or plecos hover at the sand forever; plecos must skip
  the hungry-pellet interrupt while algae exists or a fed tank keeps them
  off the glass permanently; one pleco per spot (`claimed_spots`) or they
  pile up. Name pills show "Name" + "(species)" — "(mean X)" in red.
- Pleco pacing gotcha (fixed once): cruise damp must scale with size
  (only giants lumber), floor clearance 0.10 like catfish, and `to_glass`
  skips top/floor wall-avoidance with a ≥60 px/s approach floor and
  size-scaled arrival radius — otherwise plecos never reach the glass.
- **World**: pellets sink, rest on sand, rot into `murk` (green haze that
  decays — overfeeding lesson); clams breathe on sines, snap when startled,
  filter-feed pellets; rocks pre-render seeded blob polygons (40% draw in
  front of fish, back rocks dimmed for depth; ~28% tall standing stones;
  sizes up to 300 capped at 35% of water height). Fish poop `Poop` worms:
  white, fish-proportional, extrude attached to the vent, then sink and
  dissolve; sand level animates toward its target and
  everything on it rides along (`sand_top(x)` includes seeded dunes).
- **Rendering order**: water gradient → additive light rays → sand → back
  rocks → clams → pellets → fish → particles → front rocks → murk → air gap
  + waterline → glass streaks → frame → plaque → name pills. All clipped to
  the water rect.
- Persistence: fractions of the water rect for positions, so the save is
  resolution-independent.

## Conventions

- Python 3, single file, stdlib + pygame-ce only.
- Tunables in the constants block, not buried in code.
- Headless testing: `SDL_VIDEODRIVER=dummy` works for the full app; drive it
  via `App(..., save_path=...)` + `app.run(frames=, shot=, on_frame=)` from a
  script and inspect screenshots. `App.run` clears the module font cache on
  quit so multiple Apps can run in one process (test harnesses do this).

## Decisions

- pygame over web (matches weather-frame tooling; true fullscreen).
- Full circle of life per Nathan's choice — but tuned kind (death takes
  ~13 min of on-screen neglect, fatal fights only when already weak).
- Persistent tank so fish feel like pets; names shown on tap.
- No audio yet (possible future: bubbles/plink on feed).
