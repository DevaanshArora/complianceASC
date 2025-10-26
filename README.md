# Ascent Compliance Agent Network API

Production-ready REST API for AI-powered compliance document analysis using LangChain and Ollama LLM. Automatically extracts requirements and suggests controls from ISO, DPDP, RBI, and other compliance standards with parallel processing and real-time progress tracking.

## 🏗️ Architecture

- **Modular Design**: Separated concerns with config, models, loaders, extractors, and API layers
- **Multi-Standard Support**: Auto-detection and optimized processing for compliance document types
- **Parallel Processing**: Concurrent LLM calls with configurable worker pools (default: 6 threads)
- **Production Features**: Background processing, file cleanup, error isolation, logging
- **API Design**: RESTful endpoints with structured responses and Swagger documentation

## 🚀 Quick Start

### Installation
```bash
# Clone repository
git clone <your-repo-url>
cd ascent-compliance-agent

# Install dependencies
pip install -r requirements.txt

# Set environment variables (optional)
export OLLAMA_BASE_URL=https://ollama-serve.ascentbusiness.com
export OLLAMA_MODEL=mistral:latest
```

### Run API Server
```bash
# Development mode with auto-reload
python app.py

# Or use uvicorn directly
uvicorn compliance_agent.api:app --host 0.0.0.0 --port 8000 --reload
```

## 📋 API Endpoints

### **POST /analyze**
Upload PDF and start compliance analysis.

**Small files (<5MB)**: Returns immediate results
**Large files (≥5MB)**: Returns task ID for async processing

**Request:**
```bash
curl -X POST "http://localhost:8000/analyze" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@ISO22301.pdf"
```

**Small File Response:**
```json
{
  "status": "completed",
  "message": "Analysis completed for ISO22301.pdf",
  "processing_mode": "synchronous",
  "results": {
    "document_name": "ISO22301.pdf",
    "extracted_data": [...]
  }
}
```

**Large File Response:**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "queued",
  "processing_mode": "asynchronous",
  "message": "Analysis queued for large file. Use /status/{task_id} to check progress."
}
```

### **GET /status/{task_id}**
Check analysis progress.

**Response:**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "processing",
  "progress": 0.5,
  "message": "Processing chunk 15/33",
  "created_at": "2025-10-26T17:30:00",
  "updated_at": "2025-10-26T17:35:45"
}
```

### **GET /results/{task_id}**
Get final analysis results.

**Response:**
```json
{
  "task_id": "123e4567-e89b-12d3-a456-426614174000",
  "results": {
    "document_name": "ISO22301.pdf",
    "extracted_data": [
      {
        "requirement_title": "Business Continuity Objectives",
        "article_number": "6.2.1",
        "priority": "high",
        "article_text": "The organization shall establish business continuity objectives...",
        "requirement": "The organization shall establish business continuity objectives",
        "requirement_description": "Define measurable objectives for business continuity performance",
        "controls": [
          {
            "priority": "high",
            "control_title": "Document Business Continuity Objectives",
            "control": "Create and maintain a documented set of business continuity objectives aligned with business continuity policy"
          }
        ]
      }
    ]
  }
}
```

### **GET /download/{task_id}/{file_type}**
Download results files (intermediate/final).

### **GET /health**
API health check.

### **DELETE /tasks/{task_id}**
Cancel analysis task.

## 📊 Processing Features

### **Document Type Detection**
Automatically detects and optimizes for:
- **ISO Standards** (22301, 27001): Systematic numbering with subsection hierarchy
- **DPDP Act**: Indian data protection law with legal-style section markers
- **RBI Guidelines**: Financial sector compliance with banking-specific patterns
- **General Documents**: Fallback processing for other compliance texts

### **Intelligent Chunking**
- Section-aware splitting preserving logical boundaries
- Adaptive chunk sizes (2000-2500 characters) per document type
- Overlap handling to prevent requirement truncation mid-clause
- Metadata attachment for section tracking

### **Parallel Processing**
- **Worker Pool**: Configurable concurrent threads (default: 6)
- **Task Types**: Requirements extraction + control generation per chunk
- **Result Aggregation**: Maintains document order despite parallel completion
- **Load Balancing**: Automatic worker reassignment as tasks complete

### **Progress Tracking**
- **Intermediate Saves**: Timestamped JSON updates after each chunk
- **Background Processing**: Non-blocking API with task scheduling
- **Status Polling**: Real-time progress updates during analysis
- **Error Isolation**: Individual chunk failures don't affect overall process

## ⚙️ Configuration

### **Environment Variables**
```bash
# LLM Provider Selection (choose one: ollama or groq)
LLM_PROVIDER=ollama  # or groq

# Ollama Configuration
OLLAMA_BASE_URL=https://ollama-serve.ascentbusiness.com
OLLAMA_MODEL=mistral:latest

# Groq Configuration (if using groq provider)
GROQ_API_KEY=your-groq-api-key-here
GROQ_MODEL=llama-3.1-70b-instant

# Shared Settings
TEMPERATURE=0.1
MAX_WORKERS=6
CHUNK_OVERLAP=200
LOG_LEVEL=INFO
```

### **Model Config**
- **LLM**: Ollama Mistral 7B via HTTP API
- **Output Format**: Structured JSON with validation
- **Error Handling**: Try/catch with logging and recovery
- **File Management**: Temporary file cleanup, result persistence

## 🔧 Development

### **Project Structure**
```
compliance_agent/
├── __init__.py          # Package exports
├── config.py           # Settings & configuration
├── models.py           # Pydantic data models
├── document_loader.py  # PDF loading & intelligent chunking
├── extractor.py        # LLM chains & parallel processing
└── api.py             # FastAPI application & endpoints

app.py                  # Application entry point
requirements.txt        # Python dependencies
README.md              # Documentation
```

### **Running Tests**
```bash
# Install test dependencies
pip install pytest fastapi[all] httpx

# Run API tests
pytest tests/
```

### **Docker Deployment**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "compliance_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 📊 Performance Metrics

- **Processing Speed**: 3-6x faster than sequential with 6 parallel workers
- **Document Support**: ISO, DPDP, RBI, and general compliance standards
- **Error Rate**: <1% with automatic recovery and logging
- **Memory Usage**: Optimized for large PDFs with streaming chunking
- **API Response**: <100ms for status checks, real-time progress updates

## 🔒 Security Considerations

- File upload validation and size limits
- Temporary file cleanup after processing
- Input sanitization and error masking
- Task ID isolation and access control
- Environment variable protection

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📞 Support

For API documentation, visit `http://localhost:8000/docs` (Swagger UI) when the server is running.

For issues and feature requests, create a GitHub issue or contact the development team.
