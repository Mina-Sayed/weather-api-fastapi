# Weather API (FastAPI + Weatherstack)

A minimal HTTP API that fetches current weather for a single city using the Weatherstack API.

## Requirements

- Python 3.10+
- A Weatherstack API key (free tier works)

## Setup

1) Create and activate a virtualenv
1) Install dependencies:

```bash
pip install -r requirements.txt
```

1) Export your API key:

```bash
export WEATHERSTACK_API_KEY="your_key_here"
```

1) Run the server:

```bash
uvicorn app.main:app --reload
```

## Usage

Fetch current weather for a city:

```bash
curl "http://127.0.0.1:8000/weather?city=London"
```

Interactive docs:

- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- OpenAPI: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

## Configuration

All config is via environment variables:

- `WEATHERSTACK_API_KEY` (required)
- `WEATHERSTACK_BASE_URL` (optional, default `https://api.weatherstack.com`)
- `HTTP_TIMEOUT_SECONDS` (optional, default `5.0`)
- `CACHE_ENABLED` (optional, default `true`)
- `CACHE_TTL_SECONDS` (optional, default `300`)

## Docker (optional)

Build and run:

```bash
docker build -t weather-api .
docker run --rm -p 8000:8000 -e WEATHERSTACK_API_KEY="$WEATHERSTACK_API_KEY" weather-api
```

Or with Docker Compose:

```bash
WEATHERSTACK_API_KEY="$WEATHERSTACK_API_KEY" docker compose up --build
```

## Assumptions / trade-offs

- Uses a simple in-memory TTL cache (per-process). This keeps the solution small but won’t share cache across instances.
- Returns a small, stable response shape instead of proxying Weatherstack’s full payload.
- No retries/backoff to keep code small.

## What I’d improve for production with more time

- Add retries with jittered exponential backoff and better upstream error classification.
- Add structured logging (request id, correlation id), metrics, and tracing.
- Add rate limiting and request validation rules (e.g., city normalization).
- Add tests (mocking Weatherstack) and CI.
- Replace in-memory caching with Redis for horizontal scaling.
- Add containerization/health checks and deployment config.
