"""French Cash Reconciliation — Zelty "Espèce" (cash) totals.

Pulls orders for a single day across all restaurants on the Zelty account,
filters each order's payments down to the cash ("Espèce") method, and prints
the cash total per site plus a grand total.

Auth: reads the Zelty API token from the ZELTY_API_TOKEN environment variable.
      Never hard-code the token in this file.

  PowerShell:  $env:ZELTY_API_TOKEN = "<token>"
  Bash:        export ZELTY_API_TOKEN="<token>"

"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

BASE_URL = os.environ.get("ZELTY_BASE_URL", "https://api.zelty.fr/2.7")

# Labels we treat as cash. Zelty returns a payment "method"/"type"; the French
# # cash label is "Espèce"/"Espèces". Matching is case-insensitive and accent-
# # tolerant, and we also allow a numeric type id via ZELTY_CASH_TYPE_ID once the
# # real value is confirmed from a live response (see the discovery output below).
CASH_LABELS = {"espece", "especes", "cash"}
CASH_TYPE_ID = os.environ.get("ZELTY_CASH_TYPE_ID")  # optional, e.g. "1"


def _strip_accents(s: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _normalize(s: str) -> str:
    return _strip_accents(str(s)).strip().lower()


def api_get(path: str, params: dict | None = None) -> dict:
    """GET a Zelty API endpoint and return the parsed JSON body."""
    token = os.environ.get("ZELTY_API_TOKEN")
    if not token:
        sys.exit(
            "ERROR: ZELTY_API_TOKEN is not set.\n"
            '  PowerShell:  $env:ZELTY_API_TOKEN = "<token>"\n'
            '  Bash:        export ZELTY_API_TOKEN="<token>"'
        )

    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        sys.exit(f"ERROR: HTTP {e.code} calling {url}\n{body}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: could not reach {url}: {e.reason}")


def list_restaurants() -> list[dict]:
    """Return the restaurants on the account. Falls back gracefully if the
    account exposes a single restaurant."""
    data = api_get("/restaurants")
    # Zelty commonly wraps list payloads under a key; handle both shapes.
    if isinstance(data, dict):
        for key in ("restaurants", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return data
    return [data] if data else []


def list_orders(date: str, restaurant_id: str | int | None = None) -> list[dict]:
    """Return orders for a single day (YYYY-MM-DD). `since`/`until` bound the
    day inclusively; adjust here if the account uses different filter params."""
    params = {"since": date, "until": date, "limit": 1000}
    if restaurant_id is not None:
        params["id_restaurant"] = restaurant_id
    data = api_get("/orders", params)
    if isinstance(data, dict):
        for key in ("orders", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return data
    return []


def iter_payments(order: dict):
    """Yield (method_label, method_id, amount) for each payment on an order.
    Kept forgiving because payment shape is confirmed against live data."""
    payments = order.get("payments") or order.get("payment") or []
    if isinstance(payments, dict):
        payments = [payments]
    for p in payments:
        if not isinstance(p, dict):
            continue
        label = p.get("name") or p.get("method") or p.get("type_name") or p.get("label") or ""
        method_id = p.get("id_type") or p.get("type") or p.get("id_payment_type")
        amount = p.get("amount") or p.get("total") or p.get("value") or 0
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0
        # Zelty amounts are often in cents; heuristic conversion is applied at
        # the reporting layer, not here — this yields the raw value.
        yield label, method_id, amount


def is_cash(label: str, method_id) -> bool:
    if CASH_TYPE_ID is not None and str(method_id) == str(CASH_TYPE_ID):
        return True
    return _normalize(label) in CASH_LABELS


def main() -> None:
    parser = argparse.ArgumentParser(description="Zelty cash (Espèce) totals for a single day.")
    parser.add_argument(
        "--date",
        default=(dt.date.today() - dt.timedelta(days=1)).isoformat(),
        help="Day to report, YYYY-MM-DD (default: yesterday).",
    )
    parser.add_argument(
        "--restaurant",
        default=None,
        help="Restrict to a single restaurant id (default: all sites).",
    )
    parser.add_argument(
        "--cents",
        action="store_true",
        help="Treat amounts as cents and divide by 100 for display.",
    )
    args = parser.parse_args()

    if args.restaurant is not None:
        sites = [{"id": args.restaurant, "name": f"Restaurant {args.restaurant}"}]
    else:
        sites = list_restaurants()
        if not sites:
            sys.exit("No restaurants returned by the API.")

    scale = 100.0 if args.cents else 1.0

    cash_by_site: dict[str, float] = defaultdict(float)
    seen_methods: dict[str, float] = defaultdict(float)  # discovery aid
    order_counts: dict[str, int] = defaultdict(int)

    for site in sites:
        site_id = site.get("id") or site.get("id_restaurant")
        site_name = site.get("name") or f"Restaurant {site_id}"
        orders = list_orders(args.date, site_id)
        for order in orders:
            order_counts[site_name] += 1
            for label, method_id, amount in iter_payments(order):
                seen_methods[label or f"(id {method_id})"] += amount / scale
                if is_cash(label, method_id):
                    cash_by_site[site_name] += amount / scale

    # --- Report -------------------------------------------------------------
    print(f"\nZelty cash (Espèce) reconciliation — {args.date}")
    print("=" * 52)
    grand_total = 0.0
    for site_name in sorted(set(list(cash_by_site) + list(order_counts))):
        total = cash_by_site.get(site_name, 0.0)
        grand_total += total
        print(f"  {site_name:<34} {total:>12,.2f}  ({order_counts[site_name]} orders)")
    print("-" * 52)
    print(f"  {'TOTAL Espèce':<34} {grand_total:>12,.2f}")

    # First-run discovery: confirm which label really maps to cash.
    print("\nPayment methods seen (confirm the cash label is captured above):")
    if seen_methods:
        for label, amt in sorted(seen_methods.items(), key=lambda kv: -kv[1]):
            flag = "  <- counted as CASH" if _normalize(label) in CASH_LABELS else ""
            print(f"  - {label!r}: {amt:,.2f}{flag}")
    else:
        print("  (no payments found — check the date and filter params)")


if __name__ == "__main__":
    main()
