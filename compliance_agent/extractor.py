import logging
import concurrent.futures
from typing import List, Dict, Any, Tuple
import json
from datetime import datetime

from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from .config import settings
from .document_loader import extract_section_num
from .models import ComplianceRequirement


def create_llm():
    """Create configured LLM instance based on provider setting."""
    settings.validate_llm_provider()

    if settings.llm_provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=settings.temperature
        )
    else:  # ollama
        from langchain_ollama import OllamaLLM
        return OllamaLLM(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.temperature
        )


def create_requirement_chain(llm, doc_name: str):
    """Create the requirement extraction chain."""
    req_prompt = PromptTemplate(
        template="""
        You are analyzing the "{doc_name}" compliance document.
        Below is text from document Section {section_number}:

        Section {section_number}: {text}

        IMPORTANT: Identify ONLY enforceable COMPLIANCE REQUIREMENTS that organizations MUST follow.
        Requirements are MANDATORY obligations containing enforcement language like:
        - "shall" / "must" / "will" / "is required to"
        - "shall not" / "must not" / "will not"
        - Specific mandates, prohibitions, or mandatory procedures

        DO NOT include:
        - Act titles, names, or introductory statements ("This Act shall be called...")
        - Section headers, chapter titles, or numbering
        - Definitions or explanatory text without enforcement language
        - Historical context or procedural descriptions
        - Permissions, allowances, or discretionary language ("may", "can", "could")
        - General principles without specific mandates

        EXAMPLES of ENFORCEABLE REQUIREMENTS:
        ✓ "Organizations shall implement access controls..."
        ✓ "Personal data shall not be processed without consent..."
        ✓ "The organization shall conduct risk assessments..."

        EXAMPLES to EXCLUDE:
        ✗ "The Act may be called..." (title/name)
        ✗ "This section covers..." (introduction)
        ✗ "Data fiduciary means..." (definition without mandate)
        ✗ "For the purposes of..." (context without obligation)

        If NO enforceable requirements exist in this text, return an empty array [].

        For each REQUIREMENT found, provide detailed information:

        Output a JSON array where each requirement has:
        - requirement_title: A descriptive title for the requirement
        - article_number: Use the section number provided: "{section_number}"
        - priority: "high" for core compliance mandates, "medium" for procedural requirements, "low" for administrative items
        - article_text: The text content from this section
        - requirement: The concise requirement statement (the specific mandate)
        - requirement_description: A brief description of what the requirement means

        Requirements in this section (JSON array, empty [] if none found):
        """,
        input_variables=["doc_name", "section_number", "text"]
    )

    return req_prompt | llm | JsonOutputParser()


def create_control_chain(llm):
    """Create the control suggestion chain."""
    ctrl_prompt = PromptTemplate(
        template="""
        For the following compliance requirement, suggest appropriate controls in JSON format.
        Each control should have priority, control_title, and control description.

        Requirement: {requirement}

        Output a JSON array where each item has:
        - priority: "high", "medium", or "low"
        - control_title: A descriptive title for the control
        - control: Detailed control description

        Suggested Controls (JSON array):
        """,
        input_variables=["requirement"]
    )

    return ctrl_prompt | llm | JsonOutputParser()


def extract_requirements_from_chunk(req_chain, chunk: Document, doc_name: str) -> List[Dict[str, Any]]:
    """Extract requirements from a single chunk."""
    section_id = chunk.metadata.get('section_id', 'unknown')
    section_num = extract_section_num(section_id) or section_id

    try:
        raw_output = req_chain.invoke({
            "doc_name": doc_name,
            "section_number": section_num,
            "text": chunk.page_content
        })
        # raw_output is already the parsed JSON list
        if isinstance(raw_output, list):
            # Override article_number and set article_text for each req
            for req in raw_output:
                req['article_number'] = section_num
                req['article_text'] = chunk.page_content
            return raw_output
        logging.warning(f"Requirement extraction returned non-list for chunk {section_id}")
        return []
    except Exception as e:
        logging.error(f"Error extracting requirements from chunk {section_id}: {str(e)}")
        return []


def extract_controls_for_requirement(ctrl_chain, requirement_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract control suggestions for a single requirement."""
    try:
        raw_output = ctrl_chain.invoke({"requirement": requirement_dict.get("requirement", "")})
        # raw_output is already the parsed JSON list
        if isinstance(raw_output, list):
            return raw_output
        logging.warning(f"Control extraction returned non-list for requirement: {requirement_dict.get('requirement', '')[:50]}...")
        return []
    except Exception as e:
        logging.error(f"Error extracting controls: {str(e)}")
        return []


def process_chunk(i: int, chunk: Document, req_chain, ctrl_chain, doc_name: str) -> Tuple[int, List[Dict[str, Any]]]:
    """Process a single chunk: extract requirements and controls."""
    section_id = chunk.metadata.get('section_id', 'unknown')
    logging.info(f"Processing chunk {i+1}: Section {section_id}")

    # Extract requirements
    requirements = extract_requirements_from_chunk(req_chain, chunk, doc_name)
    logging.info(f"Extracted {len(requirements)} requirements from chunk {i+1}")

    results = []
    # For each requirement, add controls and append
    for req in requirements:
        controls = extract_controls_for_requirement(ctrl_chain, req)
        req["controls"] = controls
        results.append(req)

    logging.info(f"Processed {len(requirements)} requirements from chunk {i+1}")
    return i, results


def orchestrate_compliance_analysis(pdf_path: str, intermediate_filename: str) -> List[ComplianceRequirement]:
    """Main orchestrator with parallel processing."""
    from .document_loader import load_and_chunk_pdf

    # Load and chunk PDF
    doc_type, doc_name, chunks = load_and_chunk_pdf(pdf_path)
    logging.info(f"Loaded and chunked PDF into {len(chunks)} chunks")
    logging.info(f"Document name: {doc_name}")

    llm = create_llm()
    req_chain = create_requirement_chain(llm, doc_name)
    ctrl_chain = create_control_chain(llm)

    results = {}  # Dictionary to store results by chunk index

    with concurrent.futures.ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
        # Submit all chunk processing tasks
        future_to_chunk = {
            executor.submit(process_chunk, i, chunk, req_chain, ctrl_chain, doc_name): i
            for i, chunk in enumerate(chunks)
        }

        # Process completed futures as they finish
        for future in concurrent.futures.as_completed(future_to_chunk):
            chunk_idx, chunk_results = future.result()
            results[chunk_idx] = chunk_results

            # Flatten all completed results in order
            all_results = [item for idx in sorted(results.keys()) for item in results[idx]]

            # Save intermediate results after each chunk completion
            with open(intermediate_filename, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, indent=2, ensure_ascii=False)
            logging.info(f"Updated intermediate results in {intermediate_filename} after {len(results)}/{len(chunks)} chunks")

    # Flatten final results in chunk order and validate models
    final_results = []
    for idx in sorted(results.keys()):
        for req_data in results[idx]:
            try:
                # Try to validate as ComplianceRequirement, skip if invalid
                req = ComplianceRequirement.model_validate(req_data)
                final_results.append(req)
            except Exception as e:
                logging.warning(f"Skipping invalid requirement: {e}")
                logging.debug(f"Invalid data: {req_data}")
                continue

    logging.info(f"Successfully validated {len(final_results)} requirements out of {sum(len(v) for v in results.values())} extracted")
    return final_results
