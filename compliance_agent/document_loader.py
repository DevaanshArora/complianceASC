import logging
import re
from typing import List

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from .config import settings


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


def extract_document_name(text: str) -> str:
    """Extract document/act name from text."""
    import re

    # Look for common patterns in compliance documents
    patterns = [
        r'(?:Act|Bill|Standard|Regulation)(?:\s+(?:called|known|as|of))?\s*["\']?([^"\'\n]{10,80})(?:["\']|\.)',
        r'THE\s+([A-Z][^,\n]{10,80})(?:\s+ACT|\s+BILL)',
        r'INTERNATIONAL\s+STANDARD\s+([^,\n]{10,80})',
        r'(\b[A-Z][A-Z\s]+(?:ACT|BILL|STANDARD|REGULATION)[''"?]?\s*[^,\n]{0,50})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Clean up common artifacts
            name = re.sub(r'\s+', ' ', name)
            if len(name) > 10 and len(name) < 100:
                return name

    return "Compliance Document"  # Default fallback


def load_and_chunk_pdf(pdf_path: str) -> tuple[str, str, List[Document]]:
    """Load PDF and split into logical chunks based on document type."""
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    # Get sample text for document type detection
    sample_text = documents[0].page_content[:2000] if documents else ""
    doc_type = detect_document_type(sample_text)
    doc_name = extract_document_name(sample_text)

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
        chunk_overlap=settings.chunk_overlap,  # Consistent overlap
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

    return doc_type, doc_name, chunks


def extract_section_num(section_id: str) -> str:
    """Extract the section number from section_id, e.g., '6.1.2 Determining...' -> '6.1.2'"""
    match = re.search(r'^([0-9]+(?:\.[0-9]+)*)', section_id)
    return match.group(1) if match else None
