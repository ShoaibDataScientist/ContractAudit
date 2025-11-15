AI Document Intelligence System
Overview

ContractAudit is an AI-powered tool that automates the evaluation of Request for Proposal (RFP) documents and vendor responses.  The tool implements LlamaParse, FAISS, OCR, and Large Language Models (LLMs) to extract, compare, and assess contracts intelligently. It highlights gaps, generates scores, and produces detailed audit reports — reducing the manual effort and improving consistency in contract review.

Key Features

Here are the three main features of ContractAudit:

Intelligent Document Processing

Supports uploading RFPs and vendor responses in a variety of formats (PDF, DOC, DOCX, image files).

Uses LlamaParse to parse structured content like tables, and Tesseract OCR for image-based text extraction.

Converts unstructured contract text into clean, analyzable representations.

Semantic Search & Gap Analysis

Indexes parsed documents using FAISS, enabling fast semantic retrieval.

Compares RFP requirements against vendor responses using LLM-based agents.

Detects and classifies “gaps” in responses (e.g., missing features, misalignment) and rates their severity (low, medium, high).

Automated Scoring & Report Generation

Assigns a gap score to each proposal. Uses a threshold (e.g., > 20% discrepancy) to mark responses as Rejected or Accepted.
![Demo](Assets/Report.PNG)


Generates a comprehensive HTML report that includes:

Executive summary

Checklist of RFP requirements

Gap analysis breakdown

Key insights & trends

Comparative strengths of vendor responses

Provides downloadable reports for offline review and sharing.

Backend / Architecture

Here's a high-level explanation of the backend architecture and how it works under the hood:

Flask Server:

Serves as the core application backend.

Handles file uploads, processing pipelines, analysis work, and report generation.

Modular design with separate components for parsing, retrieval, analysis, and reporting.

Document Processing Layer:

Documents (RFPs and responses) are fed into LlamaParse to extract structured data (text blocks, tables).

For image-based documents, Tesseract OCR is used to extract text.

Parsed content is normalized and prepared for semantic indexing.

Semantic Indexing (FAISS):

Uses FAISS (Facebook AI Similarity Search) to build a vector index of parsed document content.

Embeddings (generated via LLM or embedding model) are stored to enable fast, semantic retrieval of RFP sections relevant to vendor responses.

Analysis & Gap Detection:

LLM-based agents compare the RFP document and vendor response.

They identify missing or misaligned information (gaps) and categorize their severity (low, medium, high).

The system computes a gap score reflecting how well the proposal matches the RFP.

![Demo](https://raw.githubusercontent.com/ShoaibDataScientist/ContractAudit/main/screenshots/report.png)


Scoring & Decision Logic:

Based on the computed gap score, it applies configurable thresholds to decide whether a proposal is Accepted or Rejected.

Stores decision metadata to be shown in the report.

Report Generation:

After analysis, the system produces a structured HTML report.

The report includes an executive summary, requirement checklist, gap analysis, insights, and comparative evaluation.
![Demo](https://raw.githubusercontent.com/ShoaibDataScientist/ContractAudit/main/screenshots/report.png)


Users can download this report for sharing and offline review.

Frontend Integration:

The Flask backend serves API endpoints and renders the user interface.

The frontend (Tailwind + Alpine.js + HTMX) offers real-time status updates, an interactive upload experience, and dynamic visualization of report contents.
