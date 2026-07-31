"""Deterministic engineering-unit conversion registry and engine.

The engine intentionally uses :class:`decimal.Decimal` throughout so conversion
constants do not inherit binary floating-point error. Every unit belongs to a
quantity group. Conversions are permitted only inside the same group, which
prevents dimensionally invalid operations such as volts to ohms or force to
torque.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import math
import re
import unicodedata
from typing import Any, Iterable, Mapping

ZERO = Decimal("0")
ONE = Decimal("1")


class ConversionError(ValueError):
    """A structured, user-facing conversion failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class UnitDefinition:
    """One unit represented as an affine transform to its quantity base unit."""

    code: str
    name: str
    symbol: str
    quantity: str
    factor: Decimal = ONE
    offset: Decimal = ZERO
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainDefinition:
    """A public API domain containing one or more compatible quantities."""

    code: str
    name: str
    description: str
    units: tuple[UnitDefinition, ...]
    aliases: tuple[str, ...] = ()


def D(value: str | int) -> Decimal:
    return Decimal(str(value))


def U(
    code: str,
    name: str,
    symbol: str,
    quantity: str,
    factor: str | int = "1",
    *,
    offset: str | int = "0",
    aliases: Iterable[str] = (),
) -> UnitDefinition:
    return UnitDefinition(
        code=code,
        name=name,
        symbol=symbol,
        quantity=quantity,
        factor=D(factor),
        offset=D(offset),
        aliases=tuple(aliases),
    )


DOMAINS: tuple[DomainDefinition, ...] = (
    DomainDefinition(
        code="length",
        name="Length",
        description="Metric, imperial, statute, and nautical length units.",
        aliases=("distance",),
        units=(
            U("m", "metre", "m", "length", aliases=("meter", "metres", "meters")),
            U("km", "kilometre", "km", "length", "1000", aliases=("kilometer", "kilometres", "kilometers")),
            U("cm", "centimetre", "cm", "length", "0.01", aliases=("centimeter", "centimetres", "centimeters")),
            U("mm", "millimetre", "mm", "length", "0.001", aliases=("millimeter", "millimetres", "millimeters")),
            U("um", "micrometre", "µm", "length", "0.000001", aliases=("micrometer", "micron", "microns", "μm", "µm")),
            U("nm", "nanometre", "nm", "length", "0.000000001", aliases=("nanometer", "nanometres", "nanometers")),
            U("in", "inch", "in", "length", "0.0254", aliases=("inch", "inches", "\"")),
            U("ft", "foot", "ft", "length", "0.3048", aliases=("foot", "feet", "'")),
            U("yd", "yard", "yd", "length", "0.9144", aliases=("yard", "yards")),
            U("mi", "statute mile", "mi", "length", "1609.344", aliases=("mile", "miles")),
            U("nmi", "nautical mile", "nmi", "length", "1852", aliases=("nautical_mile", "nautical miles")),
        ),
    ),
    DomainDefinition(
        code="force_torque",
        name="Force and torque",
        description="Force and torque units kept in separate dimensional groups.",
        aliases=("force-torque", "force and torque", "mechanical_force"),
        units=(
            U("N", "newton", "N", "force", aliases=("newton", "newtons")),
            U("kN", "kilonewton", "kN", "force", "1000", aliases=("kilonewton", "kilonewtons")),
            U("MN", "meganewton", "MN", "force", "1000000", aliases=("meganewton", "meganewtons")),
            U("lbf", "pound-force", "lbf", "force", "4.4482216152605", aliases=("pound_force", "pounds_force")),
            U("kgf", "kilogram-force", "kgf", "force", "9.80665", aliases=("kilogram_force", "kilopond")),
            U("dyn", "dyne", "dyn", "force", "0.00001", aliases=("dyne", "dynes")),
            U("N_m", "newton-metre", "N·m", "torque", aliases=("nm_torque", "newton_metre", "newton_meter", "n*m", "n-m")),
            U("N_mm", "newton-millimetre", "N·mm", "torque", "0.001", aliases=("newton_millimetre", "newton_millimeter", "n*mm")),
            U("kN_m", "kilonewton-metre", "kN·m", "torque", "1000", aliases=("kilonewton_metre", "kilonewton_meter", "kn*m")),
            U("lbf_ft", "pound-force foot", "lbf·ft", "torque", "1.3558179483314004", aliases=("lb_ft", "ft_lbf", "foot_pound", "pound_foot")),
            U("lbf_in", "pound-force inch", "lbf·in", "torque", "0.1129848290276167", aliases=("lb_in", "in_lbf", "inch_pound", "pound_inch")),
            U("kgf_m", "kilogram-force metre", "kgf·m", "torque", "9.80665", aliases=("kilogram_force_metre", "kilogram_force_meter")),
        ),
    ),
    DomainDefinition(
        code="pressure",
        name="Pressure",
        description="SI, atmospheric, mercury-column, and imperial pressure units.",
        units=(
            U("Pa", "pascal", "Pa", "pressure", aliases=("pascal", "pascals")),
            U("kPa", "kilopascal", "kPa", "pressure", "1000", aliases=("kilopascal", "kilopascals")),
            U("MPa", "megapascal", "MPa", "pressure", "1000000", aliases=("megapascal", "megapascals")),
            U("GPa", "gigapascal", "GPa", "pressure", "1000000000", aliases=("gigapascal", "gigapascals")),
            U("bar", "bar", "bar", "pressure", "100000", aliases=("bars",)),
            U("mbar", "millibar", "mbar", "pressure", "100", aliases=("millibar", "millibars", "hpa")),
            U("psi", "pound per square inch", "psi", "pressure", "6894.757293168", aliases=("lb_in2", "lbf_in2")),
            U("ksi", "kip per square inch", "ksi", "pressure", "6894757.293168", aliases=("kpsi",)),
            U("atm", "standard atmosphere", "atm", "pressure", "101325", aliases=("atmosphere", "atmospheres")),
            U("torr", "torr", "Torr", "pressure", "133.3223684210526315789473684"),
            U("mmHg", "millimetre of mercury", "mmHg", "pressure", "133.322387415", aliases=("mm_hg",)),
            U("inHg", "inch of mercury", "inHg", "pressure", "3386.389", aliases=("in_hg",)),
        ),
    ),
    DomainDefinition(
        code="temperature",
        name="Temperature",
        description="Absolute and relative temperature scales with affine offsets.",
        aliases=("temp",),
        units=(
            U("C", "degree Celsius", "°C", "temperature", offset="273.15", aliases=("celsius", "degC", "°C")),
            U("F", "degree Fahrenheit", "°F", "temperature", "0.55555555555555555555555555555555555555555555555556", offset="459.67", aliases=("fahrenheit", "degF", "°F")),
            U("K", "kelvin", "K", "temperature", aliases=("kelvins",)),
            U("R", "degree Rankine", "°R", "temperature", "0.55555555555555555555555555555555555555555555555556", aliases=("rankine", "degR", "°R")),
        ),
    ),
    DomainDefinition(
        code="electrical",
        name="Electrical",
        description="Voltage, current, resistance, power, energy, charge, and capacitance.",
        aliases=("electric", "electricity"),
        units=(
            U("V", "volt", "V", "voltage", aliases=("volt", "volts")),
            U("mV", "millivolt", "mV", "voltage", "0.001", aliases=("millivolt", "millivolts")),
            U("kV", "kilovolt", "kV", "voltage", "1000", aliases=("kilovolt", "kilovolts")),
            U("A", "ampere", "A", "current", aliases=("amp", "amps", "ampere", "amperes")),
            U("mA", "milliampere", "mA", "current", "0.001", aliases=("milliamp", "milliamps", "milliampere")),
            U("uA", "microampere", "µA", "current", "0.000001", aliases=("microamp", "microamps", "microampere", "μA", "µA")),
            U("ohm", "ohm", "Ω", "resistance", aliases=("ohms", "Ω")),
            U("kohm", "kilohm", "kΩ", "resistance", "1000", aliases=("kiloohm", "kilohm", "kΩ")),
            U("Mohm", "megohm", "MΩ", "resistance", "1000000", aliases=("megaohm", "megohm", "MΩ")),
            U("W", "watt", "W", "power", aliases=("watt", "watts")),
            U("kW", "kilowatt", "kW", "power", "1000", aliases=("kilowatt", "kilowatts")),
            U("MW", "megawatt", "MW", "power", "1000000", aliases=("megawatt", "megawatts")),
            U("hp_e", "electrical horsepower", "hp", "power", "746", aliases=("horsepower_electric", "electric_horsepower", "hp")),
            U("J", "joule", "J", "energy", aliases=("joule", "joules")),
            U("Wh", "watt-hour", "Wh", "energy", "3600", aliases=("watt_hour", "watt_hours")),
            U("kWh", "kilowatt-hour", "kWh", "energy", "3600000", aliases=("kilowatt_hour", "kilowatt_hours")),
            U("MWh", "megawatt-hour", "MWh", "energy", "3600000000", aliases=("megawatt_hour", "megawatt_hours")),
            U("Coulomb", "coulomb", "C", "charge", aliases=("coulomb", "coulombs")),
            U("Ah", "ampere-hour", "Ah", "charge", "3600", aliases=("amp_hour", "ampere_hour")),
            U("mAh", "milliampere-hour", "mAh", "charge", "3.6", aliases=("milliamp_hour", "milliampere_hour")),
            U("F_cap", "farad", "F", "capacitance", aliases=("farad", "farads")),
            U("mF", "millifarad", "mF", "capacitance", "0.001", aliases=("millifarad", "millifarads")),
            U("uF", "microfarad", "µF", "capacitance", "0.000001", aliases=("microfarad", "microfarads", "μF", "µF")),
            U("nF", "nanofarad", "nF", "capacitance", "0.000000001", aliases=("nanofarad", "nanofarads")),
            U("pF", "picofarad", "pF", "capacitance", "0.000000000001", aliases=("picofarad", "picofarads")),
        ),
    ),
    DomainDefinition(
        code="flow",
        name="Flow",
        description="Volumetric and mass flow-rate units.",
        aliases=("flow_rate", "flow-rate"),
        units=(
            U("m3_s", "cubic metre per second", "m³/s", "volume_flow", aliases=("m3/s", "m^3/s", "cubic_metre_per_second")),
            U("L_s", "litre per second", "L/s", "volume_flow", "0.001", aliases=("l/s", "liter_per_second", "litre_per_second")),
            U("L_min", "litre per minute", "L/min", "volume_flow", "0.000016666666666666666666666666666666666666666666666667", aliases=("l/min", "lpm", "liter_per_minute", "litre_per_minute")),
            U("m3_h", "cubic metre per hour", "m³/h", "volume_flow", "0.00027777777777777777777777777777777777777777777777778", aliases=("m3/h", "m^3/h", "cubic_metre_per_hour")),
            U("cm3_s", "cubic centimetre per second", "cm³/s", "volume_flow", "0.000001", aliases=("cm3/s", "cc/s", "ccps")),
            U("cfm", "cubic foot per minute", "ft³/min", "volume_flow", "0.0004719474432", aliases=("ft3/min", "cubic_feet_per_minute")),
            U("gpm_us", "US gallon per minute", "US gal/min", "volume_flow", "0.0000630901964", aliases=("us_gpm", "gpm", "gallon_us_per_minute")),
            U("gpm_uk", "imperial gallon per minute", "Imp gal/min", "volume_flow", "0.0000757681667", aliases=("uk_gpm", "imperial_gpm", "gallon_uk_per_minute")),
            U("kg_s", "kilogram per second", "kg/s", "mass_flow", aliases=("kg/s", "kilogram_per_second")),
            U("kg_min", "kilogram per minute", "kg/min", "mass_flow", "0.016666666666666666666666666666666666666666666666667", aliases=("kg/min", "kilogram_per_minute")),
            U("kg_h", "kilogram per hour", "kg/h", "mass_flow", "0.00027777777777777777777777777777777777777777777777778", aliases=("kg/h", "kilogram_per_hour")),
            U("g_s", "gram per second", "g/s", "mass_flow", "0.001", aliases=("g/s", "gram_per_second")),
            U("lb_s", "pound per second", "lb/s", "mass_flow", "0.45359237", aliases=("lb/s", "pound_per_second")),
            U("lb_min", "pound per minute", "lb/min", "mass_flow", "0.0075598728333333333333333333333333333333333333333333", aliases=("lb/min", "pound_per_minute")),
            U("lb_h", "pound per hour", "lb/h", "mass_flow", "0.00012599788055555555555555555555555555555555555555556", aliases=("lb/h", "pound_per_hour")),
        ),
    ),
    DomainDefinition(
        code="thermal",
        name="Thermal",
        description="Thermal energy, heat rate, conductivity, and heat-transfer coefficient.",
        aliases=("heat",),
        units=(
            U("J", "joule", "J", "thermal_energy", aliases=("joule", "joules")),
            U("kJ", "kilojoule", "kJ", "thermal_energy", "1000", aliases=("kilojoule", "kilojoules")),
            U("MJ", "megajoule", "MJ", "thermal_energy", "1000000", aliases=("megajoule", "megajoules")),
            U("cal", "thermochemical calorie", "cal", "thermal_energy", "4.184", aliases=("calorie", "calories")),
            U("kcal", "kilocalorie", "kcal", "thermal_energy", "4184", aliases=("kilocalorie", "kilocalories")),
            U("BTU", "International Table British thermal unit", "BTU", "thermal_energy", "1055.05585262", aliases=("btu", "british_thermal_unit")),
            U("therm_us", "US therm", "therm", "thermal_energy", "105480400", aliases=("us_therm", "therm")),
            U("Wh", "watt-hour", "Wh", "thermal_energy", "3600", aliases=("watt_hour",)),
            U("kWh", "kilowatt-hour", "kWh", "thermal_energy", "3600000", aliases=("kilowatt_hour",)),
            U("W", "watt", "W", "heat_rate", aliases=("watt", "watts")),
            U("kW", "kilowatt", "kW", "heat_rate", "1000", aliases=("kilowatt", "kilowatts")),
            U("MW", "megawatt", "MW", "heat_rate", "1000000", aliases=("megawatt", "megawatts")),
            U("BTU_h", "British thermal unit per hour", "BTU/h", "heat_rate", "0.2930710701722222", aliases=("btu/h", "btu_per_hour")),
            U("kcal_h", "kilocalorie per hour", "kcal/h", "heat_rate", "1.1622222222222222222222222222222222222222222222222", aliases=("kcal/h", "kilocalorie_per_hour")),
            U("ton_ref", "ton of refrigeration", "TR", "heat_rate", "3516.8528420667", aliases=("refrigeration_ton", "ton_refrigeration", "tr")),
            U("W_mK", "watt per metre-kelvin", "W/(m·K)", "thermal_conductivity", aliases=("w/mk", "w_m_k")),
            U("mW_mK", "milliwatt per metre-kelvin", "mW/(m·K)", "thermal_conductivity", "0.001", aliases=("mw/mk", "mw_m_k")),
            U("BTU_h_ft_F", "BTU per hour-foot-degree Fahrenheit", "BTU/(h·ft·°F)", "thermal_conductivity", "1.730734666371", aliases=("btu/h-ft-f", "btu_h_ft_f")),
            U("W_m2K", "watt per square metre-kelvin", "W/(m²·K)", "heat_transfer_coefficient", aliases=("w/m2k", "w_m2_k")),
            U("BTU_h_ft2_F", "BTU per hour-square foot-degree Fahrenheit", "BTU/(h·ft²·°F)", "heat_transfer_coefficient", "5.6782633411135", aliases=("btu/h-ft2-f", "btu_h_ft2_f")),
        ),
    ),
    DomainDefinition(
        code="mass_density",
        name="Mass and density",
        description="Mass and density units kept in separate dimensional groups.",
        aliases=("mass-density", "mass and density", "mass"),
        units=(
            U("kg", "kilogram", "kg", "mass", aliases=("kilogram", "kilograms")),
            U("g", "gram", "g", "mass", "0.001", aliases=("gram", "grams")),
            U("mg", "milligram", "mg", "mass", "0.000001", aliases=("milligram", "milligrams")),
            U("ug", "microgram", "µg", "mass", "0.000000001", aliases=("microgram", "micrograms", "μg", "µg")),
            U("tonne", "metric tonne", "t", "mass", "1000", aliases=("metric_ton", "metric_tonne", "tonnes")),
            U("lb", "avoirdupois pound", "lb", "mass", "0.45359237", aliases=("pound", "pounds", "lbs")),
            U("oz", "avoirdupois ounce", "oz", "mass", "0.028349523125", aliases=("ounce", "ounces")),
            U("slug", "slug", "slug", "mass", "14.59390293720636", aliases=("slugs",)),
            U("kg_m3", "kilogram per cubic metre", "kg/m³", "density", aliases=("kg/m3", "kg/m^3")),
            U("g_cm3", "gram per cubic centimetre", "g/cm³", "density", "1000", aliases=("g/cm3", "g/cc")),
            U("g_mL", "gram per millilitre", "g/mL", "density", "1000", aliases=("g/ml",)),
            U("kg_L", "kilogram per litre", "kg/L", "density", "1000", aliases=("kg/l",)),
            U("lb_ft3", "pound per cubic foot", "lb/ft³", "density", "16.01846337396014", aliases=("lb/ft3", "pcf")),
            U("lb_in3", "pound per cubic inch", "lb/in³", "density", "27679.904710191", aliases=("lb/in3", "pci")),
            U("oz_in3", "ounce per cubic inch", "oz/in³", "density", "1729.9940443869", aliases=("oz/in3",)),
        ),
    ),
)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip().lower()
    text = text.replace("μ", "u").replace("µ", "u").replace("ω", "ohm")
    text = text.replace("°", "deg")
    text = text.replace("³", "3").replace("²", "2")
    text = text.replace("·", "_").replace("⋅", "_").replace("*", "_")
    text = text.replace("/", "_per_")
    text = text.replace("^", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _build_domain_index() -> dict[str, DomainDefinition]:
    index: dict[str, DomainDefinition] = {}
    for domain in DOMAINS:
        for value in (domain.code, domain.name, *domain.aliases):
            key = _normalize(value)
            if key in index and index[key] is not domain:
                raise RuntimeError(f"Duplicate domain alias: {value}")
            index[key] = domain
    return index


def _build_unit_index(domain: DomainDefinition) -> dict[str, UnitDefinition]:
    index: dict[str, UnitDefinition] = {}
    for unit in domain.units:
        for value in (unit.code, unit.name, unit.symbol, *unit.aliases):
            key = _normalize(value)
            if not key:
                continue
            existing = index.get(key)
            if existing is not None and existing is not unit:
                continue
            index[key] = unit
    return index


_DOMAIN_INDEX = _build_domain_index()
_UNIT_INDEXES: dict[str, dict[str, UnitDefinition]] = {
    domain.code: _build_unit_index(domain) for domain in DOMAINS
}


def coerce_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ConversionError("invalid_value", "Boolean values are not valid measurements.")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ConversionError("non_finite_value", "Measurement value must be finite.")
        result = Decimal(str(value))
    else:
        try:
            result = Decimal(str(value).strip())
        except (InvalidOperation, AttributeError, ValueError) as exc:
            raise ConversionError("invalid_value", f"Could not parse measurement value: {value!r}.") from exc
    if not result.is_finite():
        raise ConversionError("non_finite_value", "Measurement value must be finite.")
    return result


def resolve_domain(domain: str) -> DomainDefinition:
    match = _DOMAIN_INDEX.get(_normalize(domain))
    if match is None:
        supported = ", ".join(item.code for item in DOMAINS)
        raise ConversionError("unknown_domain", f"Unknown domain {domain!r}. Supported domains: {supported}.")
    return match


def resolve_unit(domain: DomainDefinition, unit: str) -> UnitDefinition:
    match = _UNIT_INDEXES[domain.code].get(_normalize(unit))
    if match is None:
        supported = ", ".join(item.code for item in domain.units)
        raise ConversionError(
            "unknown_unit",
            f"Unknown unit {unit!r} in domain {domain.code!r}. Supported units: {supported}.",
        )
    return match


def convert(value: Any, domain: str, from_unit: str, to_unit: str) -> tuple[Decimal, UnitDefinition, UnitDefinition, DomainDefinition]:
    source_value = coerce_decimal(value)
    domain_definition = resolve_domain(domain)
    source = resolve_unit(domain_definition, from_unit)
    target = resolve_unit(domain_definition, to_unit)
    if source.quantity != target.quantity:
        raise ConversionError(
            "incompatible_units",
            f"Cannot convert {source.code} ({source.quantity}) to {target.code} ({target.quantity}).",
        )
    with localcontext() as context:
        context.prec = 50
        base_value = (source_value + source.offset) * source.factor
        result = (base_value / target.factor) - target.offset
    if not result.is_finite():
        raise ConversionError("non_finite_result", "Conversion result is not finite.")
    return result, source, target, domain_definition


def decimal_text(value: Decimal) -> str:
    if value == ZERO:
        return "0"
    adjusted = value.adjusted()
    if -12 <= adjusted <= 18:
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    return format(value.normalize(), "E")


def quantity_pair_count(domain: DomainDefinition, *, directed: bool = True) -> int:
    counts: dict[str, int] = {}
    for unit in domain.units:
        counts[unit.quantity] = counts.get(unit.quantity, 0) + 1
    if directed:
        return sum(count * (count - 1) for count in counts.values())
    return sum(count * (count - 1) // 2 for count in counts.values())


def total_pair_count(*, directed: bool = True) -> int:
    return sum(quantity_pair_count(domain, directed=directed) for domain in DOMAINS)


def domain_catalog() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for domain in DOMAINS:
        quantities = sorted({unit.quantity for unit in domain.units})
        output.append(
            {
                "code": domain.code,
                "name": domain.name,
                "description": domain.description,
                "quantities": quantities,
                "unit_count": len(domain.units),
                "directed_pair_count": quantity_pair_count(domain),
            }
        )
    return output


def unit_catalog(domain: str) -> tuple[DomainDefinition, list[dict[str, Any]]]:
    definition = resolve_domain(domain)
    units = [
        {
            "code": unit.code,
            "name": unit.name,
            "symbol": unit.symbol,
            "quantity": unit.quantity,
            "aliases": list(unit.aliases),
        }
        for unit in definition.units
    ]
    return definition, units


def registry_invariants() -> Mapping[str, int]:
    return {
        "domain_count": len(DOMAINS),
        "unit_count": sum(len(domain.units) for domain in DOMAINS),
        "directed_pair_count": total_pair_count(directed=True),
        "undirected_pair_count": total_pair_count(directed=False),
    }
