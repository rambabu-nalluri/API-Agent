# Mize Agentic System

A Python integration for Mize CX that supports:

- Claim retrieval and claim creation from a template
- Generic record search using entity-specific `resultDefn` JSON files
- Generic record retrieve, search, and save operations through `mize_service_v2.py`
- Single-agent, graph-based, and multi-agent workflows
- A small FastAPI OData-compatible claims endpoint

## Project Files

- `mize_service.py`: original claim service plus generic search and schema loading
- `mize_service_v2.py`: generic retrieve, search, and save service
- `agent.py`: single agent and tool integration suite
- `agent_v2.py`: LangGraph search/fetch/create workflow
- `agent_v3.py`: supervisor and specialist multi-agent workflow
- `server.py`: FastAPI server
- `config.yaml`, `config_v2.yaml`: API endpoint configuration
- `schemas/`: entity-specific search result definitions
- `metadata.json`: metadata returned by the OData endpoint

## Requirements

- Python 3.10 or newer
- Access to the Mize CX environment
- A Google Generative AI API key for the agent workflows
- Mize client credentials for the API integration

## Setup

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create a `.env` file in the project directory. Use your own credentials and do not commit this file:

```dotenv
CLIENT_KEY=your_mize_client_key
CLIENT_SECRET=your_mize_client_secret
MIZE_BASE_URL=https://ccdemo.mizecx.com
GOOGLE_API_KEY=your_google_api_key
```

The current service reads `base_url` from the YAML files. `MIZE_BASE_URL` is retained as a useful environment reference but does not override the YAML value.

## Entity Schemas

Generic search loads a schema using this filename convention:

```text
schemas/<ExactMizeEntityName>_resultDefn.json
```

Current dedicated schemas:

- `Claim_resultDefn.json`
- `InspectionForm_resultDefn.json`
- `ServiceOrder_resultDefn.json`

For an entity without a dedicated file, the service uses a minimal fallback containing entity code and status fields. Add a JSON file with an `attributes` array when an entity needs its full result definition. The exact entity names used by the current agents are:

| User-facing name | Mize entity name |
| --- | --- |
| Claim | `Claim` |
| Inspection | `InspectionForm` |
| Service | `ServiceOrder` |
| Registration | `ProductRegistration` |
| Support | `ProductSupport` |

## Run the API

Start the FastAPI server from the project directory:

```bash
source .venv/bin/activate
uvicorn server:app --reload
```

Useful endpoints:

```text
GET http://127.0.0.1:8000/odata/$metadata
GET http://127.0.0.1:8000/odata/Claims
GET http://127.0.0.1:8000/odata/Claims?id=<claim-id>
```

## Run Completed Integration Suites

These suites make live calls to Mize CX and the configured Google model. Run them only with valid credentials and test data.

### Single-agent suite

`agent.py` currently enables `Fetch_Claim_12957` by default:

```bash
source .venv/bin/activate
python agent.py
```

To run the search cases in the same suite, enable the desired entries in the `test_suite` dictionary in `agent.py`, then run the command again. Results are written as `test_result_<name>.json`; non-JSON responses are written as `test_error_<name>.txt`.

### V2 graph suite

```bash
source .venv/bin/activate
python agent_v2.py
```

This runs the collaborative Claim search-to-fetch flow and the Inspection search flow defined in `agent_v2.py`. Results are written as `agent_v2_result_<name>.json`.

### V3 multi-agent suite

```bash
source .venv/bin/activate
python agent_v3.py
```

This runs the supervisor flow that searches for Claim records and fetches the first record. Results are written as `agent_v3_<name>.json`.

The V2 and V3 agents use `mize_service_v2.py` and therefore read `config_v2.yaml`.

## Quick Service-Level Check

This checks schema parsing without calling Mize or the model:

```bash
source .venv/bin/activate
python - <<'PY'
import json
from pathlib import Path

for path in Path("schemas").glob("*_resultDefn.json"):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data.get("attributes"), list), path
    print(f"OK: {path} ({len(data['attributes'])} attributes)")
PY
```

There is currently no pytest test suite. The agent scripts above are live integration tests rather than isolated unit tests, so a failed run can be caused by credentials, API availability, model output, endpoint configuration, or test-record data.

## Configuration Notes

- `config.yaml` is used by `mize_service.py`.
- `config_v2.yaml` is used by `mize_service_v2.py`.
- The OAuth token expiry calculation differs between the two service modules; verify the Mize API's `expires_in` unit before relying on long-running processes.
- The FastAPI endpoint currently exposes only claims and returns an empty collection when no claim ID is supplied.

## Security

Do not commit `.env`, generated trajectory files, or integration outputs. Any credential that has been exposed in logs, chat, screenshots, or a shared workspace should be revoked and replaced before further testing.
