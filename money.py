"""Deterministic penny arithmetic for every money figure in the app.

Money used to be rounded at whatever level each screen happened to aggregate
at, so the GP report, the Division report, the dashboard and the committee PDF
could all disagree by a few pence. These helpers give every report one rule:

* a single figure is rounded half-up to the penny;
* a column of figures is *allocated* so the rows add up exactly to the
  rounded total of the column (largest-remainder method).

Callers should allocate the components that stand on their own (total
revenue, member revenue, total cost, member cost) and derive the rest by
subtraction, so that component rows always add back to their totals.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

PENNY = Decimal('0.01')

# Every revenue figure the system records is ex-VAT; the EPOS exports are
# inc-VAT. One shared rate keeps the uplift in a single place.
VAT_RATE = 0.20
VAT_MULTIPLIER = 1 + VAT_RATE


def _decimal(value):
    """Coerce a number to a finite Decimal, treating junk as zero."""
    if value is None:
        return Decimal('0')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')
    if not number.is_finite():
        return Decimal('0')
    return number


def round_money(value):
    """Round one amount to the nearest penny (half away from zero)."""
    return float(_decimal(value).quantize(PENNY, rounding=ROUND_HALF_UP))


def sum_money(values):
    """Sum exact values and round the result once."""
    total = Decimal('0')
    for value in values:
        total += _decimal(value)
    return float(total.quantize(PENNY, rounding=ROUND_HALF_UP))


def inc_vat(ex_amount):
    """Return the VAT-inclusive value of an ex-VAT amount.

    The conversion is done once on the total, not line by line: the stored
    ex-VAT lines are already rounded to the penny, so adding VAT per line
    would compound that rounding and drift several pence from the EPOS
    export. ``ex_total × 1.2`` recovers the export total to within a penny.
    """
    return round_money(_decimal(ex_amount) * Decimal(str(VAT_MULTIPLIER)))


def ex_vat(inc_amount):
    """Return the ex-VAT value of a VAT-inclusive amount, rounded once."""
    return round_money(_decimal(inc_amount) / Decimal(str(VAT_MULTIPLIER)))


def allocate_money(values):
    """Round a column of amounts so the parts add up to the rounded total.

    The rounded parts differ from naive per-row rounding by at most a penny
    each; the residual is given to the rows that were rounded down hardest
    (or taken from those rounded up hardest), with the original position as a
    stable tie-break. The result is therefore deterministic.
    """
    values = list(values)
    if not values:
        return []

    exact = [_decimal(value) for value in values]
    target = sum(exact, Decimal('0')).quantize(PENNY, rounding=ROUND_HALF_UP)
    rounded = [value.quantize(PENNY, rounding=ROUND_HALF_UP) for value in exact]

    residual = target - sum(rounded, Decimal('0'))
    steps = int(residual / PENNY)
    if steps:
        if steps > 0:
            order = sorted(range(len(values)), key=lambda i: (rounded[i] - exact[i], i))
            step = PENNY
        else:
            order = sorted(range(len(values)), key=lambda i: (exact[i] - rounded[i], i))
            step = -PENNY
        for position in range(abs(steps)):
            rounded[order[position % len(order)]] += step

    return [float(value) for value in rounded]
