# PC Maker

Tell it a game, a resolution, settings, and a target FPS — it generates complete,
compatible PC part lists with pricing.

## How it works

1. **Game performance model** (`data/games.json`, `app/perf.py`) — each game has a
   relative GPU/CPU load and VRAM requirements per resolution. Combined with a GPU
   tier benchmark table (`data/perf.json`), we estimate FPS for any game/resolution/
   settings combo and find the minimum GPU tier that hits your target.
2. **Compatibility checker** (`app/compat.py`) — socket/chipset match, DDR generation,
   PSU wattage (+20% headroom), GPU length vs case, cooler height/TDP/socket.
3. **Build generator** (`app/builder.py`) — produces up to 3 builds
   (**Value / Balanced / Headroom**) by picking the cheapest fully-compatible parts
   around the required CPU+GPU core. Optional budget filter. Also matches curated
   prebuilt systems (`data/prebuilts.json`) that meet the same target.
4. **Retailer links** (`app/retail.py`) — every part and prebuilt gets Best Buy and
   Newegg search deep links, which always resolve to live listings (real prices/stock).
5. **Live pricing** (`app/pricing.py`) — optional Best Buy Products API integration
   (price, stock, add-to-cart links) with a 1-hour disk cache and automatic fallback
   to curated baseline prices.

## Quick start (CLI)

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python -m app.cli games
.venv/bin/python -m app.cli build hunt-showdown-1896 --resolution 1080p --settings low --fps 144
.venv/bin/python -m app.cli build cyberpunk-2077 --resolution 1440p --settings ultra --fps 60 --budget 1500
```

## Quick start (web app)

```bash
# terminal 1 — API
.venv/bin/uvicorn app.main:app --reload

# terminal 2 — frontend
cd frontend && npm install && npm run dev
# open http://localhost:5173
```

## Live pricing (optional)

Get a free API key at https://developer.bestbuy.com and:

```bash
export BESTBUY_API_KEY=yourkey
```

Parts with a `bestbuy_sku` in `data/parts.json` get exact lookups; others fall back
to a Best Buy name search (`search_term` field), then to baseline prices if the API
is unreachable. Stock status and "Buy at Best Buy" links appear in the UI.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

## Adding data

- **New game**: add an entry to `data/games.json` with `gpu_load` (1.0 ≈ Cyberpunk
  2077-level), `cpu_load`, and `vram_gb` per resolution. Use `fps_cap` for
  engine-locked games (e.g. Elden Ring's 60).
- **New part**: add to the right category in `data/parts.json`. GPUs/CPUs need a
  `tier` (1–8); motherboards need socket/DDR/form factor; PSUs need wattage; cases
  need max GPU length and cooler height; coolers need socket list and TDP capacity.
- **New prebuilt**: add to `data/prebuilts.json` with `gpu_tier`/`cpu_tier` on the
  same 1–8 scale plus `vram_gb`, `ram_gb`, `storage_gb`, and a `search_term` that
  finds it on Best Buy/Newegg.

## Project layout

```
app/
  data.py      # loaders for the curated databases
  perf.py      # FPS estimation + required tier math
  compat.py    # part compatibility rules
  builder.py   # build generation (Value/Balanced/Headroom) + prebuilt matching
  retail.py    # Best Buy / Newegg search link generation
  pricing.py   # Best Buy client, cache, fallback logic
  main.py      # FastAPI app
  cli.py       # command-line interface
data/
  parts.json      # curated parts database
  games.json      # game performance profiles (27 games)
  perf.json       # GPU tier benchmark table + multipliers
  prebuilts.json  # curated prebuilt systems (8 configs)
frontend/      # React + Vite web UI
tests/         # pytest suite (compat, perf, builder, pricing, retail, API)
```

## Notes & limitations

- FPS estimates are approximations from a tier-based model, not benchmark data —
  treat them as guidance (~±15%).
- Baseline prices are snapshots; live pricing requires a Best Buy API key.
- GPU/CPU tiers 1–8 currently cover roughly RX 6500 XT → RTX 5090 class hardware.
