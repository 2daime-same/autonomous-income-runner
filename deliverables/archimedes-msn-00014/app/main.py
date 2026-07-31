"""FastAPI surface for the Engineering Unit Conversion service."""

from __future__ import annotations

from decimal import Decimal
import math
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import __version__
from .conversions import (
    ConversionError,
    convert,
    decimal_text,
    domain_catalog,
    registry_invariants,
    unit_catalog,
)

app = FastAPI(
    title="Engineering Unit Conversion API",
    version=__version__,
    description=(
        "Deterministic, offline engineering-unit conversions across length, "
        "force/torque, pressure, temperature, electrical, flow, thermal, and mass/density domains."
    ),
    license_info={"name": "MIT"},
)


class ConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    domain: str = Field(min_length=1, max_length=80)
    from_unit: str = Field(min_length=1, max_length=80)
    to_unit: str = Field(min_length=1, max_length=80)
    value: Decimal

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("value must be finite")
        return value


class ConversionResponse(BaseModel):
    domain: str
    quantity: str
    from_unit: str
    to_unit: str
    input: float
    input_text: str
    result: float
    result_text: str


def _safe_float(value: Decimal) -> float:
    converted = float(value)
    if not math.isfinite(converted):
        raise ConversionError("result_out_of_json_range", "Value is outside the finite JSON number range.")
    return converted


def _perform(payload: ConversionRequest) -> ConversionResponse:
    result, source, target, domain = convert(
        value=payload.value,
        domain=payload.domain,
        from_unit=payload.from_unit,
        to_unit=payload.to_unit,
    )
    return ConversionResponse(
        domain=domain.code,
        quantity=source.quantity,
        from_unit=source.code,
        to_unit=target.code,
        input=_safe_float(payload.value),
        input_text=decimal_text(payload.value),
        result=_safe_float(result),
        result_text=decimal_text(result),
    )


@app.exception_handler(ConversionError)
async def conversion_error_handler(_request: Request, exc: ConversionError) -> JSONResponse:
    status = 404 if exc.code in {"unknown_domain", "unknown_unit"} else 422
    return JSONResponse(status_code=status, content={"detail": {"code": exc.code, "message": str(exc)}})


@app.get("/", tags=["service"])
def service_index() -> dict[str, Any]:
    counts = registry_invariants()
    return {
        "service": "engineering-unit-conversion-api",
        "version": __version__,
        "status": "ok",
        "documentation": "/docs",
        **counts,
    }


@app.get("/health", tags=["service"])
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__, **registry_invariants()}


@app.get("/domains", tags=["catalog"])
def list_domains() -> dict[str, Any]:
    domains = domain_catalog()
    return {"count": len(domains), "domains": domains}


@app.get("/units", tags=["catalog"])
def list_units(
    domain: Annotated[str, Query(min_length=1, max_length=80, description="Domain code or alias")],
) -> dict[str, Any]:
    definition, units = unit_catalog(domain)
    return {"domain": definition.code, "count": len(units), "units": units}


@app.get("/convert", response_model=ConversionResponse, tags=["conversion"])
def convert_get(
    domain: Annotated[str, Query(min_length=1, max_length=80)],
    from_unit: Annotated[str, Query(min_length=1, max_length=80)],
    to_unit: Annotated[str, Query(min_length=1, max_length=80)],
    value: Decimal,
) -> ConversionResponse:
    return _perform(
        ConversionRequest(domain=domain, from_unit=from_unit, to_unit=to_unit, value=value)
    )


@app.post("/convert", response_model=ConversionResponse, tags=["conversion"])
def convert_post(payload: ConversionRequest) -> ConversionResponse:
    return _perform(payload)
