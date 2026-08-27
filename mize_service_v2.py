import os
import time
import requests
import yaml
import json
from dotenv import load_dotenv

# 1. Load secrets and config
load_dotenv()
CLIENT_ID = os.getenv("CLIENT_KEY")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

with open("config_v2.yaml", "r", encoding="utf-8") as file:
    config = yaml.safe_load(file)

BASE_URL = config.get("base_url")
AUTH_CONFIG = config.get("authentication", {})
COMMON_HEADERS = config.get("headers", {})
ENDPOINTS = config.get("endpoints", {})

access_token = None
token_expires_at = 0

def get_auth_headers(token: str) -> dict:
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    return headers

def get_access_token() -> str:
    global access_token, token_expires_at
    if access_token and time.time() < token_expires_at - 30:
        return access_token

    token_url = f"{BASE_URL}{AUTH_CONFIG['token_url']}"
    response = requests.post(
        token_url,
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
    token_expires_at = time.time() + (data["expires_in"] / 1000)
    return access_token

def get_result_defn(entity_name: str) -> dict:
    """Dynamically loads the resultDefn schema from the schemas folder."""
    file_path = os.path.join("schemas", f"{entity_name}_resultDefn.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
            
    # Minimal fallback schema
    return {
        "attributes": [
            {"name": "master_EntityCode", "type": "STRING", "label": f"{entity_name} #"},
            {"name": "master_EntityStatusName", "type": "STRING", "label": "Status"}
        ]
    }

def search_records(entity_name: str, page_index: int = 0, page_size: int = 50, search_filters: list = None) -> dict:
    token = get_access_token()
    headers = get_auth_headers(token)
    
    endpoint = ENDPOINTS["search_records"]
    url = f"{BASE_URL}{endpoint['path']}?pageIndex={page_index}&pageSize={page_size}"
    
    attributes = search_filters if search_filters else [{"value": "", "condition": "CONTAINS"}]
    
    payload = {
        "entityName": entity_name,
        "pageIndex": page_index,
        "pageSize": str(page_size),
        "loginRequires": True,
        "transactionType": entity_name,
        "entityLockInfo": {"holdLock": "Y"},
        "attributes": attributes,
        "resultDefn": get_result_defn(entity_name)
    }

    response = requests.request(endpoint["method"], url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()

def retrieve_record(entity_name: str, entity_code: str) -> dict:
    token = get_access_token()
    headers = get_auth_headers(token)
    
    endpoint = ENDPOINTS["retrieve_record"]
    
    # Dynamically inject the entity name into the URL (e.g., "Claim" -> "claim")
    dynamic_path = endpoint['path'].format(entity=entity_name.lower())
    url = f"{BASE_URL}{dynamic_path}"
    
    # Some APIs pass the ID in the URL params as well. Adjust "id" or "entityCode" based on Mize's requirement.
    params = {
        "entityCode": entity_code 
    }

    response = requests.request(endpoint["method"], url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def save_record(entity_name: str, payload: dict) -> dict:
    token = get_access_token()
    headers = get_auth_headers(token)
    
    endpoint = ENDPOINTS["save_record"]
    
    # Dynamically inject the entity name into the URL
    dynamic_path = endpoint['path'].format(entity=entity_name.lower())
    url = f"{BASE_URL}{dynamic_path}"
    
    response = requests.request(endpoint["method"], url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()