import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing import Annotated, TypedDict

# Import from your new v2 service file
import mize_service_v2

# ---------------------------------------------------------
# 1. DEFINE THE TOOLS (Sub-Agents)
# ---------------------------------------------------------
def normalize_entity_name(name: str) -> str:
    entity_map = {
        "inspection": "InspectionForm",
        "claim": "Claim",
        "service": "ServiceOrder",
        "registration": "ProductRegistration",
        "support": "ProductSupport"
    }
    return entity_map.get(name.lower(), name)

@tool
def fetch_record(entity_name: str, entity_code: str) -> str:
    """
    Fetches the complete details of a specific record.
    - entity_name: "Claim", "InspectionForm", "Registration", "Support", "Service".
    - entity_code: The exact ID or Code of the record to fetch.
    """
    strict_name = normalize_entity_name(entity_name)
    try:
        data = mize_service_v2.retrieve_record(strict_name, entity_code)
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})

@tool
def search_records(entity_name: str, page_size: int = 5, filters: list = None) -> str:
    """
    Searches for records. Use this to find an 'entityCode' if you don't already have one.
    - entity_name: "Claim", "InspectionForm","ServiceOrder","ProductRegistration", "ProductSupport", etc.
    - page_size: Number of records to return.
    """
    strict_name = normalize_entity_name(entity_name)
    try:
        data = mize_service_v2.search_records(strict_name, page_index=0, page_size=page_size, search_filters=filters)
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})

@tool
def create_record(entity_name: str, serial_number: str, model: str, brand: str, requester_type_code: str, requester_code: str, **additional_fields) -> str:
    """
    Creates a new record in the system.
    Requires entity_name, serial_number, model, brand, requester_type_code, and requester_code.
    """
    strict_name = normalize_entity_name(entity_name)
    payload = {
        "entityName": strict_name,
        "product_Serial": serial_number,
        "product_Model": model,
        "brand": brand,
        "requesterTypeCode": requester_type_code,
        "requesterCode": requester_code
    }
    payload.update(additional_fields)
    
    try:
        data = mize_service_v2.save_record(strict_name, payload)
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})

# ---------------------------------------------------------
# 2. DEFINE THE STATE & GRAPH
# ---------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

def create_agentic_workflow():
    llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash")
    tools = [fetch_record, search_records, create_record]
    llm_with_tools = llm.bind_tools(tools)
    
    system_prompt = SystemMessage(content=(
        "You are an autonomous AI Orchestrator managing Mize CX data. "
        "You have tools to Search, Fetch, and Create records. "
        "If a user asks for a multi-step task (e.g., 'Search for X and then Fetch it'), "
        "you MUST execute the tools sequentially. Call the Search tool, read the resulting 'master_EntityCode' or 'entityCode', "
        "and then immediately call the Fetch tool using that exact code. "
        "IMPORTANT: Your final response MUST be strictly valid JSON representing the FINAL result. "
        "Do not output conversational text."
    ))

    def reasoning_node(state: AgentState):
        messages = [system_prompt] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools=tools)

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", reasoning_node)
    workflow.add_node("tools", tool_node)
    
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", tools_condition)
    workflow.add_edge("tools", "agent")
    
    return workflow.compile()

def run_agentic_system(query: str) -> str:
    app = create_agentic_workflow()
    initial_state = {"messages": [HumanMessage(content=query)]}
    result = app.invoke(initial_state)
    
    # 1. Extract the raw content from the final message
    raw_content = result["messages"][-1].content
    
    # 2. Safety check: If Gemini returned a list of blocks, extract the text string
    if isinstance(raw_content, list):
        content = raw_content[0].get("text", "")
    else:
        content = raw_content
        
    # 3. Now it is safe to strip
    content = content.strip()
    
    # 4. Remove Markdown formatting if the AI added it
    if content.startswith("```json"): 
        content = content[7:]
    elif content.startswith("```"): 
        content = content[3:]
    if content.endswith("```"): 
        content = content[:-3]
        
    return content.strip()

# ---------------------------------------------------------
# 3. COLLABORATIVE TEST SUITE
# ---------------------------------------------------------
if __name__ == "__main__":
    test_suite = {
        # Tests the system's ability to chain Search -> Fetch sequentially
        "Collaborative_Claim_Flow": (
            "Search for the top 3 Claim records. "
            "Find the entity code of the first record in those search results, "
            "and then fetch the complete details for that specific claim."
        ),
        # Tests single tool execution
        "Single_Search_Inspection": (
            "Search for the first 2 Inspection records."
        )
    }
    
    print("--- Starting Agentic V2 System ---")
    
    for test_name, query in test_suite.items():
        print(f"\n🚀 Running Test: {test_name}")
        raw_output = run_agentic_system(query)
        
        filename = f"agent_v2_result_{test_name}.json"
        try:
            parsed_json = json.loads(raw_output)
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(parsed_json, file, indent=4)
            print(f"✅ Success! Output saved to {filename}")
        except json.JSONDecodeError:
            print(f"⚠️ Agent did not return valid JSON. Printing raw output:")
            print(raw_output)