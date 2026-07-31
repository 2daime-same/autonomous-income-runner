# Engineering Unit Conversion REST API

A deterministic, container-ready FastAPI service for local engineering-unit conversions. It performs all calculations in-process with `decimal.Decimal`; there are no external conversion APIs, network lookups, databases, or paid dependencies.

## Acceptance-criteria coverage

| Requirement | Implementation evidence |
|---|---|
| Eight engineering domains | `length`, `force_torque`, `pressure`, `temperature`, `electrical`, `flow`, `thermal`, `mass_density` |
| At least 50 supported unit pairs | `/health` reports the computed compatible directed and undirected pair counts from the registry; both exceed 50 |
| Local calculations only | All exact factors and affine temperature transforms are declared in `app/conversions.py` |
| Three requested endpoints | `GET/POST /convert`, `GET /units`, `GET /domains` |
| At least 30 tests | Reference-value tests, all-unit round trips, API tests, dimensional-error tests, and validation tests in `tests/` |
| Docker deployment | Non-root Python 3.12 image with health check in `Dockerfile` |
| Documentation and examples | This README plus generated OpenAPI, Swagger UI at `/docs`, and ReDoc at `/redoc` |
| Accuracy within 0.1% | Exact decimal constants and reference assertions are substantially tighter than 0.1%; every compatible unit pair is round-trip tested |

## Domains and quantities

- **Length:** metric, imperial, statute, and nautical units.
- **Force and torque:** separate `force` and `torque` groups, preventing dimensional mistakes.
- **Pressure:** pascal family, bar, psi/ksi, atmosphere, torr, mmHg, and inHg.
- **Temperature:** Celsius, Fahrenheit, kelvin, and Rankine with affine offsets.
- **Electrical:** voltage, current, resistance, power, energy, charge, and capacitance.
- **Flow:** volumetric and mass flow rates.
- **Thermal:** thermal energy, heat rate, thermal conductivity, and heat-transfer coefficient.
- **Mass and density:** separate mass and density groups.

`GET /domains` and `GET /units?domain=<code>` are the canonical machine-readable catalogs.

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for interactive Swagger documentation.

## API examples

List domains:

```bash
curl http://127.0.0.1:8000/domains
```

List pressure units:

```bash
curl 'http://127.0.0.1:8000/units?domain=pressure'
```

Convert with a GET request:

```bash
curl 'http://127.0.0.1:8000/convert?domain=pressure&from_unit=psi&to_unit=kPa&value=35'
```

Convert with a POST request:

```bash
curl -X POST http://127.0.0.1:8000/convert \
  -H 'content-type: application/json' \
  -d '{"domain":"temperature","from_unit":"F","to_unit":"C","value":"68"}'
```

Representative response:

```json
{
  "domain": "temperature",
  "quantity": "temperature",
  "from_unit": "F",
  "to_unit": "C",
  "input": 68.0,
  "input_text": "68",
  "result": 20.0,
  "result_text": "20"
}
```

The numeric `result` is convenient for ordinary JSON clients. `result_text` preserves the high-precision decimal representation for clients that must avoid a binary floating-point round trip.

## Error model

Unknown domains or units return HTTP 404. Invalid or dimensionally incompatible conversions return HTTP 422:

```json
{
  "detail": {
    "code": "incompatible_units",
    "message": "Cannot convert V (voltage) to ohm (resistance)."
  }
}
```

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
```

The test suite includes one or more independently known conversion values for every required domain, affine temperature checks, alias and Unicode handling, invalid-input checks, API contract checks, and exhaustive round trips across every compatible source/target pair.

## Docker

```bash
docker build -t engineering-unit-api .
docker run --rm -p 8000:8000 engineering-unit-api
curl http://127.0.0.1:8000/health
```

The container runs as an unprivileged user and contains only the runtime package and application source.

## Design notes

Each unit is represented by an exact affine transformation to a base unit:

```text
base = (input + source_offset) × source_factor
output = base ÷ target_factor − target_offset
```

Most engineering units have zero offset. Temperature scales use both factor and offset. Units also carry a `quantity` identifier; the engine refuses conversions across quantities even when both units appear in the same public domain.

## License

MIT. See `LICENSE`.
