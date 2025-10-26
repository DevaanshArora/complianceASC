import os
import json
import logging
import re
import concurrent.futures
from datetime import datetime
from typing import List, Dict, Any

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel


# Define Pydantic models for structured output (optional)
class Requirement(BaseModel):
    text: str

class ControlSuggestion(BaseModel):
    requirement: str
    controls: List[str]

class ComplianceSection(BaseModel):
    section_id: str
    section_content: str
    requirements: List[str]
    controls: Dict[str, List[str]]


def detect_document_type(text_sample: str) -> str:
    """Detect the compliance document type from sample text."""
    text_lower = text_sample.lower()
    if "iso" in text_lower or "international standard" in text_lower:
        return "ISO"
    elif "digital personal data protection" in text_lower or "data principal" in text_lower:
        return "DPDP"
    elif "rbi" in text_lower or "reserve bank" in text_lower:
        return "RBI"
    else:
        return "GENERAL"


def load_and_chunk_pdf(pdf_path: str) -> List[Document]:
    """Load PDF and split into logical chunks based on document type."""
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    # Get sample text for document type detection
    sample_text = documents[0].page_content[:1000] if documents else ""
    doc_type = detect_document_type(sample_text)

    # Base separators
    separators = [
        "\n\n", "\n", " "  # Fallbacks
    ]

    # Document-specific chunking strategy
    if doc_type == "DPDP":
        # DPDP has sections like 18. (1), chapters, sec. markers
        separators = [
            "\nSEC. ", "\nSection ", "\nCHAPTER ", "\nChapter ",
            "\n\d+\. \(\d+\) ", "\n\d+\. ",  # "18. (1)", "12 "
            "\n1. ", "\n2. ", "\n3. ", "\n4. ", "\n5. ", "\n6. ", "\n7. ", "\n8. ", "\n9. ", "\n10. ",
            "\n11. ", "\n12. ", "\n13. ", "\n14. ", "\n15. ", "\n16. ", "\n17. ", "\n18. ", "\n19. ", "\n20. ",
            "\n21. ", "\n22. ", "\n23. ", "\n24. ", "\n25. ", "\n26. ", "\n27. ", "\n28. ", "\n29. ", "\n30. ",
            "\nAnnex ", "\nBibliography ", "\nAppendix "
        ] + separators
        chunk_size = 2000  # Moderate chunk size for legal content
    elif doc_type == "ISO":
        # ISO standards have systematic numbering with subsections
        separators = [
            "\n\d+\.\d+\.\d+ ", "\n\d+\.\d+ ", "\n\d+\. ",  # Subdivision priority
            "\nAnnex ", "\nBibliography ", "\nNormative references ",
            "\n## ", "\n# "
        ] + separators
        chunk_size = 2500  # Larger sections
    elif doc_type == "RBI":
        separators = [
            "\n\d+\. ", "\n\d+\.\d+ ", "\nChapter ", "\nAnnexure ",
            "\nRegulation ", "\nGuideline "
        ] + separators
        chunk_size = 2200
    else:
        # General compliance documents
        separators = [
            "\n\d+\. ", "\n\d+\.\d+ ", "\nChapter ", "\nSection ", "\nArticle ",
            "\nClause ", "\nANNEX ", "\nAppendix "
        ] + separators
        chunk_size = 2000

    logging.info(f"Detected document type: {doc_type}, using {len(separators)} separators, chunk_size={chunk_size}")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=200,  # Consistent overlap
        separators=separators
    )

    chunks = text_splitter.split_documents(documents)
    logging.info(f"Split into {len(chunks)} chunks")

    # Add section IDs based on content
    for i, chunk in enumerate(chunks):
        lines = chunk.page_content.split('\n')
        if lines:
            first_line = lines[0].strip()
            # More sophisticated section ID detection
            section_id = None
            if doc_type == "DPDP" and any(f"sect" in first_line.lower() or f"sec. " in first_line for f in ["SEC", "Sect"]):
                section_id = f"Section_{i+1}"
            elif any(first_line.startswith(f"{j}.") for j in range(1, 50)) or first_line.isdigit() or "ANNEX" in first_line.upper():
                section_id = first_line
            else:
                section_id = f"section_{i+1}"

            chunk.metadata.update({'section_id': section_id, 'doc_type': doc_type})
        else:
            chunk.metadata.update({'section_id': f"section_{i+1}", 'doc_type': doc_type})

    return chunks


def create_requirement_chain(llm: OllamaLLM):
    """Create the requirement extraction chain."""
    req_prompt = PromptTemplate(
        template="""
        Below is text from compliance document Section {section_number}:

        Section {section_number}: {text}

        Identify all specific requirements in this section. Requirements are mandatory obligations, directives, or compliance clauses that an organization must follow.

        If no clear requirements are present in this text, or if the text doesn't contain meaningful compliance clauses, return an empty array [].

        For each requirement found, provide detailed information in JSON format:

        Output a JSON array where each requirement has:
        - requirement_title: A descriptive title for the requirement
        - article_number: Use the section number provided: "{section_number}"
        - priority: "high", "medium", or "low" based on criticality
        - article_text: The text content from this section
        - requirement: The concise requirement statement
        - requirement_description: A brief description explaining the requirement

        Example:
        [
          {{
            "requirement_title": "Data Protection Compliance",
            "article_number": "{section_number}",
            "priority": "high",
            "article_text": "Full context text here...",
            "requirement": "The owner shall comply with data protection principles",
            "requirement_description": "Entities processing personal data must adhere to protection principles"
          }}
        ]

        Requirements in this section (JSON array):
        """,
        input_variables=["section_number", "text"]
    )

    # Return the chain that outputs JSON
    return req_prompt | llm | JsonOutputParser()


def extract_section_num(section_id: str) -> str:
    """Extract the section number from section_id, e.g., '6.1.2 Determining...' -> '6.1.2'"""
    match = re.search(r'^([0-9]+(?:\.[0-9]+)*)', section_id)
    return match.group(1) if match else None


def create_control_chain(llm: OllamaLLM):
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

        Example:
        [
          {{
            "priority": "high",
            "control_title": "Implement Data Minimization",
            "control": "Collect only necessary personal data and retain for limited periods"
          }}
        ]

        Controls (JSON array):
        """,
        input_variables=["requirement"]
    )

    return ctrl_prompt | llm | JsonOutputParser()


def extract_requirements_from_chunk(req_chain, chunk: Document) -> List[Dict[str, Any]]:
    """Extract requirements from a single chunk."""
    section_id = chunk.metadata.get('section_id', 'unknown')
    section_num = extract_section_num(section_id) or section_id

    try:
        raw_output = req_chain.invoke({
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
        logging.warning(f"Requirement extraction returned non-list for chunk {section_id}: {raw_output}")
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
        logging.error(f"Error extracting controls for requirement: {str(e)}")
        return []


def process_chunk(i, chunk, req_chain, ctrl_chain):
    """Process a single chunk: extract requirements and controls."""
    section_id = chunk.metadata.get('section_id', 'unknown')
    logging.info(f"Processing chunk {i+1}: Section {section_id}")

    # Extract requirements
    requirements = extract_requirements_from_chunk(req_chain, chunk)
    logging.info(f"Extracted {len(requirements)} requirements from chunk {i+1}")

    results = []
    # For each requirement, add controls and append
    for req in requirements:
        controls = extract_controls_for_requirement(ctrl_chain, req)
        req["controls"] = controls
        results.append(req)

    logging.info(f"Processed {len(requirements)} requirements from chunk {i+1}")
    return i, results


def orchestrate_compliance_analysis(pdf_path: str, llm: OllamaLLM, intermediate_filename: str) -> List[Dict[str, Any]]:
    """Main orchestrator with parallel processing."""
    # Load and chunk PDF
    chunks = load_and_chunk_pdf(pdf_path)
    logging.info(f"Loaded and chunked PDF into {len(chunks)} chunks")

    req_chain = create_requirement_chain(llm)
    ctrl_chain = create_control_chain(llm)

    results = {}  # Dictionary to store results by chunk index

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        # Submit all chunk processing tasks
        future_to_chunk = {
            executor.submit(process_chunk, i, chunk, req_chain, ctrl_chain): i
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

    # Flatten final results in chunk order
    final_results = [item for idx in sorted(results.keys()) for item in results[idx]]
    return final_results


def main(pdf_path: str, output_json: str = "compliance_output.json"):
    """Main entry point."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('compliance_agent.log'),
            logging.StreamHandler()
        ]
    )

    logging.info(f"Starting compliance analysis for: {pdf_path}")

    # Create intermediate filename with timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    intermediate_filename = f"intermediate_{timestamp}.json"

    llm = OllamaLLM(
        model="mistral:latest",
        base_url="https://ollama-serve.ascentbusiness.com",
        temperature=0.1  # Low temperature for consistency
    )

    result = orchestrate_compliance_analysis(pdf_path, llm, intermediate_filename)

    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    logging.info(f"Analysis complete. Results saved to {output_json}, intermediate at {intermediate_filename}")
    print(f"Analysis complete. Results saved to {output_json}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python compliance_agent.py <path_to_pdf>")
        sys.exit(1)
    main(sys.argv[1])
