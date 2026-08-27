import json
import operator
from typing import Annotated, Literal, Sequence, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from pydantic import BaseModel
from langgraph.graph import StateGraph, START, END

# We add # type: ignore to tell Pylance it is making a mistake and to hide the warning
#from langgraph.prebuilt import create_react_agent  # type: ignore

# Add these to your existing imports
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import ToolNode, tools_condition

import mize_service_v2

# ---------------------------------------------------------
# 1. DEFINE THE TOOLS
# ---------------------------------------------------------
def normalize_entity_name(name: str) -> str:
    entity_map = {"inspection": "InspectionForm", "claim": "Claim", "service": "ServiceOrder", "registration": "ProductRegistration", "support": "ProductSupport"}
    return entity_map.get(name.lower(), name)

@tool
def fetch_record(entity_name: str, entity_code: str) -> str:
    """Fetches the complete details of a specific record by its code."""
    try:
        data = mize_service_v2.retrieve_record(normalize_entity_name(entity_name), entity_code)
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})

import time

@tool
def search_records(entity_name: str, page_size: int = 5, filters: list = None) -> str:
    """Searches for records and returns a list of matching items."""
    time.sleep(2)
    try:
        data = mize_service_v2.search_records(normalize_entity_name(entity_name), page_index=0, page_size=page_size, search_filters=filters)
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})

@tool
def create_record(entity_name: str, serial_number: str, model: str, brand: str, requester_type_code: str, requester_code: str, **kwargs) -> str:
    """Creates a new record in the system."""
    payload = {
        "entityName": normalize_entity_name(entity_name),
        "product_Serial": serial_number,
        "product_Model": model,
        "brand": brand,
        "requesterTypeCode": requester_type_code,
        "requesterCode": requester_code,
        **kwargs
    }
    try:
        data = mize_service_v2.save_record(normalize_entity_name(entity_name), payload)
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------
# 2. DEFINE THE GRAPH STATE
# ---------------------------------------------------------
# operator.add ensures that messages are appended to the list rather than overwritten
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next: str  # Tracks who the Supervisor wants to act next


# ---------------------------------------------------------
# 3. BUILD THE WORKER AGENTS
# ---------------------------------------------------------
llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash")

# This helper dynamically creates a mini-graph for each specialist
def build_worker_subgraph(system_prompt: str, specialized_tools: list):
    llm_with_tools = llm.bind_tools(specialized_tools)
    
    def worker_brain(state: AgentState):

        print(f"   [Worker] Thinking... (waiting 4s to prevent rate limit)")
        time.sleep(4) # <--- ADD THIS THROTTLE

        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}
        
    # Build the mini-graph
    builder = StateGraph(AgentState)
    builder.add_node("brain", worker_brain)
    builder.add_node("tools", ToolNode(tools=specialized_tools))
    
    builder.add_edge(START, "brain")
    builder.add_conditional_edges("brain", tools_condition)
    builder.add_edge("tools", "brain")
    
    return builder.compile()

# This wrapper runs the subgraph and tags the final output with the worker's name
def create_worker_node(compiled_subgraph, name: str):
    def node(state: AgentState):
        result = compiled_subgraph.invoke({"messages": state["messages"]})
        last_message = result["messages"][-1].content
        return {"messages": [HumanMessage(content=last_message, name=name)]}
    return node

# --- Spin up the Subgraphs ---

# Worker 1: The Search Specialist
search_subgraph = build_worker_subgraph(
    "You are the Search Specialist. Search for the requested records. "
    "Output the search results as JSON so the next agent can read the record IDs and entity codes.",
    [search_records]
)
search_node = create_worker_node(search_subgraph, "Search_Specialist")

# Worker 2: The Fetch Specialist
fetch_subgraph = build_worker_subgraph(
    "You are the Fetch Specialist. Your job is to retrieve full details using fetch_record. "
    "If the Supervisor asks you to fetch MULTIPLE records, you must call your fetch_record tool multiple times "
    "(once for each ID) before answering. Return the complete retrieved record(s) as a clean JSON object or array.",
    [fetch_record]
)
fetch_node = create_worker_node(fetch_subgraph, "Fetch_Specialist")

# Worker 3: The Create Specialist
create_subgraph = build_worker_subgraph(
    "You are the Create Specialist. Your ONLY job is to save new records to the database. Format your final answer as pure JSON.",
    [create_record]
)
create_node = create_worker_node(create_subgraph, "Create_Specialist")


# ---------------------------------------------------------
# 4. BUILD THE SUPERVISOR
# ---------------------------------------------------------
# We use Pydantic to force the LLM to output one of these exact strings
class Route(BaseModel):
    next: Literal["Search_Specialist", "Fetch_Specialist", "Create_Specialist", "FINISH"]

def supervisor_node(state: AgentState):
    """The Supervisor evaluates the conversation and routes to the next worker."""
    print(f"[Supervisor] Evaluating next step... (waiting 4s to prevent rate limit)")
    time.sleep(4) 
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "You are a Supervisor coordinating: Search_Specialist, Fetch_Specialist, Create_Specialist.\n"
            "Execution rules:\n"
            "1. Analyze the user's original request carefully. Determine the exact sequence of steps required.\n"
            "2. If the user asks to search and then fetch specific records (e.g., 'the second record', 'the last record', or 'all records'), "
            "   first route to Search_Specialist, wait for the results, and then route to Fetch_Specialist, explicitly telling it WHICH IDs to fetch based on the user's request.\n"
            "3. Once the final specialist has completed the user's full request, output FINISH.\n"
            "4. The final output must be the exact JSON data generated by the final specialist."
        )),
        MessagesPlaceholder(variable_name="messages")
    ])
    
    supervisor_chain = prompt | llm.with_structured_output(Route)
    decision = supervisor_chain.invoke({"messages": state["messages"]})
    
    return {"next": decision.next}


# ---------------------------------------------------------
# 5. ASSEMBLE THE MULTI-AGENT GRAPH
# ---------------------------------------------------------
workflow = StateGraph(AgentState)

# Add all our specialized nodes
workflow.add_node("Supervisor", supervisor_node)
workflow.add_node("Search_Specialist", search_node)
workflow.add_node("Fetch_Specialist", fetch_node)
workflow.add_node("Create_Specialist", create_node)

# Every worker reports back to the Supervisor when they are done
workflow.add_edge("Search_Specialist", "Supervisor")
workflow.add_edge("Fetch_Specialist", "Supervisor")
workflow.add_edge("Create_Specialist", "Supervisor")

# The graph evaluates the 'next' variable in the state to decide where to route
workflow.add_conditional_edges(
    "Supervisor",
    lambda state: state["next"],
    {
        "Search_Specialist": "Search_Specialist",
        "Fetch_Specialist": "Fetch_Specialist",
        "Create_Specialist": "Create_Specialist",
        "FINISH": END
    }
)

# Start the workflow at the Supervisor
workflow.add_edge(START, "Supervisor")

multi_agent_app = workflow.compile()


# ---------------------------------------------------------
# 6. EXECUTION & TEST SUITE
# ---------------------------------------------------------
def run_multi_agent(query: str) -> str:
    initial_state = {"messages": [HumanMessage(content=query)]}
    result = multi_agent_app.invoke(initial_state)
    
    # Extract the final output (which came from the last active worker)
    raw_content = result["messages"][-1].content
    
    # Safety parse and clean
    if isinstance(raw_content, list):
        content = raw_content[0].get("text", "")
    else:
        content = raw_content
        
    content = content.strip()
    if content.startswith("```json"): content = content[7:]
    elif content.startswith("```"): content = content[3:]
    if content.endswith("```"): content = content[:-3]
        
    return content.strip()

if __name__ == "__main__":
    test_suite = {
        "MultiAgent_Collaboration": (
            "Search for the top 5 Claim records. "
            "take the entityCode of the first record, and fetch its full details."
        )
    }
    
    print("--- Starting Multi-Agent V3 System ---")
    
    for test_name, query in test_suite.items():
        print(f"\n🚀 Running Test: {test_name}")
        raw_output = run_multi_agent(query)
        
        filename = f"agent_v3_{test_name}.json"
        try:
            parsed_json = json.loads(raw_output)
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(parsed_json, file, indent=4)
            print(f"✅  Success! Output saved to {filename}")
        except json.JSONDecodeError:
            print(f"⚠️ Agent did not return valid JSON. Printing raw output:")
            print(raw_output)