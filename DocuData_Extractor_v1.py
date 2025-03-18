import streamlit as st
import json
import re
from pymongo import MongoClient
from bson import ObjectId

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

def display_raw_json(document, header="Raw JSON Document"):
    """Display raw JSON data inside a collapsible expander."""
    with st.expander(header):
        st.json(document)

def prune_document(node, search_term):
    """
    Recursively filter the document.
    If the search term is found in a node’s 'title', 'chapter', or 'content',
    return the entire node; otherwise, only branches that contain a match.
    """
    if isinstance(node, dict):
        direct_match = any(
            key in node and isinstance(node[key], str) and search_term.lower() in node[key].lower()
            for key in ["chapter", "title", "content"]
        )
        if direct_match:
            return node
        pruned = {}
        for k, v in node.items():
            filtered = prune_document(v, search_term)
            if filtered is not None:
                pruned[k] = filtered
        return pruned if pruned else None

    elif isinstance(node, list):
        pruned_list = []
        for item in node:
            filtered_item = prune_document(item, search_term)
            if filtered_item is not None:
                pruned_list.append(filtered_item)
        return pruned_list if pruned_list else None

    elif isinstance(node, str):
        return node if search_term.lower() in node.lower() else None

    return None

# -----------------------------------------------------------------------------
# LLM Integration (DeepSeek v3)
# -----------------------------------------------------------------------------
def trigger_llm_call():
    """
    Trigger the LLM call using the current document, user query, and search key.
    The pruned context is stored in session_state["pruned_context"].
    The final LLM answer is stored in session_state["llm_response"].
    """
    user_query = st.session_state.get("llm_user_query", "").strip()
    search_key = st.session_state.get("llm_search_key", "").strip()
    if not user_query or not search_key:
        st.error("Both query and search key are required.")
        return

    current_doc = st.session_state.get("current_document")
    if not current_doc:
        st.error("No document found. Please load a document first.")
        return

    # Prune the document based on the search key.
    pruned_context = prune_document(current_doc, search_key)
    st.session_state["pruned_context"] = pruned_context

    if pruned_context:
        context_str = json.dumps(pruned_context, indent=2)
    else:
        context_str = "No relevant context found."

    prompt = f"""You are a legal assistant. Use the context provided below to answer the user's question accurately. 
If the context does not provide sufficient details, please indicate that.

Context:
{context_str}

Question: {user_query}

Answer:"""

    with st.spinner("Loading response..."):
        from openai import OpenAI
        client = OpenAI(
            api_key="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",  # <-- Replace with your own key
            base_url="https://openrouter.ai/api/v1",
        )
        chat = client.chat.completions.create(
            model="deepseek/deepseek-chat:free",
            messages=[{"role": "user", "content": prompt}]
        )
        if chat and chat.choices and chat.choices[0].message:
            st.session_state["llm_response"] = chat.choices[0].message.content
        else:
            st.session_state["llm_response"] = "No response."

# -----------------------------------------------------------------------------
# Reset function to clear old data
# -----------------------------------------------------------------------------
def reset_app_state():
    """
    Clears out previous selections and results.
    Because Streamlit automatically re-runs on widget changes,
    we don't need an explicit rerun call here.
    """
    keys_to_clear = [
        "current_document",
        "pruned_context",
        "llm_response",
        "llm_user_query",
        "llm_search_key",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]

# =============================================================================
# MAIN APPLICATION
# =============================================================================
st.set_page_config(page_title="DocuData Extractor", layout="wide")

# Track old selections to detect changes
if "old_doc_source" not in st.session_state:
    st.session_state["old_doc_source"] = None
if "old_mongo_file" not in st.session_state:
    st.session_state["old_mongo_file"] = None
if "old_upload_json" not in st.session_state:
    st.session_state["old_upload_json"] = None

# -----------------------------------------------------------------------------
# SIDEBAR: Choose Document Source
# -----------------------------------------------------------------------------
st.sidebar.title("Document Source")
st.sidebar.info("Select how you want to load the document: from MongoDB or by uploading a JSON file.")

doc_source = st.sidebar.radio(
    "Choose Document Source:",
    ("MongoDB", "Upload JSON"),
    key="doc_source"
)

# If doc_source changed from old to new, reset the app
if st.session_state["old_doc_source"] is not None and doc_source != st.session_state["old_doc_source"]:
    reset_app_state()
st.session_state["old_doc_source"] = doc_source

# -----------------------------------------------------------------------------
# If user chooses MongoDB
# -----------------------------------------------------------------------------
if doc_source == "MongoDB":
    st.sidebar.markdown("### MongoDB Document Selection")
    try:
        MONGO_CONN_STR = (
            "mongodb+srv://riyamkulkarni:sGStH59h0EPjdgcc@jsoncluster.yjuh1.mongodb.net/"
            "?retryWrites=true&w=majority&appName=JsonCluster"
        )
        DATABASE_NAME = "myAtlasDB"
        client = MongoClient(MONGO_CONN_STR)
        db = client[DATABASE_NAME]
        collection_names = db.list_collection_names()
    except Exception as e:
        st.sidebar.error(f"Error connecting to MongoDB: {e}")
        st.stop()

    if not collection_names:
        st.sidebar.warning("No collections found in the database.")
        st.stop()

    # Build a mapping from collection names to country/state
    country_state_mapping = {}
    for coll in collection_names:
        parts = coll.split('-')
        if parts[-1].endswith(".json"):
            parts[-1] = parts[-1].replace(".json", "")
        if len(parts) >= 2:
            country = parts[0]
            state = "No_State" if len(parts) == 2 else parts[1]
            file_label = parts[1] if len(parts) == 2 else "-".join(parts[2:]) if len(parts) > 2 else "Unknown_File"
            country_state_mapping.setdefault(country, {}).setdefault(state, {})[coll] = file_label
        else:
            st.sidebar.info(f"Collection '{coll}' does not match expected naming. Skipping.")

    st.sidebar.markdown("## Select Document")
    countries = sorted(country_state_mapping.keys())
    selected_country = st.sidebar.selectbox("Select a country", options=["--Select--"] + countries, key="mongo_country")
    if selected_country and selected_country != "--Select--":
        states = sorted(country_state_mapping[selected_country].keys())
        if states == ["No_State"]:
            files_dict = country_state_mapping[selected_country]["No_State"]
            file_options = list(files_dict.items())
            file_selection = st.sidebar.selectbox(
                "Select a file",
                options=[("--Select--", None)] + file_options,
                format_func=lambda x: x[1] if x[0] != "--Select--" else x[0],
                key="mongo_file"
            )
            # If user changes file, reset old data
            if (st.session_state["old_mongo_file"] is not None 
                and file_selection is not None
                and file_selection[0] != st.session_state["old_mongo_file"]):
                reset_app_state()
            if file_selection and file_selection[0] != "--Select--":
                st.session_state["old_mongo_file"] = file_selection[0]
                collection_name, _ = file_selection
                # Load doc if not already loaded
                if "current_document" not in st.session_state:
                    try:
                        doc = db[collection_name].find_one()
                        if doc:
                            st.session_state["current_document"] = convert_object_ids(doc)
                    except Exception as e:
                        st.sidebar.error(f"Error retrieving data: {e}")
        else:
            selected_state = st.sidebar.selectbox("Select a state", options=["--Select--"] + states, key="mongo_state")
            if selected_state and selected_state != "--Select--":
                files_dict = country_state_mapping[selected_country][selected_state]
                file_options = list(files_dict.items())
                file_selection = st.sidebar.selectbox(
                    "Select a file",
                    options=[("--Select--", None)] + file_options,
                    format_func=lambda x: x[1] if x[0] != "--Select--" else x[0],
                    key="mongo_file_state"
                )
                # If user changes file, reset old data
                if (st.session_state["old_mongo_file"] is not None 
                    and file_selection is not None 
                    and file_selection[0] != st.session_state["old_mongo_file"]):
                    reset_app_state()
                if file_selection and file_selection[0] != "--Select--":
                    st.session_state["old_mongo_file"] = file_selection[0]
                    collection_name, _ = file_selection
                    if "current_document" not in st.session_state:
                        try:
                            doc = db[collection_name].find_one()
                            if doc:
                                st.session_state["current_document"] = convert_object_ids(doc)
                        except Exception as e:
                            st.sidebar.error(f"Error retrieving data: {e}")

# -----------------------------------------------------------------------------
# If user chooses "Upload JSON"
# -----------------------------------------------------------------------------
else:
    st.sidebar.markdown("### Upload Your JSON Document")
    uploaded_file = st.sidebar.file_uploader("Upload a JSON file", type=["json"], key="uploaded_json_file")
    # If user changes or removes the uploaded file, reset old data
    if (st.session_state["old_upload_json"] is not None 
        and uploaded_file != st.session_state["old_upload_json"]):
        reset_app_state()
    if uploaded_file:
        st.session_state["old_upload_json"] = uploaded_file
        # If not already loaded doc, then load it
        if "current_document" not in st.session_state:
            try:
                doc = json.load(uploaded_file)
                st.session_state["current_document"] = convert_object_ids(doc)
                st.sidebar.success("Document loaded successfully.")
            except Exception as e:
                st.sidebar.error("Error processing uploaded document: " + str(e))

# =============================================================================
# MAIN PAGE
# =============================================================================
st.title("DocuData Extractor")

if "current_document" in st.session_state:
    st.subheader("Loaded Document (Raw)")
    with st.expander("View Document JSON"):
        st.json(st.session_state["current_document"])

    st.markdown("---")
    st.subheader("LLM Query Integration")
    st.info("Enter your question and the search key. The search key is used to prune the document to relevant context.")
    st.text_input("Enter your query:", key="llm_user_query")
    st.text_input("Enter search key for context (press Enter when done):", key="llm_search_key", on_change=trigger_llm_call)

    if "pruned_context" in st.session_state and st.session_state["pruned_context"]:
        with st.expander("Show Raw Pruned Data"):
            st.json(st.session_state["pruned_context"])

    if "llm_response" in st.session_state:
        st.subheader("LLM Response")
        st.write(st.session_state["llm_response"])
else:
    st.info("Please use the sidebar to select or upload a document. Once loaded, it will appear here.")