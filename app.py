#!/usr/bin/env python3
"""
Ascent Compliance Agent Network API Server

Run the FastAPI application for compliance document analysis.
"""

import uvicorn
from compliance_agent.api import app


def main():
    """Start the FastAPI server."""
    # Configure for production
    uvicorn.run(
        "compliance_agent.api:app",
        host="0.0.0.0",
        port=8009,
        reload=True,  # Set to False in production
        log_level="info",
        access_log=True
    )


if __name__ == "__main__":
    main()
