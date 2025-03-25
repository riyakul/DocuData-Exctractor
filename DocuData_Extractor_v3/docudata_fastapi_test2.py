import logging
import uuid
import tempfile
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Form, UploadFile, File, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from building_code_processor import BuildingCodeProcessor, LLMQueryEngine
import markdown
from pymongo import MongoClient

# Load environment variables from a .env file 
# Load environment variables from a .env file
load_dotenv()

# MongoDB connection string from .env or directly in code
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URL)

# Connect to your database
db = client['building_codes_database']  # You can name it whatever you want



# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("api.log"), logging.StreamHandler()]
)
logger = logging.getLogger("API")

load_dotenv(override=True)

# Initialize FastAPI app
app = FastAPI(title="Building Code Processor")

# Set up templates and static files
templates_dir = Path("templates")
if not templates_dir.exists():
    templates_dir.mkdir(parents=True)

static_dir = Path("static")
if not static_dir.exists():
    static_dir.mkdir(parents=True)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Create output directory
output_dir = Path("./output")
output_dir.mkdir(parents=True, exist_ok=True)

# Store session data with expiration
sessions = {}
SESSION_EXPIRY = timedelta(hours=1)  # Sessions expire after 1 hour

# Data models
class LocationQuery(BaseModel):
    city: str
    state: str
    country: str
    keyword: Optional[str] = None

class CodeSelection(BaseModel):
    session_id: str
    selected_indices: List[int]

class QueryRequest(BaseModel):
    session_id: str
    query: str

# Cleanup expired sessions
def cleanup_expired_sessions():
    """Remove expired sessions and their temporary files."""
    current_time = datetime.now()
    expired_session_ids = []
    for session_id, session_data in sessions.items():
        if current_time > session_data.get("expires_at", current_time):
            # Clean up temporary files
            file_path = session_data.get("file_path")
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Removed temp file for expired session {session_id}")
                except Exception as e:
                    logger.error(f"Error removing temp file: {str(e)}")
            expired_session_ids.append(session_id)
    
    # Remove expired sessions
    for session_id in expired_session_ids:
        del sessions[session_id]
        logger.info(f"Removed expired session {session_id}")

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Render the main page with the location form."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/list-codes")
async def list_codes(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    city: str = Form(...),
    state: str = Form(...),
    country: str = Form(...),
    keyword: Optional[str] = Form(None)
):
    """List available building codes based on location and optional keyword."""
    background_tasks.add_task(cleanup_expired_sessions)
    session_id = str(uuid.uuid4())
    temp_file = f"temp_{session_id}.json"
    try:
        with open(temp_file, "wb") as f:
            f.write(await file.read())
        logger.info(f"Processing request for {city}, {state}, {country} with keyword: {keyword}")
        processor = BuildingCodeProcessor(temp_file)
        available_codes = processor.list_available_codes(city, state, country, keyword)
        sessions[session_id] = {
            "file_path": temp_file,
            "city": city,
            "state": state,
            "country": country,
            "keyword": keyword,
            "available_codes": available_codes,
            "processed": False,
            "expires_at": datetime.now() + SESSION_EXPIRY
        }
        return {
            "session_id": session_id,
            "codes": available_codes,
            "location": f"{city}, {state}, {country}"
        }
    except Exception as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        logger.error(f"Error listing codes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/process-codes")
async def process_codes(selection: CodeSelection):
    """Process selected building codes and generate a report."""
    session_id = selection.session_id
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions[session_id]
    try:
        processor = BuildingCodeProcessor(session["file_path"])
        session["expires_at"] = datetime.now() + SESSION_EXPIRY
        location_codes = processor.filter_by_location(
            session["city"], session["state"], session["country"]
        )
        if not selection.selected_indices:
            raise HTTPException(status_code=400, detail="No codes selected")
        if max(selection.selected_indices) > len(location_codes):
            raise HTTPException(status_code=400, detail="Invalid code index selected")
        pruned_codes, matches = processor.process_selected_codes(
            location_codes, selection.selected_indices, session.get("keyword")
        )
        report = processor.generate_report(pruned_codes, matches)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"report_{session_id}_{timestamp}.txt"
        report_path = output_dir / report_file
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        preview_text = report[:500] + "..." if len(report) > 500 else report
        preview_html = markdown.markdown(preview_text, extensions=['extra', 'codehilite'])
        session["processed"] = True
        session["report_file"] = report_file
        session["report_content"] = report
        session["report_path"] = str(report_path)
        selected_code_details = []
        for i in selection.selected_indices:
            if 1 <= i <= len(session["available_codes"]):
                selected_code_details.append(session["available_codes"][i-1])
        return {
            "session_id": session_id,
            "report_file": report_file,
            "report_preview": preview_text,
            "report_preview_html": preview_html,
            "selected_codes": selected_code_details
        }
    except Exception as e:
        logger.error(f"Error processing codes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/report/{session_id}")
async def get_report(session_id: str):
    """Get the full report content."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions[session_id]
    if not session.get("processed", False):
        raise HTTPException(status_code=400, detail="Report not yet processed")
    session["expires_at"] = datetime.now() + SESSION_EXPIRY
    report_html = markdown.markdown(session["report_content"], extensions=['extra', 'codehilite'])
    return {"report": session["report_content"], "report_html": report_html}

@app.post("/api/query")
async def query_codes(request: QueryRequest):
    """Process an LLM query about the building codes."""
    try:
        if request.session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        session_data = sessions[request.session_id]
        session_data["expires_at"] = datetime.now() + SESSION_EXPIRY
        if not session_data.get("processed", False) or "report_content" not in session_data:
            raise HTTPException(status_code=400, detail="No report available for query")
        api_key = os.getenv("DEEPSEEK_API_KEY")
        logger.info(f"Processing query with API key: {'Available' if api_key else 'Not available'}")
        llm_engine = LLMQueryEngine(api_key=api_key)
        location = f"{session_data['city']}, {session_data['state']}, {session_data['country']}"
        response_markdown = llm_engine.query(
            document_text=session_data['report_content'],
            user_query=request.query,
            location=location
        )
        response_html = markdown.markdown(response_markdown, extensions=['extra', 'codehilite'])
        return {"answer": response_markdown, "answer_html": response_html}
    except Exception as e:
        logger.error(f"Query processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/cleanup/{session_id}")
async def cleanup_session(session_id: str):
    """Clean up session data and temporary files."""
    if session_id in sessions:
        try:
            if os.path.exists(sessions[session_id]["file_path"]):
                os.remove(sessions[session_id]["file_path"])
                logger.info(f"Removed temporary file for session {session_id}")
            del sessions[session_id]
            logger.info(f"Removed session {session_id}")
            return {"status": "success", "message": "Session cleaned up successfully"}
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error cleaning up session: {str(e)}")
    return {"status": "success", "message": "Session not found"}

@app.on_event("startup")
async def startup_event():
    """Initialize app components on startup."""
    logger.info("Starting Building Code Processor API")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown."""
    logger.info("Shutting down Building Code Processor API")
    for session_id, session_data in sessions.items():
        try:
            file_path = session_data.get("file_path")
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.error(f"Error removing temporary file: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
