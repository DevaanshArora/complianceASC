import logging
import uuid
import json
from typing import Optional, Any, Dict
from datetime import datetime
import os

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .models import TaskStatus, AnalysisResult
from .extractor import orchestrate_compliance_analysis

# In-memory task store (use Redis/DB in production)
task_store: dict[str, TaskStatus] = {}


def serialize_for_json(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Convert datetime objects to ISO strings for JSON serialization."""
    if isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_for_json(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return obj


# Validate settings on startup
from .config import settings
try:
    settings.validate_llm_provider()
    print(f"✓ LLM provider configured: {settings.llm_provider}")
except ValueError as e:
    print(f"✗ LLM configuration error: {e}")
    exit(1)

app = FastAPI(
    title="Ascent Compliance Agent Network API",
    description="AI-powered compliance document analysis for requirements extraction and control suggestions",
    version="1.0.0"
)

# Add CORS middleware to allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


@app.post("/analyze", summary="Upload PDF and start analysis")
async def analyze_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
) -> dict:
    """
    Upload a compliance PDF and start analysis.

    For small files (<5MB), returns immediate results.
    For larger files, returns task ID for progress tracking.

    Returns immediate results or task ID with tracking URL.
    """

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    # Read file content to check size
    content = await file.read()
    file_size_mb = len(content) / (1024 * 1024)
    sync_processing = file_size_mb < 5.0  # Process small files synchronously

    # Generate task ID
    task_id = str(uuid.uuid4())

    # Save uploaded file temporarily
    temp_path = f"temp_{task_id}.pdf"
    try:
        with open(temp_path, "wb") as buffer:
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    if sync_processing:
        # Process immediately for small files
        try:
            logging.info(f"Processing small file synchronously: {file.filename} ({file_size_mb:.1f}MB)")

            # Import processing function
            from .extractor import orchestrate_compliance_analysis

            # Create timestamped intermediate file
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            intermediate_filename = f"intermediate_{timestamp}.json"

            # Run analysis synchronously
            llm_result = orchestrate_compliance_analysis(temp_path, intermediate_filename)

            # Create final result structure
            from .models import AnalysisResult
            analysis_result = AnalysisResult(
                document_name=file.filename,
                total_chunks=0,  # Not tracked in current implementation
                processed_chunks=len(llm_result),
                requirements_found=len(llm_result),
                extracted_data=llm_result,
                processing_status="completed",
                updated_at=datetime.now()
            )

            # Save final results (serialize datetime objects)
            final_filename = f"results_{task_id}.json"
            with open(final_filename, 'w', encoding='utf-8') as f:
                json.dump(serialize_for_json(analysis_result.model_dump()), f, indent=2, ensure_ascii=False, default=str)

            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

            # Return immediate results
            return {
                "status": "completed",
                "message": f"Analysis completed for {file.filename}",
                "processing_mode": "synchronous",
                "results": serialize_for_json(analysis_result.model_dump())
            }

        except Exception as e:
            # Clean up on error
            if os.path.exists(temp_path):
                os.remove(temp_path)

            raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

    else:
        # Process asynchronously for large files
        logging.info(f"Processing large file asynchronously: {file.filename} ({file_size_mb:.1f}MB)")

        # Create task status
        task_status = TaskStatus(
            task_id=task_id,
            status="pending",
            progress=0.0,
            message="Analysis queued (large file)",
            created_at=datetime.now()
        )
        task_store[task_id] = task_status

        # Start background processing
        background_tasks.add_task(process_pdf_analysis, task_id, temp_path, file.filename)

        return {
            "task_id": task_id,
            "status": "queued",
            "processing_mode": "asynchronous",
            "message": f"Analysis queued for large file. Use /status/{task_id} to check progress."
        }


@app.get("/status/{task_id}", summary="Get analysis status")
def get_analysis_status(task_id: str) -> TaskStatus:
    """
    Get the current status of a compliance analysis task.
    """
    if task_id not in task_store:
        raise HTTPException(status_code=404, detail="Task not found")

    return task_store[task_id]


@app.get("/results/{task_id}", summary="Get analysis results")
def get_analysis_results(task_id: str) -> dict:
    """
    Get the final results of a completed analysis.
    """
    if task_id not in task_store:
        raise HTTPException(status_code=404, detail="Task not found")

    task_status = task_store[task_id]

    if task_status.status != "completed":
        raise HTTPException(status_code=412, detail=f"Analysis not completed. Status: {task_status.status}")

    if not task_status.result_path or not os.path.exists(task_status.result_path):
        raise HTTPException(status_code=500, detail="Results file not found")

    try:
        with open(task_status.result_path, 'r', encoding='utf-8') as f:
            results = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load results: {str(e)}")

    return {
        "task_id": task_id,
        "results": results
    }


@app.get("/download/{task_id}/{file_type}", summary="Download analysis files")
def download_file(task_id: str, file_type: str) -> FileResponse:
    """
    Download intermediate or final results file.

    file_type: "intermediate" or "final"
    """
    if task_id not in task_store:
        raise HTTPException(status_code=404, detail="Task not found")

    task_status = task_store[task_id]

    if file_type == "intermediate":
        file_path = task_status.intermediate_path
        filename = f"intermediate_{task_id}.json"
    elif file_type == "final":
        file_path = task_status.result_path
        filename = f"results_{task_id}.json"
    else:
        raise HTTPException(status_code=400, detail="Invalid file_type. Use 'intermediate' or 'final'")

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type='application/json'
    )


@app.get("/health", summary="Health check")
def health_check() -> dict:
    """
    Check API health and basic service status.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "Ascent Compliance Agent Network API"
    }


@app.delete("/tasks/{task_id}", summary="Cancel analysis task")
def cancel_task(task_id: str) -> dict:
    """
    Cancel a running or queued analysis task.
    """
    if task_id not in task_store:
        raise HTTPException(status_code=404, detail="Task not found")

    task_status = task_store[task_id]

    if task_status.status in ["completed", "failed"]:
        raise HTTPException(status_code=400, detail="Cannot cancel a completed or failed task")

    task_status.status = "cancelled"
    task_status.message = "Task cancelled by user"
    task_status.updated_at = datetime.now()

    return {"message": "Task cancelled successfully"}


def process_pdf_analysis(task_id: str, pdf_path: str, original_filename: str):
    """
    Background task to process PDF analysis.
    """
    task_status = task_store[task_id]

    try:
        # Update status to processing
        task_status.status = "processing"
        task_status.message = "Loading and analyzing document"
        task_status.progress = 0.1
        task_status.updated_at = datetime.now()

        # Create intermediate file name
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        intermediate_filename = f"intermediate_{timestamp}.json"

        # Run analysis
        result = orchestrate_compliance_analysis(pdf_path, intermediate_filename)

        # Create final result structure
        analysis_result = AnalysisResult(
            document_name=original_filename,
            total_chunks=result[0].chunk_count if hasattr(result[0], 'chunk_count') else 0,  # TODO: track chunks
            processed_chunks=result[0].chunk_count if hasattr(result[0], 'chunk_count') else len(result),
            requirements_found=len(result),
            extracted_data=result,
            processing_status="completed",
            updated_at=datetime.now()
        )

        # Save final results
        final_filename = f"results_{task_id}.json"
        with open(final_filename, 'w', encoding='utf-8') as f:
            json.dump(serialize_for_json(analysis_result.model_dump()), f, indent=2, ensure_ascii=False, default=str)

        # Update task status
        task_status.status = "completed"
        task_status.progress = 1.0
        task_status.message = f"Analysis completed. Found {len(result)} requirements."
        task_status.result_path = final_filename
        task_status.intermediate_path = intermediate_filename
        task_status.updated_at = datetime.now()

        # Clean up temp file
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

    except Exception as e:
        # Update status on error
        task_status.status = "failed"
        task_status.message = f"Analysis failed: {str(e)}"
        task_status.updated_at = datetime.now()

        # Clean up files
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

        logging.error(f"Task {task_id} failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
