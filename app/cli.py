"""CLI for quick build generation without the web app.

Usage:
  .venv/bin/python -m app.cli build hunt-showdown-1896 --resolution 1080p --settings low --fps 144
  .venv/bin/python -m app.cli games
  .venv/bin/python -m app.cli parts gpus
"""

import argparse
import json
import sys

from app import builder
from app.data import games_db, parts_db
from app.ebay import EbayPricer
from app.pricing import BestBuyPricer
from app.searchapi import SearchApiPricer

SLOT_LABELS = {
    "gpu": "GPU",
    "cpu": "CPU",
    "motherboard": "Motherboard",
    "ram": "RAM",
    "storage": "Storage",
    "psu": "Power Supply",
    "case": "Case",
    "cooler": "CPU Cooler",
}


def cmd_games(_args):
    for g in sorted(games_db().values(), key=lambda g: g["name"].lower()):
        cap = f" (capped at {g['fps_cap']} FPS)" if g.get("fps_cap") else ""
        print(f"{g['id']:32} {g['name']}{cap}")
    return 0


def cmd_parts(args):
    db = parts_db()
    if args.category not in db:
        print(f"Unknown category. Choose from: {', '.join(db.keys())}", file=sys.stderr)
        return 1
    print(json.dumps(db[args.category], indent=2))
    return 0


def cmd_build(args):
    pricer = BestBuyPricer()
    ebay = EbayPricer()
    market = SearchApiPricer()
    try:
        result = builder.generate_builds(
            game_id=args.game,
            resolution=args.resolution,
            settings=args.settings,
            target_fps=args.fps,
            budget_usd=args.budget,
        )
    except KeyError as e:
        print(e, file=sys.stderr)
        return 1
    except builder.BuildImpossibleError as e:
        print(f"Cannot build: {e}", file=sys.stderr)
        return 1

    pricer.enrich_builds(result, require_in_stock=args.in_stock_only, ebay=ebay,
                         market=market)

    game = result["game"]
    print(
        f"\n{game['name']} — {result['resolution']} / {result['settings']} / "
        f"target {result['target_fps']} FPS"
    )
    print("=" * 64)
    for build in result["builds"]:
        print(
            f"\n[{build['variant'].upper()}] est. ~{build['estimated_fps']} FPS — "
            f"${build['total_price_usd']:,.0f}"
        )
        if build.get("compatibility_errors"):
            print(f"  !! compatibility: {build['compatibility_errors']}")
        if build.get("stock_swaps"):
            for swap in build["stock_swaps"]:
                print(f"  [swapped for stock] {swap}")
        for slot in SLOT_LABELS:
            part = build["parts"].get(slot)
            if part is None:
                continue
            price = part["effective_price_usd"]
            stock = part.get("live", {})
            stock_note = ""
            if stock.get("price_source") == "bestbuy":
                stock_note = " (in stock)" if stock["in_stock"] else " (OUT OF STOCK)"
            source = part.get("price_source", "baseline")
            src_note = {"bestbuy": "", "ebay": " (ebay)", "market": " (market)",
                        "baseline": " (est.)"}[source]
            print(f"  {SLOT_LABELS[slot]:14} {part['name']:48} ${price:7.0f}{src_note}{stock_note}")
            used = part.get("ebay", {}).get("used")
            if used and used.get("median_price_usd"):
                print(
                    f"  {'':14}   └ used on eBay ~${used['median_price_usd']:,.0f}"
                    f"  ({used['listing_count']} listings)"
                )
            m = part.get("shopping", {}).get("market")
            if m and m.get("best_price_usd"):
                print(
                    f"  {'':14}   └ cheapest across retailers ${m['best_price_usd']:,.0f}"
                    f" at {m['best_merchant']} ({m['offer_count']} offers)"
                )        print(f"  {'TOTAL':14} {'':48} ${build['total_price_usd']:7,.0f}")
    if result.get("prebuilts"):
        print("\nPREBUILT ALTERNATIVES")
        print("-" * 64)
        for pb in result["prebuilts"]:
            print(
                f"  {pb['name']:52} ~${pb['price_usd']:5,.0f}  ~{pb['estimated_fps']} FPS"
            )
            print(f"    {pb['retail_urls']['bestbuy']}")
    for note in result.get("notes", []):
        print(f"\nNote: {note}")
    if not pricer.enabled:
        print("\n(Using baseline prices. Set BESTBUY_API_KEY for live pricing/stock.)")
    if not ebay.enabled:
        print("(eBay marketplace pricing disabled. Set EBAY_CLIENT_ID/EBAY_CLIENT_SECRET.)")
    if not market.enabled:
        print("(Multi-retailer market pricing disabled. Set SEARCHAPI_API_KEY.)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pcmaker", description="Game-driven PC build generator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("games", help="List all supported games")

    p_parts = sub.add_parser("parts", help="Dump parts in a category")
    p_parts.add_argument("category")

    p_build = sub.add_parser("build", help="Generate builds for a game")
    p_build.add_argument("game", help="Game id (see 'games' command)")
    p_build.add_argument("--resolution", default="1080p", choices=["1080p", "1440p", "4k"])
    p_build.add_argument("--settings", default="high", choices=["low", "medium", "high", "ultra"])
    p_build.add_argument("--fps", type=int, default=60)
    p_build.add_argument("--budget", type=float, default=None)
    p_build.add_argument("--in-stock-only", action="store_true", dest="in_stock_only",
                         help="Swap out-of-stock parts for in-stock equivalents (requires BESTBUY_API_KEY)")

    args = parser.parse_args(argv)
    return {"games": cmd_games, "parts": cmd_parts, "build": cmd_build}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
