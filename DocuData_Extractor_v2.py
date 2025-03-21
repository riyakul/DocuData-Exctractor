import os
import time
from dotenv import load_dotenv
import streamlit as st
import json
from pymongo import MongoClient
from bson import ObjectId
import gridfs

# Load environment variables from .env file
# load_dotenv()
# api_key = os.environ.get("DEEPSEEK_API_KEY")
# if not api_key:
#     raise ValueError("API key is not set in the .env file!")

#SECRETS METHOD
try:
    api_key = st.secrets["DEEPSEEK_API_KEY"]
except KeyError:
    st.error("API key is not set in the secrets!")
    st.stop()


# =============================================================================
# Helper Functions
# =============================================================================
def convert_object_ids(doc):
    """Recursively convert ObjectIds to strings."""
    if isinstance(doc, dict):
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                doc[key] = str(value)
            elif isinstance(value, (dict, list)):
                convert_object_ids(value)
    elif isinstance(doc, list):
        for i, item in enumerate(doc):
            if isinstance(item, ObjectId):
                doc[i] = str(item)
            elif isinstance(item, (dict, list)):
                convert_object_ids(item)
    return doc

def check_filter_presence(doc_str, f):
    """
    For a given filter f and document string doc_str:
    - If f is a list, return True if any element in f is present in doc_str.
    - Otherwise, return True if f is present in doc_str.
    """
    if isinstance(f, list):
        return any(x.lower() in doc_str.lower() for x in f)
    else:
        return f.lower() in doc_str.lower()

def prune_document(doc, filters):
    """
    Recursively prune the document based on filters.
    For each node, if its string representation contains every non-empty filter,
    keep the node (and recursively its children). Otherwise, return None.
    """
    folder_keys = {"chapters", "sections", "subsections", "titles", "content"}
    
    if isinstance(doc, dict):
        # Check if this dict is a "folder" and if any of its children match.
        for key in folder_keys:
            if key in doc and isinstance(doc[key], list):
                for child in doc[key]:
                    if prune_document(child, filters) is not None:
                        return doc

        doc_str = " ".join(str(v) for v in doc.values())
        if all(check_filter_presence(doc_str, f) for f in filters if f):
            pruned = {}
            for k, v in doc.items():
                child = prune_document(v, filters)
                if child is not None:
                    pruned[k] = child
            return pruned if pruned else doc
        else:
            return None

    elif isinstance(doc, list):
        pruned_list = [prune_document(item, filters) for item in doc]
        pruned_list = [item for item in pruned_list if item is not None]
        return pruned_list if pruned_list else None

    elif isinstance(doc, str):
        return doc if all(check_filter_presence(doc, f) for f in filters if f) else None
    else:
        return doc

def group_by_code_type(doc):
    """
    Traverse the pruned document and group entries by their 'codeType' field.
    Returns a dict mapping each code type to a list of matching entries.
    """
    groups = {}

    def traverse(node):
        if isinstance(node, dict):
            if "codeType" in node:
                ct = node["codeType"]
                if ct not in groups:
                    groups[ct] = []
                groups[ct].append(node)
            for value in node.values():
                traverse(value)
        elif isinstance(node, list):
            for item in node:
                traverse(item)

    traverse(doc)
    return groups

def trigger_llm_call():
    """
    Trigger the LLM call using the filtered document and user's query.
    If no data matches the filters, we ask for suggestions to adjust them.
    Otherwise, we group the data by codeType and present it to the LLM.
    We set temperature=0 for consistent answers on repeated queries.
    """
    user_query = st.session_state.get("llm_user_query", "").strip()
    if not user_query:
        st.error("Please enter a question.")
        return

    # Gather filter values from session state
    address_str = st.session_state.get("user_address", "").strip()
    project_id  = st.session_state.get("selected_project_type_id", "")
    building_id = st.session_state.get("selected_building_type_id", "")

    # Derive region and country from the address (last two comma-separated parts)
    splitted = [x.strip() for x in address_str.split(",") if x.strip()]
    derived_country = splitted[-1] if len(splitted) >= 1 else ""
    derived_region  = splitted[-2] if len(splitted) >= 2 else ""

    # Store them in session_state for reference
    st.session_state["derived_country"] = derived_country
    st.session_state["derived_region"]  = derived_region

    # Combine filters for free-text matching
    filters = [address_str, derived_country, derived_region, project_id, building_id]

    if "current_document" not in st.session_state:
        st.error("No document loaded!")
        return

    current_doc = st.session_state["current_document"]
    pruned_context = prune_document(current_doc, filters)
    st.session_state["pruned_context"] = pruned_context

    if not pruned_context:
        # If no matching context is found, ask the LLM for suggestions to adjust filters.
        suggestion_prompt = f"""You are a legal assistant specialized in building codes.
The user’s query is: "{user_query}"
No relevant document data was found based on these filter inputs:
- Derived Country: {derived_country or 'Not found'}
- Derived Region: {derived_region or 'Not found'}
- Project Type ID: {project_id or 'Not provided'}
- Building Type ID: {building_id or 'Not provided'}
- Full Address: {address_str or 'Not provided'}

Please suggest filter adjustments or additional details that may help retrieve relevant context. 
Provide the suggestions as a numbered list."""
        with st.spinner("Generating filter adjustment suggestions..."):
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )
            chat = client.chat.completions.create(
                model="deepseek/deepseek-chat:free",
                messages=[{"role": "user", "content": suggestion_prompt}],
                temperature=0
            )
            if chat and chat.choices and chat.choices[0].message:
                st.session_state["llm_response"] = chat.choices[0].message.content
            else:
                st.session_state["llm_response"] = "No suggestions provided."
        return

    # Group the pruned context by code type
    grouped_context = group_by_code_type(pruned_context)

    # Build a context string by printing each code type group that has data
    grouped_context_str = ""
    for ct, entries in grouped_context.items():
        if entries:
            grouped_context_str += f"\n\n=== Code Type: {ct} ===\n"
            grouped_context_str += json.dumps(entries, indent=2)

    # Build a prompt referencing the derived country/region
    prompt = f"""You are a legal assistant specialized in building codes.
Please produce consistent answers each time the same query is asked.
We derived:
- Country: {derived_country or 'Unknown'}
- Region/State: {derived_region or 'Unknown'}

Below is the filtered JSON data, grouped by codeType.
Please provide all relevant rules and regulations under each codeType heading in a well-structured, readable format. 
Also clearly mention for which country and region the answer is derived, and ensure numerical accuracy.

Context:
{grouped_context_str}

Question: {user_query}

Answer:
"""

    with st.spinner("Loading response..."):
        from openai import OpenAI
        client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        chat = client.chat.completions.create(
            model="deepseek/deepseek-chat:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        if chat and chat.choices and chat.choices[0].message:
            st.session_state["llm_response"] = chat.choices[0].message.content
        else:
            st.session_state["llm_response"] = "No response."

def reset_app_state():
    """Reset the session state for filters and queries."""
    keys_to_clear = [
        "current_document", "pruned_context", "user_address",
        "selected_project_type", "selected_project_type_id",
        "selected_building_type", "selected_building_type_id",
        "llm_user_query", "llm_response",
        "derived_country", "derived_region"
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.experimental_rerun()

# =============================================================================
# MAIN APPLICATION SETUP
# =============================================================================
st.set_page_config(page_title="DocuData Extractor", layout="wide")
# Bigger header at the top with horizontal line separation
st.markdown("<h1 style='font-size: 3em; text-align: center;'>DocuData Extractor</h1>", unsafe_allow_html=True)
st.markdown("<hr>", unsafe_allow_html=True)

# Always load the document from GridFS using a fixed filename.
MONGO_CONN_STR = (
    "mongodb+srv://riyamkulkarni:sGStH59h0EPjdgcc@jsoncluster.yjuh1.mongodb.net/"
    "?retryWrites=true&w=majority&appName=JsonCluster"
)
DATABASE_NAME = "CombinedJson"
try:
    client = MongoClient(MONGO_CONN_STR)
    db = client[DATABASE_NAME]
    fs = gridfs.GridFS(db)
except Exception as e:
    st.error(f"Error connecting to MongoDB/ GridFS: {e}")
    st.stop()

fixed_filename = "D:\\Augrade\\codes_db_final (3).json"
if "current_document" not in st.session_state:
    try:
        grid_file = fs.find_one({"filename": fixed_filename})
        if grid_file:
            raw = grid_file.read()
            doc = json.loads(raw)
            st.session_state["current_document"] = convert_object_ids(doc)
            st.success("Document loaded from GridFS.")
        else:
            st.error(f"No GridFS file found with filename: {fixed_filename}")
            st.stop()
    except Exception as e:
        st.error(f"Error reading GridFS file: {e}")
        st.stop()

# -----------------------------------------------------------------------------
# SIDEBAR FILTERS (Enter details, Project Type, Building Type)
# -----------------------------------------------------------------------------
st.sidebar.header("Enter details")
# Text input with placeholder for sample address format
st.sidebar.text_input(
    "Enter address:", 
    key="user_address", 
    placeholder="HouseNo.,Street,Area,City,State,Country"
)

# --- Project Type Dropdown ---
doc = st.session_state["current_document"]
if "projectTypes" in doc:
    project_options = [(pt["name"], pt["id"]) for pt in doc["projectTypes"]]
    project_names = ["--Select--"] + [name for name, _ in project_options]
    selected_project_type = st.sidebar.selectbox(
        "Select Project Type", 
        options=project_names, 
        key="selected_project_type"
    )
    if selected_project_type != "--Select--":
        for name, ptid in project_options:
            if name == selected_project_type:
                st.session_state["selected_project_type_id"] = ptid
                break

# --- Building Type Dropdown (always shown) ---
if "buildingTypes" in doc:
    # Filter by project type if selected; otherwise, show all building types.
    if st.session_state.get("selected_project_type_id"):
        building_options = [(bt["name"], bt["id"]) for bt in doc["buildingTypes"] if bt.get("projectTypeId") == st.session_state["selected_project_type_id"]]
    else:
        building_options = [(bt["name"], bt["id"]) for bt in doc["buildingTypes"]]
    building_names = ["--Select--"] + [name for name, _ in building_options]
    selected_building_type = st.sidebar.selectbox(
        "Select Building Type", 
        options=building_names, 
        key="selected_building_type"
    )
    if selected_building_type != "--Select--":
        for name, btid in building_options:
            if name == selected_building_type:
                st.session_state["selected_building_type_id"] = btid
                break

# Add a reset button in the sidebar
if st.sidebar.button("Reset"):
    reset_app_state()

# -----------------------------------------------------------------------------
# MAIN PAGE CONTENT
# -----------------------------------------------------------------------------
st.markdown("<h2 style='font-size: 2em;'>Ask me</h2>", unsafe_allow_html=True)
# Text input for user's question
st.text_input("Enter your question:", key="llm_user_query")

# Button to get LLM answer
if st.button("Get LLM Answer"):
    trigger_llm_call()
    # Optionally show pruned data if it exists (for debugging)
    if "pruned_context" in st.session_state and st.session_state["pruned_context"]:
        st.markdown("<h3 style='font-size: 1.5em;'>Filtered Data (Pruned)</h3>", unsafe_allow_html=True)
        st.json(st.session_state["pruned_context"])
    # Show LLM response if available
    if "llm_response" in st.session_state:
        st.markdown("<h3 style='font-size: 1.5em;'>LLM Response</h3>", unsafe_allow_html=True)
        st.write(st.session_state["llm_response"])
