import os
import json
from dotenv import load_dotenv

# Load variables before initializing anything else
load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_core.messages import messages_to_dict

import mize_service

# --- DEFINE AGENT TOOLS ---

@tool
def fetch_claim_details(claim_id: int) -> str:
    """Retrieves the full JSON data of an existing claim by its ID."""
    try:
        data = mize_service.retrieve_claim(claim_id)
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})

@tool
def create_claim_from_template(template_claim_id: int, overrides: dict) -> str:
    """Creates a new claim using an existing claim as a template and applying overrides."""
    try:
        template = mize_service.retrieve_claim(template_claim_id)
        payload = mize_service.build_new_claim_payload(template, overrides)
        result = mize_service.save_claim(payload)
        return json.dumps({"status": "success", "data": result})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def search_records(entity_name: str, page_index: int = 0, page_size: int = 50, filters: list = None) -> str:
    """
    Generic search tool to find records in the system.
    - entity_name: MUST be the exact system entity name. 
      Map user requests using these rules:
        * "Inspection" -> "InspectionForm"
        * "Claim" -> "Claim"
        * "Service" -> "ServiceOrder"
        * "Registration" -> "ProductRegistration"
        * "Support" -> "ProductSupport"
    - page_index: Defaults to 0 (first page).
    - page_size: Defaults to 50.
    - filters: Optional list of dictionaries, e.g., [{"name": "product_Serial", "value": "12345", "condition": "EQUALS"}]
    """
    
    # 1. Python Safety Net: Map colloquial names to strict API entity names
    # This ensures that even if the AI passes "Inspection", the code fixes it.
    entity_map = {
        "inspection": "InspectionForm",
        "claim": "Claim",
        "service": "ServiceOrder",
        "registration": "ProductRegistration",
        "support": "ProductSupport"
    }
    
    # Clean the input (e.g., "Inspection" -> "inspection") and look it up.
    # If the AI correctly passed "InspectionForm", the .get() will default back to "InspectionForm".
    strict_entity_name = entity_map.get(entity_name.lower(), entity_name)
    
    try:
        data = mize_service.search_records(
            entity_name=strict_entity_name, # Use the mapped name here
            page_index=page_index, 
            page_size=page_size, 
            search_filters=filters
        )
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})

# --- BUILD AGENT ---

def run_agent(query: str):
    llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash")
    tools = [fetch_claim_details, create_claim_from_template, search_records]
    
    system_prompt = (
        "You are an AI API Agent. You execute backend operations for claims data. "
        "IMPORTANT: Your final response MUST be strictly valid JSON representing the result. "
        "Do not include any conversational text, explanations, or greetings. "
        "Output ONLY the raw JSON object."
    )
    
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt
    )
    
    response = agent.invoke({
        "messages": [{"role": "user", "content": query}]
    })
    
    # --- NEW CODE: Save the entire complete response ---
    # Convert the LangChain message objects into standard dictionaries
    full_history_dict = {
        "messages": messages_to_dict(response["messages"])
    }
    
    # Save the complete trajectory to a file
    with open("full_agent_trajectory.json", "w", encoding="utf-8") as file:
        json.dump(full_history_dict, file, indent=4)
    # ---------------------------------------------------
    
    # Continue with extracting the final answer...
    content = response["messages"][-1].content
    if isinstance(content, list):
        content = content[0].get("text", "")
        
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
        
    return content.strip()


if __name__ == "__main__":
    # Define a generic test suite covering ALL tools.
    # Comment out any test you don't want to run right now by adding a '#' at the start of the line.
    test_suite = {
        # --- TESTING THE FETCH TOOL ---
        "Fetch_Claim_12957": "Fetch the complete details for claim 12957.",
        
        # --- TESTING THE SEARCH TOOL ---
        # "Search_Inspections": "Search for the first 5 Inspection records.",
        # "Search_Claims": "Search for the first 3 Claim records.",
        # "Search_Service": "Search for the first 2 Service records.",
        # "Search_Registration": "Search for the first 5 Registration records.",
        # "Search_Support": "Search for the first 10 Support records.",
        
    }
    
    print("--- Starting Agentic Test Suite ---")
    
    for test_name, query in test_suite.items():
        print(f"\n🚀 Running Test: {test_name}")
        print(f"Prompt: \"{query}\"")
        
        # Execute the agent
        raw_output = run_agent(query)
        
        # Define a unique filename for this test
        filename = f"test_result_{test_name}.json"
        
        try:
            # Parse and save the JSON
            parsed_json = json.loads(raw_output)
            
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(parsed_json, file, indent=4)
                
            print(f"✅ Success! Output saved to {filename}")
            
        except json.JSONDecodeError:
            # Fallback if the AI returned plain text
            error_filename = f"test_error_{test_name}.txt"
            with open(error_filename, "w", encoding="utf-8") as file:
                file.write(raw_output)
            print(f"⚠️ Agent did not return valid JSON. Saved raw text to {error_filename}")
        
        print("-" * 60)
        