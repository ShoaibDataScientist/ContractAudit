import os
import re
import shutil
import sys
import traceback
import logging
from logging.handlers import RotatingFileHandler
from functools import lru_cache
from typing import List, Optional, Any
from typing_extensions import Literal
from flask import Flask, render_template, request, jsonify, send_file, abort
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from llama_parse import LlamaParse
from openai import OpenAI
from langchain.agents import create_structured_chat_agent, Tool
from langchain.memory import ConversationBufferMemory
from langchain.tools import tool
from pydantic import BaseModel, Field
import asyncio
import uuid  # For unique filenames
from PIL import Image
import pytesseract
import arabic_reshaper
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.pagesizes import letter
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
pdfmetrics.registerFont(TTFont('Arabic_naskh', 'NotoNaskhArabic-Regular.ttf'))
pdfmetrics.registerFont(TTFont('Urdu_naskh', 'NotoNastaliqUrdu-Regular.ttf'))
pdfmetrics.registerFont(TTFont('English_naskh', 'Roboto-Regular.ttf'))
language_mapping = {"Arabic": "ara", "Urdu": "urd", "English": "eng"}


# Load environment variables
load_dotenv()
app = Flask(__name__)

# Custom formatter for logging
class CustomFormatter(logging.Formatter):
    def format(self, record):
        record.request_id = getattr(record, 'request_id', '-')
        return super().format(record)

# Logging configuration
log_formatter = CustomFormatter('%(asctime)s - [%(request_id)s] - %(name)s - %(levelname)s - %(message)s')
log_file = 'app.log'
log_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
log_handler.setFormatter(log_formatter)
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
app.logger.addHandler(console_handler)

# Constants
TOP_K = 6
CHAT_CONTEXT_CHAR_LIMIT = 4000
CHAT_HISTORY_TURNS = 8
UPLOAD_FOLDER = 'uploads'  # Define an upload folder to save the temporary files
OUTPUT_FOLDER = 'parsed_pdfs'
FAISS_INDEX_FOLDER = 'faiss_index'
DOWNLOAD_REPORT_FOLDER = 'downloadable_reports'  # New folder for downloadable reports

# Accept PDF, DOC, DOCX, PNG, JPEG, JPG
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'png', 'jpeg', 'jpg'}

# --- NEW CONSTANTS FOR SCORING ---
MAX_POSSIBLE_GAP_SCORE = 100  # THIS IS A PLACEHOLDER. ADJUST AS NEEDED.
PROPOSAL_REJECTION_THRESHOLD_PERCENT = 20  # 20% difference for rejection
ENHANCED_PROPOSAL_ACCEPTED_GAP_SCORE_THRESHOLD = max(1, int(MAX_POSSIBLE_GAP_SCORE * 0.2))

# Create necessary directories for
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, FAISS_INDEX_FOLDER, DOWNLOAD_REPORT_FOLDER]:
    # Include new folders
    os.makedirs(folder, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER  # Set Flask's upload folder configuration

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Environment variable handling
def get_required_env_var(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        app.logger.critical(f"{var_name} not found in environment variables")
        raise ValueError(f"{var_name} not found in environment variables")
    return value

# Initialize clients
openai_api_key = get_required_env_var("OPENAI_API_KEY")
llama_cloud_api_key = get_required_env_var("LLAMA_CLOUD_API_KEY")
client = OpenAI(api_key=openai_api_key)

# Initialize ChatOpenAI with caching
@lru_cache(maxsize=1)
def get_llm():
    return ChatOpenAI(
        model="gpt-4o",
        temperature=0.3,
        max_tokens=None,
        timeout=None,
        max_retries=2,
        api_key=openai_api_key,
    )

# Pydantic models
class GapItem(BaseModel):
    description: str = Field(description="Description of the gap between RFP and Response")
    severity: Literal["Low", "Medium", "High"] = Field(description="Severity of the gap")
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Missing technical specifications",
                    "severity": "High"
                }
            ]
        }
    }

class GapAnalysis(BaseModel):
    summary: str = Field(description="Brief summary of the overall gap analysis")
    gaps: List[GapItem] = Field(description="List of identified gaps")
    suggestions: List[str] = Field(description="List of suggestions to address the gaps")
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Several gaps identified between RFP and Response",
                    "gaps": [
                        {
                            "description": "Missing technical specifications",
                            "severity": "High"
                        }
                    ],
                    "suggestions": [
                        "Include detailed technical specifications"
                    ]
                }
            ]
        }
    }

# Custom exceptions
class DocumentProcessingError(Exception):
    pass

class RetrieverError(Exception):
    pass

# FAISS operations
class FAISSOperations:
    @staticmethod
    def clear_index(collection_name: str) -> None:
        try:
            index_path = os.path.join(FAISS_INDEX_FOLDER, collection_name)
            if os.path.exists(index_path):
                shutil.rmtree(index_path)
            app.logger.info(f"Cleared FAISS index for collection: {collection_name}")
        except Exception as e:
            app.logger.error(f"Error clearing FAISS index for collection {collection_name}: {str(e)}")
            app.logger.debug(traceback.format_exc())
            raise DocumentProcessingError(f"Failed to clear FAISS index: {str(e)}")

    @staticmethod
    def create_index(documents: List[Document], collection_name: str) -> FAISS:
        try:
            if not documents:
                raise DocumentProcessingError("No documents to index. The document list is empty.")
            embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
            texts = [doc.page_content for doc in documents]
            metadatas = [doc.metadata for doc in documents]
            if not texts or all(not t.strip() for t in texts):
                raise DocumentProcessingError("No text data available for FAISS indexing.")
            vectorstore = FAISS.from_texts(texts, embeddings, metadatas=metadatas)
            index_path = os.path.join(FAISS_INDEX_FOLDER, collection_name)
            os.makedirs(index_path, exist_ok=True)
            vectorstore.save_local(index_path)
            app.logger.info(f"Created new FAISS index for collection: {collection_name}")
            return vectorstore
        except Exception as e:
            app.logger.error(f"Error creating FAISS index for collection {collection_name}: {str(e)}")
            app.logger.debug(traceback.format_exc())
            raise DocumentProcessingError(f"Failed to create FAISS index: {str(e)}")

class DocumentProcessor:
    @staticmethod
    def _create_parser(use_vendor_model: bool = True) -> LlamaParse:
        parser_kwargs = dict(
            api_key=llama_cloud_api_key,
            result_type="markdown",
            num_workers=1,
            verbose=True,
            language="en"
        )
        if use_vendor_model:
            parser_kwargs.update(
                use_vendor_multimodal_model=True,
                vendor_multimodal_model_name="anthropic-sonnet-3.5",
            )
        return LlamaParse(**parser_kwargs)

    @staticmethod
    def _has_text(pages: List[Any]) -> bool:
        if not pages:
            return False
        for page in pages:
            if getattr(page, "text", None) and page.text.strip():
                return True
        return False

    @staticmethod
    def parse_file(file_path: str, output_name: str) -> str:
        try:
            ext = file_path.rsplit('.', 1)[-1].lower()
            if ext in ['pdf', 'doc', 'docx']:
                # --- Existing LlamaParse logic; adjust as per your application ---
                FAISSOperations.clear_index(output_name)
                current_parser = DocumentProcessor._create_parser(use_vendor_model=True)
                fallback_attempted = False
                result = None
                try:
                    result = current_parser.load_data(file_path)
                except Exception as vendor_exception:
                    error_message = str(vendor_exception)
                    fallback_needed = any(
                        indicator in error_message.lower()
                        for indicator in ["multimodal_error", "not available", "vendor"]
                    )
                    if fallback_needed:
                        app.logger.warning(
                            "Vendor multimodal model unavailable. Retrying parsing with default LlamaParse pipeline."
                        )
                        fallback_attempted = True
                        current_parser = DocumentProcessor._create_parser(use_vendor_model=False)
                        result = current_parser.load_data(file_path)
                    else:
                        raise
                if not DocumentProcessor._has_text(result):
                    if not fallback_attempted:
                        app.logger.warning(
                            "Vendor parser returned no readable text. Retrying with default LlamaParse pipeline."
                        )
                        try:
                            fallback_attempted = True
                            fallback_parser = DocumentProcessor._create_parser(use_vendor_model=False)
                            result = fallback_parser.load_data(file_path)
                        except Exception as fallback_exc:
                            raise DocumentProcessingError(
                                f"Unable to parse '{file_path}' even after fallback attempt: {fallback_exc}"
                            ) from fallback_exc
                    else:
                        raise DocumentProcessingError(
                            f"The parsed file '{file_path}' contains no readable text."
                        )
                if not DocumentProcessor._has_text(result):
                    raise DocumentProcessingError(
                        f"The parsed file '{file_path}' contains no readable text."
                    )
                output_path = os.path.join(OUTPUT_FOLDER, f"{output_name}.md")
                with open(output_path, 'w', encoding='utf-8') as f:
                    for page in result:
                        if page.text and page.text.strip():
                            f.write(page.text)
                            f.write("\n\n---\n\n")
                documents = [
                    Document(page_content=page.text, metadata={"source": output_name, "page": i})
                    for i, page in enumerate(result) if page.text and page.text.strip()
                ]
                if not documents:
                    raise DocumentProcessingError(
                        f"The file '{file_path}' could not be converted into valid documents."
                    )
                FAISSOperations.create_index(documents, output_name)
                return f"Successfully processed: {output_name}"

            elif ext in ['png', 'jpeg', 'jpg']:
                # --- Tesseract OCR logic for images ---
                try:
                    image = Image.open(file_path)
                    extracted_text = pytesseract.image_to_string(image)
                except Exception as ocr_error:
                    raise DocumentProcessingError(f"OCR failed: {ocr_error}")

                if not extracted_text.strip():
                    raise DocumentProcessingError(
                        f"The image '{file_path}' did not contain any readable text."
                    )
                output_path = os.path.join(OUTPUT_FOLDER, f"{output_name}.md")
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(extracted_text)
                    f.write("\n\n---\n\n")
                document = Document(
                    page_content=extracted_text,
                    metadata={"source": output_name, "page": 0}
                )
                FAISSOperations.create_index([document], output_name)
                return f"Successfully processed: {output_name}"

            else:
                raise DocumentProcessingError(f"Unsupported file type: {ext}")

        except Exception as e:
            app.logger.error(f"Error parsing {file_path}: {str(e)}")
            app.logger.debug(traceback.format_exc())
            raise DocumentProcessingError(f"Failed to parse file: {str(e)}")

# Document Retrieval
class DocumentRetriever:
    @staticmethod
    def initialize_retriever(collection_name: str) -> Optional[Any]:
        try:
            embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
            index_path = os.path.join(FAISS_INDEX_FOLDER, collection_name)
            if not os.path.exists(index_path):
                app.logger.warning(f"No FAISS index found for collection: {collection_name}")
                return None
            vectorstore = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
            return vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": TOP_K})
        except Exception as e:
            app.logger.error(f"Error initializing retriever for {collection_name}: {str(e)}")
            app.logger.debug(traceback.format_exc())
            raise RetrieverError(f"Failed to initialize retriever: {str(e)}")

    @staticmethod
    def retrieve_documents(query: str, retriever: Any) -> str:
        try:
            docs = retriever.invoke(query)
            return "\n\n".join([
                f"**Document {i+1}:**\n{doc.page_content}"
                for i, doc in enumerate(docs)
            ])
        except Exception as e:
            app.logger.error(f"Error retrieving documents: {str(e)}")
            raise RetrieverError(f"Failed to retrieve documents: {str(e)}")

# Analysis
class Analyzer:
    @staticmethod
    def calculate_gap_score(gaps: List[GapItem]) -> float:
        score_mapping = {
            "Low": 1,
            "Medium": 3,
            "High": 5
        }
        total_score = 0
        for gap in gaps:
            total_score += score_mapping.get(gap.severity, 0)
        return total_score

    @staticmethod
    def analyze_gap(context: str) -> dict:
        try:
            llm = get_llm()
            gap_analysis_parser = PydanticOutputParser(pydantic_object=GapAnalysis)
            gap_analysis_prompt = PromptTemplate(
                template="Analyze the gap between the RFP requirements and the Response based on the following context:\n\n{context}\n\n{format_instructions}\n",
                input_variables=["context"],
                partial_variables={"format_instructions": gap_analysis_parser.get_format_instructions()},
            )
            output = llm.invoke(gap_analysis_prompt.format(context=context))
            parsed_output = gap_analysis_parser.parse(output.content)
            result = parsed_output.model_dump()
            gap_score = Analyzer.calculate_gap_score(parsed_output.gaps)
            result["gap_score"] = gap_score
            return result
        except Exception as e:
            app.logger.error(f"Error during gap analysis: {str(e)}")
            raise ValueError(f"Failed to analyze gap: {str(e)}")

    @staticmethod
    def generate_insights(context: str) -> str:
        try:
            llm = get_llm()
            insight_prompt = f"""\
Based on the following documents: {context}
Please provide a structured report with the following sections if uploaded documents are in arabic then your response should also in arabic if its in english than response should also in english:
1. Executive Summary:
   - Provide a concise overview of the main points from both the RFP and the Response.
2. RFP Requirements Checklist:
   - List the critical requirements from the RFP.
   - For each requirement, indicate whether it is addressed in the Response (Addressed/Partially Addressed/Not Addressed).
3. Key Insights:
   - Bullet point the most critical insights derived from comparing the RFP and the Response.
   - For each insight, provide a brief explanation of its significance.
4. Trends and Patterns:
   - Identify and explain any common themes or patterns across both documents.
5. Comparative Analysis:
   - Highlight notable differences between the RFP requirements and the Response.
   - Identify any areas where the Response exceeds RFP expectations.
"""
            insights = llm.invoke(insight_prompt)
            return insights.content
        except Exception as e:
            app.logger.error(f"Error generating insights: {str(e)}")
            raise ValueError(f"Failed to generate insights: {str(e)}")

# Report Formatting
class ReportFormatter:
    @staticmethod
    def _strip_code_fences(text: str) -> str:
        if not text:
            return text
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped

        # Remove opening fence and optional language tag
        stripped = stripped[3:].lstrip()
        newline_index = stripped.find("\n")
        if newline_index != -1:
            language_tag = stripped[:newline_index].strip().lower()
            if language_tag in {"html", "htm", "markdown", "md"}:
                stripped = stripped[newline_index + 1 :]
        stripped = stripped.strip()

        # Remove trailing fence if present
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        return stripped.strip()

    @staticmethod
    def format_report(raw_data: str, bid_document_number: str = None) -> str:
        try:
            prompt = f"""
Format the following raw data into a well-structured HTML report if uploaded documents are in arabic then your response should also in arabic if its in english than response should also in english. Focus on analysis details only and do not restate overall summary metrics like bid document numbers, overall gap score, proposal status, or percentage differences. 
{raw_data}
"""

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You will be given unformated data and you will format it into a well-structured HTML report. Use tables and images to make the report more readable.Specially use table for Gap Description and Saverity(in arabic if uploaded documents arein arabic) and in saverity column mention high,medium,low(in arabic if uploaded documents arein arabic) with helighted color and if uploaded documents are in arabic then your response should also in arabic if its in english than response should also in english"
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
            )

            formatted_html = response.choices[0].message.content
            return ReportFormatter._strip_code_fences(formatted_html)
        except Exception as e:
            app.logger.error(f"Error formatting report: {str(e)}")
            return f"<p>Error formatting report: {str(e)}</p>"

def clean_report_text(report_html: Optional[str], limit: int = CHAT_CONTEXT_CHAR_LIMIT) -> str:
    if not report_html:
        return ""
    try:
        text = re.sub(r'<(script|style).*?>.*?</\1>', ' ', report_html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()[:limit]
    except re.error:
        return report_html[:limit]

def format_chat_history(history: List[dict], limit: int = CHAT_HISTORY_TURNS) -> str:
    if not history:
        return ""
    formatted_turns = []
    for turn in history[-limit:]:
        role = turn.get('role', 'user').strip().lower()
        content = (turn.get('content') or '').strip()
        if not content:
            continue
        role_label = "User" if role == 'user' else "Assistant"
        formatted_turns.append(f"{role_label}: {content}")
    return "\n".join(formatted_turns)

# Agent Tools
class AgentTools:
    @staticmethod
    @tool
    def retrieve_rfp_documents(query: str) -> str:
        """Retrieve relevant RFP documents using the query."""
        try:
            retriever = DocumentRetriever.initialize_retriever("rfp_parsed")
            if not retriever:
                return "Error: RFP documents not processed yet."
            return DocumentRetriever.retrieve_documents(query, retriever)
        except Exception as e:
            app.logger.error(f"Error retrieving RFP documents: {str(e)}")
            return f"Error retrieving RFP documents: {str(e)}"

    @staticmethod
    @tool
    def retrieve_response_documents(query: str) -> str:
        """Retrieve relevant Response documents using the query."""
        try:
            retriever = DocumentRetriever.initialize_retriever("response_parsed")
            if not retriever:
                return "Error: Response documents not processed yet."
            return DocumentRetriever.retrieve_documents(query, retriever)
        except Exception as e:
            app.logger.error(f"Error retrieving Response documents: {str(e)}")
            return f"Error retrieving Response documents: {str(e)}"

    @staticmethod
    def setup_agent():
        try:
            memory = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True
            )
            tools = [
                Tool(
                    name="Retrieve RFP Documents",
                    func=AgentTools.retrieve_rfp_documents,
                    description="Retrieve relevant RFP documents using the query."
                ),
                Tool(
                    name="Retrieve Response Documents",
                    func=AgentTools.retrieve_response_documents,
                    description="Retrieve relevant Response documents using the query."
                ),
                Tool(
                    name="Analyze Gap",
                    func=Analyzer.analyze_gap,
                    description="Analyze gaps between RFP requirements and Response."
                ),
                Tool(
                    name="Generate Insights",
                    func=Analyzer.generate_insights,
                    description="Generate detailed insights from documents."
                )
            ]
            return create_structured_chat_agent(
                llm=get_llm(),
                tools=tools,
                memory=memory,
                verbose=True,
                max_iterations=5
            )
        except Exception as e:
            app.logger.error(f"Error setting up agent: {str(e)}")
            raise ValueError(f"Failed to setup agent: {str(e)}")

# Flask routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_documents():
    request_id = str(uuid.uuid4())
    app.logger.info("Received request to /process", extra={'request_id': request_id})
    if 'rfp' not in request.files or 'response' not in request.files:
        app.logger.warning("Incomplete request: Both RFP and Response files are required", extra={'request_id': request_id})
        return jsonify({"error": "Both RFP and Response files are required"}), 400
    bid_document_number = request.form.get('bidDocumentNumber')
    if not bid_document_number:
        app.logger.warning("Bid Document Number is required", extra={'request_id': request_id})
        return jsonify({"error": "Bid Document Number is required"}), 400
    rfp_file = request.files['rfp']
    response_file = request.files['response']
    for file in [rfp_file, response_file]:
        if not allowed_file(file.filename):
            app.logger.warning(f"Only files of types {ALLOWED_EXTENSIONS} are allowed. Received: {file.filename}", extra={'request_id': request_id})
            return jsonify({"error": f"Only files of types {', '.join(ALLOWED_EXTENSIONS)} are allowed"}), 400

    # Use original extension when saving
    rfp_ext = rfp_file.filename.rsplit('.', 1)[1].lower()
    response_ext = response_file.filename.rsplit('.', 1)[1].lower()
    rfp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_rfp_{uuid.uuid4()}.{rfp_ext}")
    response_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_response_{uuid.uuid4()}.{response_ext}")
    try:
        rfp_file.save(rfp_path)
        response_file.save(response_path)
        app.logger.info(f"Files saved temporarily: {rfp_path}, {response_path}", extra={'request_id': request_id})
        processor = DocumentProcessor()
        rfp_result = processor.parse_file(rfp_path, "rfp_parsed")
        response_result = processor.parse_file(response_path, "response_parsed")
        app.logger.info("Documents parsed successfully", extra={'request_id': request_id})
        return jsonify({
            "rfp_result": rfp_result,
            "response_result": response_result,
            "bid_document_number": bid_document_number,
            "message": "Documents processed successfully"
        })
    except Exception as e:
        app.logger.error(f"Error processing documents: {str(e)}", extra={'request_id': request_id})
        app.logger.debug(traceback.format_exc(), extra={'request_id': request_id})
        return jsonify({"error": str(e)}), 500
    finally:
        for path in [rfp_path, response_path]:
            if os.path.exists(path):
                os.remove(path)
                app.logger.info(f"Cleaned up temporary file: {path}", extra={'request_id': request_id})

@app.route('/generate_report', methods=['POST'])
def generate_report():
    request_id = str(uuid.uuid4())
    app.logger.info("Received request to /generate_report", extra={'request_id': request_id})
    try:
        bid_document_number = request.json.get('bidDocumentNumber')
        retriever = DocumentRetriever()
        rfp_retriever = retriever.initialize_retriever("rfp_parsed")
        response_retriever = retriever.initialize_retriever("response_parsed")
        if not rfp_retriever or not response_retriever:
            app.logger.error("Documents not processed before generating report", extra={'request_id': request_id})
            raise ValueError("Documents must be processed before generating a report")
        rfp_content = retriever.retrieve_documents("Retrieve all relevant RFP content.", rfp_retriever)
        response_content = retriever.retrieve_documents("Retrieve all relevant Response content.", response_retriever)
        app.logger.info("Documents retrieved for analysis", extra={'request_id': request_id})
        analyzer = Analyzer()
        raw_analysis_dict = analyzer.analyze_gap(f"RFP Content:\n{rfp_content}\n\nResponse Content:\n{response_content}")
        raw_insights = analyzer.generate_insights(f"RFP Content:\n{rfp_content}\n\nResponse Content:\n{response_content}")
        app.logger.info("Gap analysis and insights generated", extra={'request_id': request_id})

        # --- Scoring Logic ---
        gap_score = raw_analysis_dict.get("gap_score", 0)
        if MAX_POSSIBLE_GAP_SCORE <= 0:
            app.logger.error("MAX_POSSIBLE_GAP_SCORE is not set or is zero/negative.", extra={'request_id': request_id})
            difference_percentage = 0.0
            proposal_status = "Error in scoring configuration"
        else:
            difference_percentage = (gap_score / MAX_POSSIBLE_GAP_SCORE) * 100
            proposal_status = "Accepted"
            if difference_percentage > PROPOSAL_REJECTION_THRESHOLD_PERCENT:
                proposal_status = "Rejected"
                app.logger.info(f"Proposal Rejected: Difference {difference_percentage:.2f}% exceeds {PROPOSAL_REJECTION_THRESHOLD_PERCENT}% threshold.", extra={'request_id': request_id})
            else:
                app.logger.info(f"Proposal Accepted: Difference {difference_percentage:.2f}% within {PROPOSAL_REJECTION_THRESHOLD_PERCENT}% threshold.", extra={'request_id': request_id})

        raw_analysis_text = f"""\
Summary: {raw_analysis_dict['summary']}
Gaps: {chr(10).join([f"- {gap['description']} (Severity: {gap['severity']})" for gap in raw_analysis_dict['gaps']])}
Suggestions: {chr(10).join([f"- {suggestion}" for suggestion in raw_analysis_dict['suggestions']])}
"""
        raw_report_content = f"""\
# RFP and Response Analysis Report

## Part 1: Gap Analysis

{raw_analysis_text}

## Part 2: Detailed Insights

{raw_insights}
"""
        formatter = ReportFormatter()
        formatted_report_html = formatter.format_report(raw_report_content, bid_document_number=bid_document_number)
        app.logger.info("Report formatted to HTML", extra={'request_id': request_id})

        # --- NEW: Save the HTML report to a temporary file for download ---
        report_filename = f"report_{bid_document_number.replace(' ', '_')}_{uuid.uuid4()}.html"  # Sanitize bid_document_number for filename
        report_filepath = os.path.join(DOWNLOAD_REPORT_FOLDER, report_filename)
        with open(report_filepath, 'w', encoding='utf-8') as f:
            f.write(formatted_report_html)
        app.logger.info(f"Report saved for download: {report_filepath}", extra={'request_id': request_id})

        allow_enhanced_proposal = False
        enhanced_message = "This proposal already meets the minimum improvement criteria."
        if proposal_status == "Rejected":
            allow_enhanced_proposal = True
            enhanced_message = "Proposal was rejected. Draft an enhanced version to close the gaps."
        elif gap_score is not None and gap_score <= ENHANCED_PROPOSAL_ACCEPTED_GAP_SCORE_THRESHOLD:
            allow_enhanced_proposal = True
            enhanced_message = "Proposal was accepted but recorded a low gap score. Consider drafting a stronger version."

        return jsonify({
            "structured_report": formatted_report_html,  # Still send HTML for display
            "gap_score": gap_score,
            "difference_percentage": difference_percentage,
            "proposal_status": proposal_status,
            "rejection_threshold": PROPOSAL_REJECTION_THRESHOLD_PERCENT,
            "bid_document_number": bid_document_number,
            "download_filename": report_filename,  # New: send the filename for download
            "allow_enhanced_proposal": allow_enhanced_proposal,
            "enhanced_proposal_message": enhanced_message
        })
    except ValueError as e:
        app.logger.error(f"Validation error during report generation: {str(e)}", extra={'request_id': request_id})
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Error generating report: {str(e)}", extra={'request_id': request_id})
        app.logger.debug(traceback.format_exc(), extra={'request_id': request_id})
        return jsonify({"error": "An internal error occurred"}), 500

@app.route('/chat', methods=['POST'])
def chat_with_documents():
    request_id = str(uuid.uuid4())
    app.logger.info("Received request to /chat", extra={'request_id': request_id})
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()

    if not message:
        return jsonify({"error": "Message is required to start the chat."}), 400

    bid_document_number = (data.get('bidDocumentNumber') or '').strip() or 'N/A'
    report_html = data.get('reportHtml') or ''
    history = data.get('history') or []

    try:
        rfp_retriever = DocumentRetriever.initialize_retriever("rfp_parsed")
        response_retriever = DocumentRetriever.initialize_retriever("response_parsed")
        if not rfp_retriever or not response_retriever:
            raise ValueError("Please process the RFP and Response documents before starting a chat.")

        rfp_context = DocumentRetriever.retrieve_documents(message, rfp_retriever)
        response_context = DocumentRetriever.retrieve_documents(message, response_retriever)

        def trim_context(text: str) -> str:
            if not text:
                return ""
            return text[:CHAT_CONTEXT_CHAR_LIMIT]

        rfp_context = trim_context(rfp_context)
        response_context = trim_context(response_context)
        history_text = format_chat_history(history, CHAT_HISTORY_TURNS)
        report_text = clean_report_text(report_html, CHAT_CONTEXT_CHAR_LIMIT)

        instruction_block = (
            "You are a contract intelligence assistant. Use the retrieved RFP context, "
            "Response context, and structured report summary to answer the question. "
            "Reference the evidence you used. If the underlying documents are in Arabic, respond in Arabic; "
            "if they are in English, respond in English. If the answer is not available, say so."
        )

        prompt = f"""{instruction_block}

Bid Document Number: {bid_document_number}

Conversation so far:
{history_text or 'No previous conversation.'}

Structured Report Summary:
{report_text or 'Report not generated yet.'}

Retrieved RFP Context:
{rfp_context or 'No matching RFP excerpts.'}

Retrieved Response Context:
{response_context or 'No matching Response excerpts.'}

User Question:
{message}
"""

        llm = get_llm()
        answer = llm.invoke(prompt)
        answer_text = getattr(answer, 'content', str(answer))

        app.logger.info("Chat response generated successfully", extra={'request_id': request_id})
        return jsonify({"answer": answer_text})
    except ValueError as e:
        app.logger.warning(f"Chat validation error: {str(e)}", extra={'request_id': request_id})
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Error during chat processing: {str(e)}", extra={'request_id': request_id})
        app.logger.debug(traceback.format_exc(), extra={'request_id': request_id})
        return jsonify({"error": "An internal error occurred while generating the chat response."}), 500

@app.route('/enhanced_proposal', methods=['POST'])
def enhanced_proposal():
    request_id = str(uuid.uuid4())
    app.logger.info("Received request to /enhanced_proposal", extra={'request_id': request_id})
    data = request.get_json(silent=True) or {}
    bid_document_number = (data.get('bidDocumentNumber') or '').strip()
    if not bid_document_number:
        return jsonify({"error": "Bid Document Number is required to generate a proposal."}), 400

    report_html = data.get('reportHtml') or ''
    gap_score = data.get('gapScore')
    difference_percentage = data.get('differencePercentage')
    proposal_status = data.get('proposalStatus') or 'Unknown'

    try:
        retriever = DocumentRetriever()
        rfp_retriever = retriever.initialize_retriever("rfp_parsed")
        response_retriever = retriever.initialize_retriever("response_parsed")
        if not rfp_retriever or not response_retriever:
            raise ValueError("Please process the RFP and Response documents before drafting a new proposal.")

        rfp_context = retriever.retrieve_documents(
            "Summarize the most critical requirements, evaluation criteria, and compliance points from the RFP.",
            rfp_retriever
        )
        response_context = retriever.retrieve_documents(
            "Summarize the original proposal's approach, strengths, and weaknesses.",
            response_retriever
        )

        gap_display = gap_score if gap_score is not None else "N/A"
        diff_display = difference_percentage if difference_percentage is not None else "N/A"
        history_summary = f"Status: {proposal_status}. Gap Score: {gap_display}. Difference %: {diff_display}."
        report_summary = clean_report_text(report_html, CHAT_CONTEXT_CHAR_LIMIT)

        prompt = f"""
You are an expert proposal writer. Create an enhanced proposal that directly addresses the identified gaps and aligns tightly with the client's RFP.
Follow the language of the source documents (Arabic stays Arabic, English stays English). Provide clear sections such as Executive Overview, Technical Approach, Compliance Matrix, Value Additions, and Timeline.
Where helpful, include bullet points or tables for clarity. Focus on specificity drawn from the context below.

Bid Document Number: {bid_document_number}
Latest Evaluation: {history_summary}

Structured Report Summary:
{report_summary or 'Not available'}

Key RFP Highlights:
{rfp_context or 'No RFP context was retrieved.'}

Original Response Highlights:
{response_context or 'No response context was retrieved.'}
"""

        llm = get_llm()
        proposal_response = llm.invoke(prompt)
        proposal_html = ReportFormatter._strip_code_fences(getattr(proposal_response, 'content', str(proposal_response)))
        if not proposal_html:
            raise ValueError("Enhanced proposal generation returned no content.")

        safe_bid = re.sub(r'[^A-Za-z0-9_-]+', '_', bid_document_number) or "proposal"
        filename = f"enhanced_proposal_{safe_bid}_{uuid.uuid4()}.html"
        filepath = os.path.join(DOWNLOAD_REPORT_FOLDER, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(proposal_html)
        app.logger.info(f"Enhanced proposal saved: {filepath}", extra={'request_id': request_id})

        return jsonify({
            "proposal_html": proposal_html,
            "download_filename": filename
        })
    except ValueError as e:
        app.logger.warning(f"Enhanced proposal validation error: {str(e)}", extra={'request_id': request_id})
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Error generating enhanced proposal: {str(e)}", extra={'request_id': request_id})
        app.logger.debug(traceback.format_exc(), extra={'request_id': request_id})
        return jsonify({"error": "An internal error occurred while drafting the enhanced proposal."}), 500

@app.route('/api/evaluate_and_report', methods=['POST'])
def evaluate_and_report():
    request_id = str(uuid.uuid4())
    app.logger.info("Received request to /api/evaluate_and_report", extra={'request_id': request_id})
    # 1. Validate input files and bidDocumentNumber
    if 'rfp' not in request.files or 'response' not in request.files:
        app.logger.warning("Incomplete request: Both RFP and Response files are required", extra={'request_id': request_id})
        return jsonify({"error": "Both RFP and Response files are required"}), 400
    bid_document_number = request.form.get('bidDocumentNumber')
    if not bid_document_number:
        app.logger.warning("Bid Document Number is required", extra={'request_id': request_id})
        return jsonify({"error": "Bid Document Number is required"}), 400
    rfp_file = request.files['rfp']
    response_file = request.files['response']
    for file in [rfp_file, response_file]:
        if not allowed_file(file.filename):
            app.logger.warning(f"Only files of types {ALLOWED_EXTENSIONS} are allowed. Received: {file.filename}", extra={'request_id': request_id})
            return jsonify({"error": f"Only files of types {', '.join(ALLOWED_EXTENSIONS)} are allowed"}), 400

    rfp_ext = rfp_file.filename.rsplit('.', 1)[1].lower()
    response_ext = response_file.filename.rsplit('.', 1)[1].lower()
    rfp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_rfp_{uuid.uuid4()}.{rfp_ext}")
    response_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_response_{uuid.uuid4()}.{response_ext}")

    try:
        # Save files temporarily
        rfp_file.save(rfp_path)
        response_file.save(response_path)
        app.logger.info(f"Files saved temporarily: {rfp_path}, {response_path}", extra={'request_id': request_id})
        # 2. Process documents
        processor = DocumentProcessor()
        processor.parse_file(rfp_path, "rfp_parsed")
        processor.parse_file(response_path, "response_parsed")
        app.logger.info("Documents parsed successfully", extra={'request_id': request_id})

        # 3. Initialize retrievers
        retriever = DocumentRetriever()
        rfp_retriever = retriever.initialize_retriever("rfp_parsed")
        response_retriever = retriever.initialize_retriever("response_parsed")
        if not rfp_retriever or not response_retriever:
            app.logger.error("Failed to initialize retrievers after document processing", extra={'request_id': request_id})
            raise ValueError("Failed to process documents for analysis. Retrievers could not be initialized.")

        # 4. Retrieve content
        rfp_content = retriever.retrieve_documents("Retrieve all relevant RFP content.", rfp_retriever)
        response_content = retriever.retrieve_documents("Retrieve all relevant Response content.", response_retriever)
        app.logger.info("Documents retrieved for analysis", extra={'request_id': request_id})

        # 5. Perform gap analysis and generate insights
        analyzer = Analyzer()
        raw_analysis_dict = analyzer.analyze_gap(f"RFP Content:\n{rfp_content}\n\nResponse Content:\n{response_content}")
        raw_insights = analyzer.generate_insights(f"RFP Content:\n{rfp_content}\n\nResponse Content:\n{response_content}")
        app.logger.info("Gap analysis and insights generated", extra={'request_id': request_id})

        # 6. Calculate scoring
        gap_score = raw_analysis_dict.get("gap_score", 0)
        if MAX_POSSIBLE_GAP_SCORE <= 0:
            app.logger.error("MAX_POSSIBLE_GAP_SCORE is not set or is zero/negative.", extra={'request_id': request_id})
            difference_percentage = 0.0
            proposal_status = "Error in scoring configuration"
        else:
            difference_percentage = (gap_score / MAX_POSSIBLE_GAP_SCORE) * 100
            proposal_status = "Accepted"
            if difference_percentage > PROPOSAL_REJECTION_THRESHOLD_PERCENT:
                proposal_status = "Rejected"
                app.logger.info(f"Proposal Rejected: Difference {difference_percentage:.2f}% exceeds {PROPOSAL_REJECTION_THRESHOLD_PERCENT}% threshold.", extra={'request_id': request_id})
            else:
                app.logger.info(f"Proposal Accepted: Difference {difference_percentage:.2f}% within {PROPOSAL_REJECTION_THRESHOLD_PERCENT}% threshold.", extra={'request_id': request_id})

        # Prepare raw content for formatting
        raw_analysis_text = f"""\
Summary: {raw_analysis_dict['summary']}
Gaps: {chr(10).join([f"- {gap['description']} (Severity: {gap['severity']})" for gap in raw_analysis_dict['gaps']])}
Suggestions: {chr(10).join([f"- {suggestion}" for suggestion in raw_analysis_dict['suggestions']])}
"""
        raw_report_content = f"""\
# RFP and Response Analysis Report

## Part 1: Gap Analysis

**Overall Gap Score:** {gap_score} (out of {MAX_POSSIBLE_GAP_SCORE})

**Difference Percentage:** {difference_percentage:.2f}%

**Proposal Status:** {proposal_status}

{raw_analysis_text}

## Part 2: Detailed Insights

{raw_insights}
"""
        # 7. Format the report
        formatter = ReportFormatter()
        formatted_report_html = formatter.format_report(raw_report_content, bid_document_number=bid_document_number)
        app.logger.info("Report formatted to HTML", extra={'request_id': request_id})

        # 8. Save the HTML report (optional, but good for consistency with existing /generate_report)
        report_filename = f"report_{bid_document_number.replace(' ', '_')}_{uuid.uuid4()}.html"
        report_filepath = os.path.join(DOWNLOAD_REPORT_FOLDER, report_filename)
        with open(report_filepath, 'w', encoding='utf-8') as f:
            f.write(formatted_report_html)
        app.logger.info(f"Report saved for download: {report_filepath}", extra={'request_id': request_id})

        # 9. Return JSON response matching AnalysisReportDto
        return jsonify({
            "structured_report": formatted_report_html,
            "gap_score": gap_score,
            "difference_percentage": difference_percentage,
            "proposal_status": proposal_status,
            "rejection_threshold": PROPOSAL_REJECTION_THRESHOLD_PERCENT,
            "bid_document_number": bid_document_number
        })
    except ValueError as e:
        app.logger.error(f"Validation error in /api/evaluate_and_report: {str(e)}", extra={'request_id': request_id})
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Error in /api/evaluate_and_report: {str(e)}", extra={'request_id': request_id})
        app.logger.debug(traceback.format_exc(), extra={'request_id': request_id})
        return jsonify({"error": "An internal error occurred"}), 500
    finally:
        # Clean up temporary files
        for path in [rfp_path, response_path]:
            if os.path.exists(path):
                os.remove(path)
                app.logger.info(f"Cleaned up temporary file: {path}", extra={'request_id': request_id})

@app.route('/download/<path:filename>')
def download_generated_file(filename: str):
    safe_directory = os.path.abspath(DOWNLOAD_REPORT_FOLDER)
    requested_path = os.path.abspath(os.path.join(safe_directory, filename))
    if not requested_path.startswith(safe_directory):
        abort(404)
    if not os.path.exists(requested_path):
        return jsonify({"error": "Requested file was not found."}), 404
    return send_file(requested_path, as_attachment=True, download_name=os.path.basename(requested_path))

# Flask app run (only for development/testing)
if __name__ == '__main__':
    try:
        for directory in [UPLOAD_FOLDER, OUTPUT_FOLDER, FAISS_INDEX_FOLDER, DOWNLOAD_REPORT_FOLDER]:
            os.makedirs(directory, exist_ok=True)

        required_vars = ["OPENAI_API_KEY", "LLAMA_CLOUD_API_KEY"]
        missing_vars = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        port = int(os.environ.get('PORT', 5001))
        app.run(
            debug=False,
            host='0.0.0.0',
            port=port,
            use_reloader=False,
            threaded=True
        )
    except Exception as e:
        app.logger.critical(f"Failed to start application: {str(e)}")
        app.logger.debug(traceback.format_exc())
        sys.exit(1)
