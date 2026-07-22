"""Where the daily Zelty cash figure (column D) comes from.

There is no invented/demo data. Until the Zelty API key is connected, the app
does not fabricate cash figures — column D is read from the workbook (for days
already recorded) or typed in manually. This module only handles the *live* pull
once a key exists.

Public entry point:
    get_cash(date, site_names) -> {site_name: cash_float}   # live Zelty only
"""

from __future__ import annotations

import datetime as dt


def get_cash(date: dt.date, site_names: list[str]) -> dict[str, float]:
    """Live Zelty cash per site for `date`. Inert until a key + mapping exist."""
    # Real path — fill in once ZELTY_API_TOKEN and recon.SITE_TO_ZELTY exist.
    #   import main, recon
    #   out = {}
    #   for name in site_names:
    #       rid = recon.SITE_TO_ZELTY.get(name)
    #       orders = main.list_orders(date.isoformat(), rid)
    #       total = sum(a for o in orders for lbl, mid, a in main.iter_payments(o)
    #                   if main.is_cash(lbl, mid))          # cash only
    #       out[name] = total
    #   return out
    raise NotImplementedError(
        "Live Zelty pull is not active yet: awaiting ZELTY_API_TOKEN and the "
        "workbook->restaurant mapping (recon.SITE_TO_ZELTY)."
    )
