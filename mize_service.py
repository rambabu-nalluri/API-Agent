import os
import json
import time
import requests
import yaml
from dotenv import load_dotenv

# 1. Load secrets from .env
load_dotenv()
CLIENT_ID = os.getenv("CLIENT_KEY")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

# 2. Load structural config from config.yaml
with open("config.yaml", "r", encoding="utf-8") as file:
    config = yaml.safe_load(file)

BASE_URL = config.get("base_url")
AUTH_CONFIG = config.get("authentication", {})
COMMON_HEADERS = config.get("headers", {})
ENDPOINTS = config.get("endpoints", {})

# Extract paths dynamically
TOKEN_URL = f"{BASE_URL}{AUTH_CONFIG.get('token_url')}"
CLAIM_RETRIEVE_URL = f"{BASE_URL}{ENDPOINTS['claim_retrieve']['path']}"
CLAIM_SAVE_URL = f"{BASE_URL}{ENDPOINTS['save_claim']['path']}"

access_token = None
token_expires_at = 0

def get_auth_headers(token: str) -> dict:
    """Combines YAML headers with the dynamic Bearer token."""
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    return headers

def get_access_token() -> str:
    """Acquire and cache OAuth2 client credentials token."""
    global access_token, token_expires_at

    if access_token and time.time() < token_expires_at - 30:
        return access_token

    response = requests.post(
        TOKEN_URL,
        headers=COMMON_HEADERS,
        json={
            "client_secret": CLIENT_SECRET,
            "client_id": CLIENT_ID,
            "grant_type": AUTH_CONFIG.get("grant_type", "client_credentials")
        },
        timeout=30
    )
    response.raise_for_status()
    data = response.json()
    access_token = data["access_token"]
    token_expires_at = data["expires_in"] / 1000
    return access_token

def retrieve_claim(claim_id: int, **extra_params) -> dict:
    """Fetch raw claim JSON from Mize with endpoint-specific parameter config."""
    token = get_access_token()
    headers = get_auth_headers(token)
    
    # 1. Fetch parameter configurations SPECIFICALLY for this endpoint
    endpoint_config = ENDPOINTS.get("claim_retrieve", {})
    param_config = endpoint_config.get("parameters", {})
    
    claim_id_key = param_config.get("claim_id_key", "id")
    default_params = param_config.get("default_params", {})
    
    # 2. Merge default YAML params, the dynamic ID, and any extra dynamic params
    params = default_params.copy()
    params[claim_id_key] = claim_id
    params.update(extra_params)
    
    response = requests.request(
        method=endpoint_config.get("method", "GET"), 
        url=CLAIM_RETRIEVE_URL,
        headers=headers,
        params=params,
        timeout=30
    )
    response.raise_for_status()
    return response.json()

def build_new_claim_payload(template_json: dict, override_data: dict) -> dict:
    """Sanitizes a retrieved claim JSON and injects overrides."""
    payload = template_json.copy()

    read_only_keys = ["id", "claimId", "claimNumber", "creationDate", "lastUpdatedDate", "status"]
    for key in read_only_keys:
        payload.pop(key, None)

    payload.update(override_data)
    payload["claimDate"] = override_data.get("claimDate", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    return payload

def save_claim(payload: dict) -> dict:
    """POST payload to Mize CX to create the new claim."""
    token = get_access_token()
    headers = get_auth_headers(token)
    
    endpoint_config = ENDPOINTS.get("save_claim", {})
    
    response = requests.request(
        method=endpoint_config.get("method", "POST"),
        url=CLAIM_SAVE_URL,
        headers=headers,
        json=payload,
        timeout=30
    )
    response.raise_for_status()
    return response.json()


def get_result_defn(entity_name: str) -> dict:
    """Dynamically loads the resultDefn schema from the schemas folder."""
    file_path = os.path.join("schemas", f"{entity_name}_resultDefn.json")
    
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
            
    # Fallback if you haven't created the JSON file for this entity yet
    return {
        "attributes": [
            {"name": "master_EntityCode", "type": "STRING", "label": f"{entity_name} #"},
            {"name": "master_EntityStatusName", "type": "STRING", "label": "Status"}
        ]
    }

import os
import json # Make sure json is imported at the top
import time
import requests
import yaml
from dotenv import load_dotenv

# ... (keep your existing imports and configuration loading) ...

def get_result_defn(entity_name: str) -> dict:
    """Dynamically loads the resultDefn schema from the schemas folder."""
    file_path = os.path.join("schemas", f"{entity_name}_resultDefn.json")
    
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
            
    # Fallback if you haven't created the JSON file for this entity yet
    return {
        "attributes": [
            {"name": "master_EntityCode", "type": "STRING", "label": f"{entity_name} #"},
            {"name": "master_EntityStatusName", "type": "STRING", "label": "Status"}
        ]
    }

def search_records(entity_name: str, page_index: int = 0, page_size: int = 50, search_filters: list = None) -> dict:
    """Generic search for any entity with dynamically loaded configurations."""
    token = get_access_token()
    headers = get_auth_headers(token)
    
    endpoint_config = ENDPOINTS.get("search_claims", {})
    search_url = f"{BASE_URL}{endpoint_config['path']}"
    
    params = endpoint_config.get("parameters", {}).get("default_params", {}).copy()
    params["pageIndex"] = page_index
    params["pageSize"] = page_size

    if not search_filters:
        attributes = [{"value": "", "condition": "CONTAINS"}]
    else:
        attributes = search_filters

    # Construct the generic payload using the dynamic schema loader
    payload = {
        "entityName": entity_name,
        "pageIndex": page_index,
        "pageSize": str(page_size),
        "loginRequires": True,
        "transactionType": entity_name,
        "entityLockInfo": {"holdLock": "Y"},
        "attributes": attributes,
        
        # --- DYNAMIC INJECTION HAPPENS HERE ---
        "resultDefn": get_result_defn(entity_name)
    }

    response = requests.request(
        method=endpoint_config.get("method", "POST"),
        url=search_url,
        headers=headers,
        params=params,
        json=payload,
        timeout=30
    )
    
    response.raise_for_status()
    return response.json()