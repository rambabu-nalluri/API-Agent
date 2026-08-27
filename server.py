from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import mize_service

app = FastAPI(title="Mize CX OData API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["OData-Version", "Content-Type"]
)

@app.get("/odata/$metadata", response_class=Response)
def get_odata_metadata():
    try:
        with open("metadata.json", "r", encoding="utf-8") as f:
            csdl_content = f.read()
        return Response(content=csdl_content, media_type="application/json")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="metadata.json not found")

@app.get("/odata/Claims")
def get_odata_claims(id: Optional[int] = None):
    if id:
        raw_claim = mize_service.retrieve_claim(id)
        return {
            "@odata.context": "/odata/$metadata#Claims/$entity",
            "Id": raw_claim.get("id"),
            "ClaimNumber": raw_claim.get("claimNumber"),
            "SerialNumber": raw_claim.get("serialNumber"),
            "ProductCode": raw_claim.get("productCode"),
            "ClaimStatus": raw_claim.get("status"),
            "Description": raw_claim.get("description", "")
        }
    return {"@odata.context": "/odata/$metadata#Claims", "value": []}