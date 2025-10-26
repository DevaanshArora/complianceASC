# Ascent Compliance Agent Network

An agentic network powered by LangChain that processes compliance documents (ISO22301, ISO27001, DPDP, RBI, etc.) to extract requirements and suggest controls with intelligent multi-document support, parallel processing, and robust error handling.

## Features

- **Multi-Standard Support**: Automatic detection and optimized processing for ISO, DPDP, RBI, and general compliance documents
- **Intelligent Chunking**: Document-type-specific separators and adaptive chunk sizing for optimal section boundaries
- **Parallel Processing**: Concurrent LLM calls with 6-worker thread pools for 3-6x performance improvement
- **Smart Section Mapping**: Automatic article numbering and hierarchical section recognition
- **Robust Error Handling**: Graceful failure management with per-chunk isolation and comprehensive logging
- **Progressive Results**: Timestamped intermediate JSON saves with real-time progress tracking

## Architecture

1. **Document Type Detection**: Analyzes initial content to identify ISO/DPDP/RBI/GENERAL formats
2. **Adaptive Chunking**: Custom separators and sizing based on document structure
3. **Requirement Agent**: Contextual LLM chain requiring strict JSON output with section-aware processing
4. **Control Agent**: Structured control suggestions with priority levels and detailed descriptions
5. **Parallel Orchestrator**: Concurrent processing with result aggregation and checkpointing
6. **Error Recovery**: Independent chunk processing with logging and intermediate saves

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Ensure Ollama server is running with Mistral model

## Usage

```bash
python compliance_agent.py path/to/compliance_document.pdf
```

## Output Structure

```json
[
  {
    "requirement_title": "Data Breach Notification",
    "article_number": "8",
    "priority": "high",
    "article_text": "Full section text...",
    "requirement": "Organization shall notify breaches within 72 hours",
    "requirement_description": "Rapid breach reporting to protect data subjects",
    "controls": [
      {
        "priority": "high",
        "control_title": "Automated Breach Detection System",
        "control": "Implement real-time monitoring and alert systems..."
      }
    ]
  }
]
```

## Output Format

The final output is a JSON array of compliance requirements:

```json
[
  {
    "requirement_title": "Digital Personal Data Processing Compliance",
    "article_number": "3",
    "priority": "high",
    "article_text": "3. Subject to the provisions of this Act...",
    "requirement": "Subject to the provisions of this Act...",
    "requirement_description": "Ensure compliance with the Act for processing digital personal data...",
    "controls": [
      {
        "priority": "high",
        "control_title": "Establish Data Protection Board",
        "control": "18. (1) With effect from such date..."
      }
    ]
  }
]
```

Intermediate results are saved after each chunk as `intermediate_YYYY-MM-DD_HH-MM-SS.json`.

## Dependencies

- langchain: Core framework
- langchain-community: PDF loader
- langchain-ollama: Ollama LLM integration
- pypdf: PDF parsing
- pydantic: Data models
# complianceASC
