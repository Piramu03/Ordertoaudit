from decimal import Decimal, ROUND_HALF_UP


class UnitError(ValueError):
    """Unknown unit, or a conversion between different kinds of unit (e.g. kg to litre)."""


# unit -> (family, factor to the family's base unit)
FACTORS = {
    "kg": ("mass", Decimal("1")),
    "g": ("mass", Decimal("0.001")),
    "litre": ("volume", Decimal("1")),
    "ml": ("volume", Decimal("0.001")),
    "piece": ("count", Decimal("1")),
    "packet": ("count", Decimal("1")),
}

ALIASES = {
    "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "l": "litre", "lt": "litre", "ltr": "litre", "liter": "litre",
    "liters": "litre", "litres": "litre", "millilitre": "ml", "milliliter": "ml",
    "pieces": "piece", "pc": "piece", "pcs": "piece",
    "packets": "packet", "pkt": "packet", "cartons": "carton",
}

UNIT_CHOICES = ["kg", "g", "litre", "ml", "piece", "packet"]


def normalize(unit):
    u = str(unit).strip().lower()
    return ALIASES.get(u, u)


def _dec(qty):
    if isinstance(qty, float):
        raise TypeError("Use Decimal, int or str for quantities, never float")
    return qty if isinstance(qty, Decimal) else Decimal(str(qty))


def _lookup(unit, carton_size):
    u = normalize(unit)
    if u == "carton":
        if not carton_size:
            raise UnitError("Carton size (packets per carton) is needed to convert cartons")
        return "count", Decimal(str(carton_size))
    if u not in FACTORS:
        raise UnitError(f"Unknown unit '{unit}'")
    return FACTORS[u]


def convert(qty, from_unit, to_unit, carton_size=None):
    """convert(1200, 'g', 'kg') -> 1.2 ; convert(10, 'carton', 'packet', carton_size=20) -> 200"""
    qty = _dec(qty)
    if normalize(from_unit) == normalize(to_unit):
        return qty
    from_family, from_factor = _lookup(from_unit, carton_size)
    to_family, to_factor = _lookup(to_unit, carton_size)
    if from_family != to_family:
        raise UnitError(f"Cannot convert {from_unit} to {to_unit}")
    return qty * from_factor / to_factor


def to_base(qty, from_unit, base_unit, carton_size=None):
    """Convert into an item's own unit, rounded to 3 decimals (the ledger precision)."""
    return convert(qty, from_unit, base_unit, carton_size).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )


def cartons_for(packets, per_carton):
    """Full cartons and loose packets: cartons_for(188, 20) -> (9, 8)."""
    packets, per = _dec(packets), _dec(per_carton)
    if per <= 0 or packets < 0 or packets != packets.to_integral_value() or per != per.to_integral_value():
        raise UnitError("Packets and carton size must be whole numbers, and carton size above zero")
    return divmod(int(packets), int(per))