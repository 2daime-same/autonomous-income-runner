from __future__ import annotations

from decimal import Decimal
import itertools

import pytest

from app.conversions import (
    ConversionError,
    DOMAINS,
    convert,
    decimal_text,
    registry_invariants,
    resolve_domain,
    resolve_unit,
)


@pytest.mark.parametrize(
    ("domain", "source", "target", "value", "expected", "tolerance"),
    [
        ("length", "m", "mm", "1", "1000", "1e-40"),
        ("length", "in", "mm", "1", "25.4", "1e-40"),
        ("length", "mi", "km", "1", "1.609344", "1e-40"),
        ("length", "nmi", "m", "1", "1852", "1e-40"),
        ("force_torque", "lbf", "N", "1", "4.4482216152605", "1e-40"),
        ("force_torque", "kgf", "N", "1", "9.80665", "1e-40"),
        ("force_torque", "lbf_ft", "N_m", "1", "1.3558179483314004", "1e-40"),
        ("force_torque", "N_mm", "N_m", "1000", "1", "1e-40"),
        ("pressure", "bar", "kPa", "1", "100", "1e-40"),
        ("pressure", "atm", "Pa", "1", "101325", "1e-40"),
        ("pressure", "psi", "kPa", "1", "6.894757293168", "1e-35"),
        ("pressure", "torr", "atm", "760", "1", "1e-25"),
        ("temperature", "C", "K", "0", "273.15", "1e-40"),
        ("temperature", "C", "F", "100", "212", "1e-35"),
        ("temperature", "F", "C", "32", "0", "1e-35"),
        ("temperature", "K", "R", "273.15", "491.67", "1e-35"),
        ("electrical", "kV", "V", "2.4", "2400", "1e-40"),
        ("electrical", "mA", "A", "250", "0.25", "1e-40"),
        ("electrical", "Mohm", "ohm", "1.5", "1500000", "1e-40"),
        ("electrical", "hp_e", "W", "1", "746", "1e-40"),
        ("electrical", "kWh", "J", "1", "3600000", "1e-40"),
        ("electrical", "Ah", "Coulomb", "1", "3600", "1e-40"),
        ("electrical", "uF", "nF", "1", "1000", "1e-40"),
        ("flow", "L_min", "m3_h", "60", "3.6", "1e-35"),
        ("flow", "cfm", "m3_s", "1", "0.0004719474432", "1e-40"),
        ("flow", "gpm_us", "L_min", "1", "3.785411784", "1e-30"),
        ("flow", "lb_h", "kg_h", "1", "0.45359237", "1e-35"),
        ("thermal", "kcal", "kJ", "1", "4.184", "1e-40"),
        ("thermal", "BTU", "J", "1", "1055.05585262", "1e-40"),
        ("thermal", "kW", "BTU_h", "1", "3412.141633", "1e-6"),
        ("thermal", "ton_ref", "kW", "1", "3.5168528420667", "1e-35"),
        ("thermal", "BTU_h_ft_F", "W_mK", "1", "1.730734666371", "1e-40"),
        ("thermal", "BTU_h_ft2_F", "W_m2K", "1", "5.6782633411135", "1e-40"),
        ("mass_density", "lb", "kg", "1", "0.45359237", "1e-40"),
        ("mass_density", "oz", "g", "1", "28.349523125", "1e-35"),
        ("mass_density", "tonne", "kg", "1", "1000", "1e-40"),
        ("mass_density", "g_cm3", "kg_m3", "1", "1000", "1e-40"),
        ("mass_density", "lb_ft3", "kg_m3", "1", "16.01846337396014", "1e-40"),
    ],
)
def test_reference_conversions(domain, source, target, value, expected, tolerance):
    result, *_ = convert(value, domain, source, target)
    assert abs(result - Decimal(expected)) <= Decimal(tolerance)


def test_exact_registry_scope_exceeds_bounty_minimum():
    counts = registry_invariants()
    assert counts["domain_count"] == 8
    assert counts["unit_count"] >= 100
    assert counts["directed_pair_count"] >= 50
    assert counts["undirected_pair_count"] >= 50


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.code)
def test_every_domain_has_compatible_pairs(domain):
    quantities: dict[str, int] = {}
    for unit in domain.units:
        quantities[unit.quantity] = quantities.get(unit.quantity, 0) + 1
    assert all(count >= 2 for count in quantities.values())


@pytest.mark.parametrize("domain", DOMAINS, ids=lambda domain: domain.code)
def test_round_trip_every_compatible_unit_pair(domain):
    values = (Decimal("-12.345"), Decimal("0"), Decimal("98765.4321"))
    units_by_quantity: dict[str, list] = {}
    for unit in domain.units:
        units_by_quantity.setdefault(unit.quantity, []).append(unit)
    for units in units_by_quantity.values():
        for source, target in itertools.permutations(units, 2):
            for value in values:
                converted, *_ = convert(value, domain.code, source.code, target.code)
                round_trip, *_ = convert(converted, domain.code, target.code, source.code)
                assert abs(round_trip - value) <= Decimal("1e-35") * max(abs(value), Decimal("1"))


def test_aliases_and_unicode_are_resolved():
    result, source, target, domain = convert("1", "force-torque", "n*m", "lbf·ft")
    assert domain.code == "force_torque"
    assert source.code == "N_m"
    assert target.code == "lbf_ft"
    assert result > Decimal("0.737")

    result, source, target, _ = convert("1", "electrical", "µF", "nF")
    assert source.code == "uF"
    assert target.code == "nF"
    assert result == Decimal("1000")


def test_incompatible_quantities_are_rejected():
    with pytest.raises(ConversionError, match="Cannot convert") as exc:
        convert("1", "electrical", "V", "ohm")
    assert exc.value.code == "incompatible_units"

    with pytest.raises(ConversionError) as exc:
        convert("1", "force_torque", "N", "N_m")
    assert exc.value.code == "incompatible_units"


def test_unknown_domain_and_unit_are_structured():
    with pytest.raises(ConversionError) as exc:
        resolve_domain("alchemy")
    assert exc.value.code == "unknown_domain"

    domain = resolve_domain("length")
    with pytest.raises(ConversionError) as exc:
        resolve_unit(domain, "furlong")
    assert exc.value.code == "unknown_unit"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True, "not-a-number"])
def test_non_finite_and_invalid_values_are_rejected(value):
    with pytest.raises(ConversionError):
        convert(value, "length", "m", "km")


def test_decimal_text_is_stable():
    assert decimal_text(Decimal("100.0000")) == "100"
    assert decimal_text(Decimal("0.0012300")) == "0.00123"
    assert decimal_text(Decimal("0")) == "0"
