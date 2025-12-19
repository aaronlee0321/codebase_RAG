from flask import Flask, render_template, request, session, jsonify
from flask_ngrok import run_with_ngrok
import os
import sys
import lancedb
from lancedb.rerankers import AnswerdotaiRerankers
import re
import redis
import uuid
import logging
import markdown
from openai import OpenAI
import json
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from redis import ConnectionPool
import pandas as pd
import sqlite3

# Import create_tables to ensure Qwen embedding function is registered
import create_tables

from prompts import (
    HYDE_SYSTEM_PROMPT,
    HYDE_V2_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT  
)

# Configuration
CONFIG = {
    'SECRET_KEY': os.urandom(24),
    'REDIS_HOST': 'localhost',
    'REDIS_PORT': 6379,
    'REDIS_DB': 0,
    'REDIS_POOL_SIZE': 10,  # Add pool size configuration
    'LOG_FILE': 'app.log',
    'LOG_FORMAT': '%(asctime)s - %(message)s',
    'LOG_DATE_FORMAT': '%d-%b-%y %H:%M:%S'
}

# Logging setup
def setup_logging(config):
    # Create logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # File handler
    file_handler = logging.FileHandler(config['LOG_FILE'])
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(config['LOG_FORMAT'], datefmt=config['LOG_DATE_FORMAT']))
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(config['LOG_FORMAT'], datefmt=config['LOG_DATE_FORMAT']))
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# File path index helper functions
def get_tables_for_files(file_filters, file_index_path="file_path_index.db", table_sets=None):
    """
    Use SQLite index to determine which table sets contain the target files.
    If SQLite lookup fails, fall back to searching LanceDB tables directly.
    
    Args:
        file_filters: List of normalized file paths
        file_index_path: Path to SQLite index file
        table_sets: Optional list of (method_table, class_table) tuples for fallback search
    
    Returns: Set of table prefixes (e.g., {'Scripts', '_GameData'})
    """
    if not file_filters:
        return None
    
    # Normalize all filter paths using consistent normalization
    normalized_filters = set()
    for f in file_filters:
        norm = normalize_path_consistent(f)
        if norm:
            normalized_filters.add(norm)
    
    if not normalized_filters:
        return None
    
    # Try SQLite index first
    table_prefixes = None
    if os.path.exists(file_index_path):
        try:
            conn = sqlite3.connect(file_index_path)
            cursor = conn.cursor()
            
            # Find which tables contain these files
            placeholders = ','.join(['?'] * len(normalized_filters))
            cursor.execute(f"""
                SELECT DISTINCT table_name 
                FROM file_chunks 
                WHERE normalized_path IN ({placeholders})
            """, list(normalized_filters))
            
            matching_tables = {row[0] for row in cursor.fetchall()}
            conn.close()
            
            # Extract table prefixes (e.g., 'Scripts_method' -> 'Scripts')
            table_prefixes = set()
            for table_name in matching_tables:
                if table_name.endswith("_method"):
                    table_prefixes.add(table_name[:-7])
                elif table_name.endswith("_class"):
                    table_prefixes.add(table_name[:-6])
            
            if table_prefixes:
                try:
                    app.logger.info(f"[FILE INDEX] Found {len(table_prefixes)} table prefix(es) via SQLite index: {table_prefixes}")
                except:
                    pass
                return table_prefixes
        except Exception as e:
            try:
                app.logger.warning(f"[FILE INDEX] SQLite lookup failed: {e}, trying fallback")
            except:
                print(f"Warning: Error querying file index: {e}, trying fallback")
    
    # FALLBACK: Search LanceDB tables directly if SQLite index lookup failed
    if table_sets is None:
        # Try to use global table_sets from module scope
        try:
            import sys
            module = sys.modules.get(__name__)
            if module and hasattr(module, 'table_sets'):
                table_sets = module.table_sets
        except:
            pass
    
    if table_sets:
        try:
            app.logger.info(f"[FILE INDEX] Using fallback: searching {len(table_sets)} table set(s) directly")
            found_prefixes = set()
            
            # Use parent database directory
            if os.path.exists("../database"):
                uri = "../database"
            elif os.path.exists("database"):
                uri = "database"
            else:
                return None
            
            db = lancedb.connect(uri)
            
            # Search each table set for the target files
            for method_table, class_table in table_sets:
                prefix = table_prefix_map.get((method_table, class_table))
                if not prefix:
                    continue
                
                # Check method table
                try:
                    method_df = method_table.to_pandas()
                    if not method_df.empty and "file_path" in method_df.columns:
                        method_df["normalized_path"] = method_df["file_path"].apply(normalize_path_consistent)
                        matches = method_df[method_df["normalized_path"].isin(normalized_filters)]
                        if not matches.empty:
                            found_prefixes.add(prefix)
                            app.logger.info(f"[FILE INDEX] Fallback: Found files in {prefix}_method table")
                except Exception as e:
                    app.logger.warning(f"[FILE INDEX] Fallback error checking {prefix}_method: {e}")
                
                # Check class table
                try:
                    class_df = class_table.to_pandas()
                    if not class_df.empty and "file_path" in class_df.columns:
                        class_df["normalized_path"] = class_df["file_path"].apply(normalize_path_consistent)
                        matches = class_df[class_df["normalized_path"].isin(normalized_filters)]
                        if not matches.empty:
                            found_prefixes.add(prefix)
                            app.logger.info(f"[FILE INDEX] Fallback: Found files in {prefix}_class table")
                except Exception as e:
                    app.logger.warning(f"[FILE INDEX] Fallback error checking {prefix}_class: {e}")
            
            if found_prefixes:
                app.logger.info(f"[FILE INDEX] Fallback found {len(found_prefixes)} table prefix(es): {found_prefixes}")
                return found_prefixes
        except Exception as e:
            try:
                app.logger.warning(f"[FILE INDEX] Fallback search failed: {e}")
            except:
                print(f"Warning: Fallback search failed: {e}")
    
    # No matches found
    try:
        app.logger.warning(f"[FILE INDEX] No tables found for {len(normalized_filters)} file(s) via index or fallback")
    except:
        pass
    return None

# Database setup
def setup_database(codebase_paths=None, auto_detect=True):
    """
    Setup database connections for multiple codebase folders.
    Args:
        codebase_paths: List of codebase folder paths or single path string, or None
        auto_detect: If True and codebase_paths is None/empty, auto-detect all available tables
    Returns:
        List of (method_table, class_table) tuples
    """
    global table_prefix_map
    # Use parent database directory (where create_tables.py puts tables)
    # Check if running from code_qa directory - if so, use parent database
    if os.path.exists("database") and os.path.exists("../database"):
        # Prefer parent database (where _GameData tables are)
        uri = "../database"
    else:
        uri = "database"
    db = lancedb.connect(uri)
    
    table_sets = []
    
    # Auto-detect: find all available method/class table pairs
    if auto_detect and (codebase_paths is None or (isinstance(codebase_paths, list) and len(codebase_paths) == 0)):
        try:
            tables_response = db.list_tables()
            # Extract table names from the response object
            available_tables = tables_response.tables if hasattr(tables_response, 'tables') else []
            # Find all method/class table pairs
            method_tables = {t for t in available_tables if isinstance(t, str) and t.endswith("_method")}
            class_tables = {t for t in available_tables if isinstance(t, str) and t.endswith("_class")}
            
            # Match method and class tables by prefix
            for method_table_name in method_tables:
                prefix = method_table_name[:-7]  # Remove "_method"
                class_table_name = prefix + "_class"
                
                if class_table_name in class_tables:
                    try:
                        method_table = db.open_table(method_table_name)
                        class_table = db.open_table(class_table_name)
                        table_pair = (method_table, class_table)
                        table_sets.append(table_pair)
                        # Store prefix mapping for efficient filtering
                        table_prefix_map[table_pair] = prefix
                        print(f"Auto-loaded tables: {method_table_name}, {class_table_name} (prefix: {prefix})")
                    except Exception as e:
                        print(f"Warning: Could not open {method_table_name}/{class_table_name}: {e}")
        except Exception as e:
            print(f"Warning: Could not auto-detect tables: {e}")
    
    # Manual loading from provided paths
    if codebase_paths:
        if isinstance(codebase_paths, str):
            codebase_paths = [codebase_paths]
        
        for codebase_path in codebase_paths:
            normalized_path = os.path.normpath(os.path.abspath(codebase_path))
            codebase_folder_name = os.path.basename(normalized_path)
            
            try:
                method_table = db.open_table(codebase_folder_name + "_method")
                class_table = db.open_table(codebase_folder_name + "_class")
                table_pair = (method_table, class_table)
                table_sets.append(table_pair)
                # Store prefix mapping
                table_prefix_map[table_pair] = codebase_folder_name
                print(f"Loaded tables for {codebase_folder_name}")
            except Exception as e:
                print(f"Warning: Could not open tables for {codebase_folder_name}: {e}")
    
    return table_sets

# Application setup
def setup_app():
    app = Flask(__name__)
    app.config.update(CONFIG)
    
    # Setup logging
    app.logger = setup_logging(app.config)
    
    # Redis connection pooling setup
    app.redis_pool = ConnectionPool(
        host=app.config['REDIS_HOST'],
        port=app.config['REDIS_PORT'],
        db=app.config['REDIS_DB'],
        max_connections=app.config['REDIS_POOL_SIZE']
    )
    
    # Create Redis client using the connection pool
    app.redis_client = redis.Redis(connection_pool=app.redis_pool)
    
    # Markdown filter
    @app.template_filter('markdown')
    def markdown_filter(text):
        return markdown.markdown(text, extensions=['fenced_code', 'tables'])
    
    return app

# Create the Flask app
app = setup_app()

# Global table sets (will be initialized in main)
table_sets = []
# Store table prefix mapping: (method_table, class_table) -> prefix
table_prefix_map = {}
method_table = None
class_table = None

# Create time_logs directory
TIME_LOGS_DIR = Path("time_logs")
TIME_LOGS_DIR.mkdir(exist_ok=True)

# Helper function for consistent path normalization (must be defined before use)
def normalize_path_consistent(p):
    """
    Consistent path normalization used throughout the app.
    Returns normalized path or None if invalid.
    """
    if p is None:
        return None
    try:
        p_str = str(p).strip()
        if not p_str:
            return None
        # Always convert to absolute and normalize case
        abs_path = os.path.abspath(p_str)
        norm_path = os.path.normcase(abs_path)
        return norm_path
    except Exception as e:
        return None

# Load indexed C# files for sidebar display and file filtering
INDEXED_CS_FILES = []
INDEXED_FILES_BY_NAME = {}
INDEXED_CS_JSON = Path("indexed_cs_files.json")
if INDEXED_CS_JSON.exists():
    try:
        with INDEXED_CS_JSON.open("r", encoding="utf-8") as f:
            INDEXED_CS_FILES = json.load(f)
        for entry in INDEXED_CS_FILES:
            name = entry.get("file_name")
            path = entry.get("absolute_path")
            if not name or not path:
                continue
            norm_path = normalize_path_consistent(path)
            INDEXED_FILES_BY_NAME.setdefault(name, []).append(norm_path)
        app.logger.info(f"Loaded {len(INDEXED_CS_FILES)} indexed C# files from {INDEXED_CS_JSON}")
    except Exception as e:
        app.logger.warning(f"Failed to load indexed_cs_files.json: {e}")
else:
    app.logger.warning("indexed_cs_files.json not found; sidebar file list and @cs filters will be limited.")


def save_timing_log(timing_data):
    """Save timing log data to a JSON file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = TIME_LOGS_DIR / f"timing_log_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(timing_data, f, indent=2, ensure_ascii=False)
    
    app.logger.info(f"[TIMING LOG] Saved to {filename}")

# OpenAI client setup - Support Qwen/DashScope
api_key = os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise ValueError("QWEN_API_KEY, DASHSCOPE_API_KEY, or OPENAI_API_KEY environment variable must be set")

# Use DashScope compatible base URL if using Qwen/DashScope
base_url = None
if os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"):
    base_url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"  # International endpoint
    app.logger.info("Using DashScope/Qwen API with international compatible endpoint")
else:
    app.logger.info("Using OpenAI API")

client = OpenAI(api_key=api_key, base_url=base_url)

# Get LLM models from environment or use defaults
# Use qwen-plus for HYDE v2 (quality), qwen-flash for answers (fastest)
_hyde_model = os.environ.get("HYDE_MODEL", "qwen-plus")  # qwen-plus for HYDE v2 quality
_answer_model = os.environ.get("ANSWER_MODEL", "qwen-flash")  # qwen-flash for fastest answer generation
app.logger.info(f"Using HYDE model: {_hyde_model}")
app.logger.info(f"Using Answer model: {_answer_model}")

# Initialize the reranker (may be disabled if torch issues occur)
try:
    reranker = AnswerdotaiRerankers(column="source_code")
    app.logger.info("Reranker initialized successfully")
except Exception as e:
    app.logger.warning(f"Reranker initialization failed: {e}. Reranking will be disabled.")
    reranker = None

# Helper functions for file-scoped queries
def _resolve_cs_file_filters(raw_files):
    """
    Convert a list of user-specified file tokens (names or paths) into a list
    of normalized absolute paths using indexed_cs_files.json as the source of truth.
    
    Improved to handle:
    - Case-insensitive filename matching
    - Multiple files with same name
    - Partial path matching
    - Direct absolute path input
    - Relative paths that need to be resolved
    """
    if not raw_files:
        return None

    resolved_paths = []

    for token in raw_files:
        if not token:
            continue
        token = token.strip()

        # Normalize the token for comparison
        norm_token = normalize_path_consistent(token)
        
        # Absolute path case - normalize and add directly
        if os.path.isabs(token):
            if token.lower().endswith(".cs") and norm_token:
                resolved_paths.append(norm_token)
                continue
            # Even if not .cs, try to normalize and check if it exists in indexed files
            if norm_token:
                # Check if this normalized path exists in our indexed files
                for entry in INDEXED_CS_FILES:
                    entry_path = entry.get("absolute_path")
                    if entry_path:
                        entry_norm = normalize_path_consistent(entry_path)
                        if entry_norm == norm_token:
                            resolved_paths.append(norm_token)
                            break
                continue

        # Extract basename for matching
        basename = os.path.basename(token)
        if not basename.lower().endswith(".cs"):
            # If token doesn't end with .cs, try adding it
            if not basename:
                basename = token
            if not basename.lower().endswith(".cs"):
                basename = basename + ".cs"
        
        basename_lower = basename.lower()
        found_match = False
        
        # First try exact match (case-sensitive) from INDEXED_FILES_BY_NAME
        matches = INDEXED_FILES_BY_NAME.get(basename)
        if matches:
            resolved_paths.extend(matches)
            found_match = True
        
        # Fallback: case-insensitive search through all indexed files
        if not found_match:
            for entry in INDEXED_CS_FILES:
                entry_name = entry.get("file_name", "")
                if entry_name.lower() == basename_lower:
                    entry_path = entry.get("absolute_path")
                    if entry_path:
                        norm_path = normalize_path_consistent(entry_path)
                        if norm_path and norm_path not in resolved_paths:
                            resolved_paths.append(norm_path)
                            found_match = True
        
        # Also try partial path matching (e.g., "Ability/AbilityKamikaze.cs" or "Scripts/GameManager.cs")
        if not found_match and ("/" in token or "\\" in token):
            token_parts = token.replace("\\", "/").split("/")
            filename = token_parts[-1]
            if not filename.lower().endswith(".cs"):
                filename = filename + ".cs"
            
            # Search for files where the path contains the token parts
            for entry in INDEXED_CS_FILES:
                entry_path = entry.get("absolute_path", "")
                entry_name = entry.get("file_name", "")
                if entry_name.lower() == filename.lower():
                    # Check if path segments match
                    entry_parts = entry_path.replace("\\", "/").split("/")
                    # Match if last few segments match
                    if len(token_parts) <= len(entry_parts):
                        # Check if the last N segments of entry_path match token_parts
                        entry_tail = entry_parts[-len(token_parts):]
                        if all(tp.lower() == ep.lower() for tp, ep in zip(token_parts, entry_tail)):
                            norm_path = normalize_path_consistent(entry_path)
                            if norm_path and norm_path not in resolved_paths:
                                resolved_paths.append(norm_path)
                                found_match = True
                                break

    # Deduplicate while preserving order
    seen = set()
    unique_paths = []
    for p in resolved_paths:
        if p and p not in seen:
            seen.add(p)
            unique_paths.append(p)
    
    # Log resolution results for debugging
    if unique_paths:
        try:
            app.logger.info(f"[FILE RESOLUTION] Resolved {len(raw_files)} token(s) to {len(unique_paths)} path(s)")
            for i, (token, path) in enumerate(zip(raw_files, unique_paths[:3])):
                app.logger.info(f"  {token} -> {path}")
        except:
            pass

    return unique_paths or None


def parse_cs_file_filter(raw_query):
    """
    Parse @cs directives of the form:
      '@cs GameManager.cs: summarise the class'
      '@codebase @cs GameManager.cs, SceneLoader.cs: how do scenes transition?'
      '@DatabaseManager.cs summarise this' (simpler format)
      '@DatabaseManager.cs, GameManager.cs: query' (multiple files with colon)

    Returns:
      clean_query (str): query text with the @cs/@filename prefixes removed
      resolved_paths (List[str] | None): list of absolute paths to filter on
    """
    resolved_paths = None
    
    # Pattern 1: @cs filename: query (original format)
    pattern1 = r"@cs\s+([^:]+):(.*)"
    match1 = re.search(pattern1, raw_query, flags=re.IGNORECASE | re.DOTALL)
    if match1:
        files_part, question_part = match1.groups()
        raw_files = [f.strip() for f in files_part.split(",") if f.strip()]
        resolved_paths = _resolve_cs_file_filters(raw_files)
        clean_query = question_part.strip()
        return clean_query, resolved_paths
    
    # Pattern 2: @filename.cs query (simpler format without @cs prefix)
    # Match @ followed by filename ending in .cs, then optional colon or space, then query
    pattern2 = r"@([A-Za-z0-9_\.]+\.cs)(?:\s*[:,]?\s*|\s+)(.*)"
    match2 = re.search(pattern2, raw_query, flags=re.IGNORECASE)
    if match2:
        filename, question_part = match2.groups()
        raw_files = [filename.strip()]
        resolved_paths = _resolve_cs_file_filters(raw_files)
        clean_query = question_part.strip()
        # If query is empty, try to extract from the rest of the string
        if not clean_query:
            # Remove the @filename.cs part and use the rest
            clean_query = re.sub(r"@" + re.escape(filename) + r"(?:\s*[:,]?\s*|\s+)", "", raw_query, flags=re.IGNORECASE).strip()
        return clean_query, resolved_paths
    
    # Pattern 3: Multiple @filename.cs files
    # Match multiple @filename.cs patterns
    pattern3 = r"@([A-Za-z0-9_\.]+\.cs)(?:\s*,\s*@([A-Za-z0-9_\.]+\.cs))*\s*[:,]?\s*(.*)"
    match3 = re.search(pattern3, raw_query, flags=re.IGNORECASE)
    if match3:
        first_file = match3.group(1)
        other_files = [g for g in match3.groups()[1:] if g and g.endswith('.cs')]
        question_part = match3.group(match3.lastindex) if match3.lastindex else ""
        raw_files = [first_file] + other_files
        resolved_paths = _resolve_cs_file_filters(raw_files)
        clean_query = question_part.strip()
        return clean_query, resolved_paths
    
    return raw_query, None


# Replace groq_hyde function
def openai_hyde(query):
    start_time = time.time()
    stream = client.chat.completions.create(
        model=_hyde_model,
        messages=[
            {
                "role": "system",
                "content": HYDE_SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": f"Help predict the answer to the query: {query}",
            }
        ],
        stream=True
    )
    
    first_token_time = None
    token_count = 0
    full_response = ""
    
    for chunk in stream:
        if chunk.choices[0].delta.content:
            if first_token_time is None:
                first_token_time = time.time() - start_time
            token_count += 1
            full_response += chunk.choices[0].delta.content
    
    total_time = time.time() - start_time
    token_rate = token_count / (total_time - first_token_time) if first_token_time and (total_time - first_token_time) > 0 else 0
    
    timing_data = {
        "total_time": round(total_time, 2),
        "ttft": round(first_token_time, 2) if first_token_time else None,
        "token_count": token_count,
        "token_rate": round(token_rate, 1) if token_rate > 0 else None,
        "response_length": len(full_response)
    }
    
    if first_token_time:
        app.logger.info(f"[HYDE GENERATION] Completed in {total_time:.2f}s | TTFT: {first_token_time:.2f}s | Tokens: {token_count} | Rate: {token_rate:.1f} tokens/s")
    else:
        app.logger.info(f"[HYDE GENERATION] Completed in {total_time:.2f}s")
    
    return full_response, timing_data

def openai_hyde_v2(query, temp_context, hyde_query):
    start_time = time.time()
    # Note: hyde_query parameter now contains the original query (Stage 1 removed)
    stream = client.chat.completions.create(
        model=_hyde_model,
        messages=[
            {
                "role": "system",
                "content": HYDE_V2_SYSTEM_PROMPT.format(query=query, temp_context=temp_context)
            },
            {
                "role": "user",
                "content": f"Enhance the query: {hyde_query}",
            }
        ],
        stream=True
    )
    
    first_token_time = None
    token_count = 0
    full_response = ""
    
    for chunk in stream:
        if chunk.choices[0].delta.content:
            if first_token_time is None:
                first_token_time = time.time() - start_time
            token_count += 1
            full_response += chunk.choices[0].delta.content
    
    total_time = time.time() - start_time
    token_rate = token_count / (total_time - first_token_time) if first_token_time and (total_time - first_token_time) > 0 else 0
    
    timing_data = {
        "total_time": round(total_time, 2),
        "ttft": round(first_token_time, 2) if first_token_time else None,
        "token_count": token_count,
        "token_rate": round(token_rate, 1) if token_rate > 0 else None,
        "response_length": len(full_response)
    }
    
    if first_token_time:
        app.logger.info(f"[HYDE v2 GENERATION] Completed in {total_time:.2f}s | TTFT: {first_token_time:.2f}s | Tokens: {token_count} | Rate: {token_rate:.1f} tokens/s")
    else:
        app.logger.info(f"[HYDE v2 GENERATION] Completed in {total_time:.2f}s")
    
    return full_response, timing_data


def openai_chat(query, context):
    start_time = time.time()
    stream = client.chat.completions.create(
        model=_answer_model,  # Use qwen-flash for fastest answer generation
        messages=[
            {
                "role": "system",
                "content": CHAT_SYSTEM_PROMPT.format(context=context)
            },
            {
                "role": "user",
                "content": (
                    "You must answer the following question using ONLY the code "
                    "shown in the system context. If the answer is not present "
                    "in that code, explicitly say that it is not implemented or "
                    "cannot be determined from the available code.\n\n"
                    f"Question: {query}"
                ),
            }
        ],
        stream=True,
        max_tokens=2000,  # Limit response length to prevent overly long answers
        temperature=0  # More deterministic responses
    )
    
    first_token_time = None
    token_count = 0
    full_response = ""
    
    for chunk in stream:
        if chunk.choices[0].delta.content:
            if first_token_time is None:
                first_token_time = time.time() - start_time
            token_count += 1
            full_response += chunk.choices[0].delta.content
    
    total_time = time.time() - start_time
    token_rate = token_count / (total_time - first_token_time) if first_token_time and (total_time - first_token_time) > 0 else 0
    
    timing_data = {
        "total_time": round(total_time, 2),
        "ttft": round(first_token_time, 2) if first_token_time else None,
        "token_count": token_count,
        "token_rate": round(token_rate, 1) if token_rate > 0 else None,
        "response_length": len(full_response)
    }
    
    if first_token_time:
        app.logger.info(f"[ANSWER GENERATION] Completed in {total_time:.2f}s | TTFT: {first_token_time:.2f}s | Tokens: {token_count} | Rate: {token_rate:.1f} tokens/s | Response: {len(full_response)} chars")
    else:
        app.logger.info(f"[ANSWER GENERATION] Completed in {total_time:.2f}s | Response: {len(full_response)} chars")
    
    return full_response, timing_data

def process_input(input_text):
    processed_text = input_text.replace('\n', ' ').replace('\t', ' ')
    processed_text = re.sub(r'\s+', ' ', processed_text)
    processed_text = processed_text.strip()
    
    return processed_text

def _filter_docs_by_files(docs, allowed_paths):
    """Filter LanceDB result docs to only those whose file_path is in allowed_paths.
    Uses consistent path normalization for reliable matching.
    """
    if not allowed_paths:
        return docs

    # Use consistent normalization
    allowed_set = {normalize_path_consistent(p) for p in allowed_paths if normalize_path_consistent(p) is not None}
    if not allowed_set:
        return docs
    
    filtered = []
    for doc in docs:
        file_path = doc.get("file_path")
        if not file_path:
            continue
        norm = normalize_path_consistent(file_path)
        if norm and norm in allowed_set:
            filtered.append(doc)
    return filtered


def generate_context(query, rerank=False, file_filters=None, table_sets=None):
    start_time = time.time()
    app.logger.info(f"[CONTEXT RETRIEVAL] Query: {query}")
    
    # Use provided table_sets or fall back to global
    if table_sets is None or len(table_sets) == 0:
        # Fallback to global if not provided
        global method_table, class_table
        if method_table is not None and class_table is not None:
            table_sets = [(method_table, class_table)]
        else:
            raise ValueError("No table sets available and no fallback tables found")
    
    # OPTIMIZATION: If file filters exist, use SQLite index to determine which table sets to search
    filtered_table_sets = table_sets
    if file_filters:
        table_prefixes = get_tables_for_files(file_filters, table_sets=table_sets)
        if table_prefixes:
            # Filter table_sets to only those containing the target files
            filtered_table_sets = []
            for table_pair in table_sets:
                prefix = table_prefix_map.get(table_pair)
                if prefix and prefix in table_prefixes:
                    filtered_table_sets.append(table_pair)
                    app.logger.info(f"[CONTEXT RETRIEVAL] Using table set with prefix: {prefix} (contains target files)")
                elif not prefix:
                    # If prefix not in map, include it (safe fallback for manually loaded tables)
                    filtered_table_sets.append(table_pair)
            
            if not filtered_table_sets:
                app.logger.warning(f"[CONTEXT RETRIEVAL] No table sets match file filters, using all tables")
                filtered_table_sets = table_sets
            else:
                app.logger.info(f"[CONTEXT RETRIEVAL] Filtered to {len(filtered_table_sets)} table set(s) containing target files")
        else:
            app.logger.info(f"[CONTEXT RETRIEVAL] File index lookup found no matching tables, searching all tables")
    
    timing_info = {
        "query": query,
        "rerank_enabled": rerank
    }
    
    # Step 1: Initial search with original query across filtered table sets
    search_start = time.time()
    all_method_dfs = []
    all_class_dfs = []
    
    # If file filters are specified, also do a direct file lookup to ensure we get results
    # from the target files even if semantic search doesn't return them
    if file_filters:
        allowed_set = {normalize_path_consistent(p) for p in file_filters if normalize_path_consistent(p) is not None}
        app.logger.info(f"[CONTEXT RETRIEVAL] Performing direct file lookup for {len(allowed_set)} file(s)")
        
        # Direct lookup: get all chunks from target files
        for method_table, class_table in filtered_table_sets:
            try:
                method_df_direct = method_table.to_pandas()
                if not method_df_direct.empty and "file_path" in method_df_direct.columns:
                    method_df_direct["normalized_path"] = method_df_direct["file_path"].apply(normalize_path_consistent)
                    method_df_direct = method_df_direct[method_df_direct["normalized_path"].isin(allowed_set)]
                    if not method_df_direct.empty:
                        all_method_dfs.append(method_df_direct)
                        app.logger.info(f"[CONTEXT RETRIEVAL] Direct lookup found {len(method_df_direct)} method chunks from target files")
            except Exception as e:
                app.logger.warning(f"[CONTEXT RETRIEVAL] Direct file lookup error for methods: {e}")
            
            try:
                class_df_direct = class_table.to_pandas()
                if not class_df_direct.empty and "file_path" in class_df_direct.columns:
                    class_df_direct["normalized_path"] = class_df_direct["file_path"].apply(normalize_path_consistent)
                    class_df_direct = class_df_direct[class_df_direct["normalized_path"].isin(allowed_set)]
                    if not class_df_direct.empty:
                        all_class_dfs.append(class_df_direct)
                        app.logger.info(f"[CONTEXT RETRIEVAL] Direct lookup found {len(class_df_direct)} class chunks from target files")
            except Exception as e:
                app.logger.warning(f"[CONTEXT RETRIEVAL] Direct file lookup error for classes: {e}")
    
    # Also do semantic search to get relevant chunks (may include target files or related files)
    for method_table, class_table in filtered_table_sets:
        method_search = method_table.search(query).limit(20)  # broaden, we'll filter down
        class_search = class_table.search(query).limit(20)
        all_method_dfs.append(method_search.to_pandas())
        all_class_dfs.append(class_search.to_pandas())
    
    # Combine all dataframes (direct lookup + semantic search)
    method_df = pd.concat(all_method_dfs, ignore_index=True) if all_method_dfs else pd.DataFrame()
    class_df = pd.concat(all_class_dfs, ignore_index=True) if all_class_dfs else pd.DataFrame()
    
    # Remove duplicates (in case direct lookup and semantic search both returned the same chunks)
    if not method_df.empty:
        method_df = method_df.drop_duplicates(subset=['file_path', 'name', 'class_name'], keep='first')
    if not class_df.empty:
        class_df = class_df.drop_duplicates(subset=['file_path', 'class_name'], keep='first')

    # Filter semantic search results if file filters are specified
    # (Direct lookup results are already filtered, so we only need to filter semantic search results)
    if file_filters:
        allowed_set = {normalize_path_consistent(p) for p in file_filters if normalize_path_consistent(p) is not None}
        app.logger.info(f"[CONTEXT RETRIEVAL] File filters applied: {len(allowed_set)} file(s)")
        app.logger.info(f"[CONTEXT RETRIEVAL] Allowed paths: {list(allowed_set)[:3]}...")  # Log first 3
        
        if "file_path" in method_df.columns and not method_df.empty:
            before_count = len(method_df)
            # Log sample paths BEFORE filtering to see what's in the DB
            sample_before = method_df["file_path"].head(3).tolist()
            app.logger.info(f"[CONTEXT RETRIEVAL] Sample method paths in DB (before filter): {sample_before}")
            
            # Filter with better error handling using consistent normalization
            def matches_filter(p):
                norm = normalize_path_consistent(p)
                if norm is None:
                    return False
                return norm in allowed_set
            
            method_df = method_df[method_df["file_path"].apply(matches_filter)]
            after_count = len(method_df)
            app.logger.info(f"[CONTEXT RETRIEVAL] Method results: {before_count} -> {after_count} after file filtering")
            if after_count == 0 and before_count > 0:
                # Show what normalized paths look like
                normalized_samples = [normalize_path_consistent(p) for p in sample_before]
                app.logger.warning(f"[CONTEXT RETRIEVAL] No methods matched filter.")
                app.logger.warning(f"[CONTEXT RETRIEVAL] Sample normalized DB paths: {normalized_samples}")
                app.logger.warning(f"[CONTEXT RETRIEVAL] Allowed normalized paths: {list(allowed_set)}")
            elif after_count > 0:
                app.logger.info(f"[CONTEXT RETRIEVAL] ✅ Successfully filtered to {after_count} method chunks from target files")
        if "file_path" in class_df.columns and not class_df.empty:
            before_count = len(class_df)
            # Log sample paths BEFORE filtering to see what's in the DB
            sample_before = class_df["file_path"].head(3).tolist()
            app.logger.info(f"[CONTEXT RETRIEVAL] Sample class paths in DB (before filter): {sample_before}")
            
            # Filter with better error handling using consistent normalization
            def matches_filter(p):
                norm = normalize_path_consistent(p)
                if norm is None:
                    return False
                return norm in allowed_set
            
            class_df = class_df[class_df["file_path"].apply(matches_filter)]
            after_count = len(class_df)
            app.logger.info(f"[CONTEXT RETRIEVAL] Class results: {before_count} -> {after_count} after file filtering")
            if after_count == 0 and before_count > 0:
                # Show what normalized paths look like
                normalized_samples = [normalize_path_consistent(p) for p in sample_before]
                app.logger.warning(f"[CONTEXT RETRIEVAL] No classes matched filter.")
                app.logger.warning(f"[CONTEXT RETRIEVAL] Sample normalized DB paths: {normalized_samples}")
                app.logger.warning(f"[CONTEXT RETRIEVAL] Allowed normalized paths: {list(allowed_set)}")
            elif after_count > 0:
                app.logger.info(f"[CONTEXT RETRIEVAL] ✅ Successfully filtered to {after_count} class chunks from target files")

    # After filtering, clip to 5 rows each
    method_docs = method_df.head(5)
    class_docs = class_df.head(5)
    search_time = time.time() - search_start
    
    # Step 2: Build temporary context and truncate to 6000 chars for faster HYDE v2
    if not method_docs.empty:
        methods_text = "\n".join(method_docs["code"].astype(str))
    else:
        methods_text = ""
    if not class_docs.empty:
        classes_text = "\n".join(class_docs["source_code"].astype(str))
    else:
        classes_text = ""

    temp_context = methods_text + "\n" + classes_text
    temp_context = temp_context[:6000]  # Truncate for faster processing
    
    # Step 3: HYDE v2 query generation (context-aware refinement)
    hyde_query_v2, hyde_v2_timing = openai_hyde_v2(query, temp_context, query)  # Use original query instead of hyde_query
    timing_info["hyde_v2_generation"] = hyde_v2_timing
    
    # Step 4: Final search with HYDE v2 refined query across all table sets
    search_start = time.time()
    all_method_docs = []
    all_class_docs = []
    
    for method_table, class_table in filtered_table_sets:
        method_search = method_table.search(hyde_query_v2)
        class_search = class_table.search(hyde_query_v2)
        
        # Step 5: Reranking (if enabled and reranker available)
        if rerank and reranker is not None:
            method_search = method_search.rerank(reranker)
            class_search = class_search.rerank(reranker)
        
        # Step 6: Limit and convert to list
        method_docs = method_search.limit(10).to_list()
        class_docs = class_search.limit(10).to_list()
        all_method_docs.extend(method_docs)
        all_class_docs.extend(class_docs)
    
    # Combine and optionally filter to selected files
    method_docs = all_method_docs
    class_docs = all_class_docs

    method_docs = _filter_docs_by_files(method_docs, file_filters)
    class_docs = _filter_docs_by_files(class_docs, file_filters)
    search_time += time.time() - search_start
    timing_info["vector_search_time"] = round(search_time, 2)
    
    # Debug/logging: show which chunks were selected for this query
    try:
        app.logger.info("[CONTEXT RETRIEVAL] Selected method chunks:")
        for doc in method_docs:
            app.logger.info(
                f"  METHOD | file={doc.get('file_path')} | class={doc.get('class_name')} | name={doc.get('name')}"
            )
        app.logger.info("[CONTEXT RETRIEVAL] Selected class chunks:")
        for doc in class_docs:
            app.logger.info(
                f"  CLASS  | file={doc.get('file_path')} | class={doc.get('class_name')}"
            )
    except Exception as e:
        app.logger.warning(f"[CONTEXT RETRIEVAL] Failed to log selected chunks: {e}")

    # Step 7: Combine top results
    top_3_methods = method_docs[:3]
    methods_combined = "\n\n".join(f"File: {doc['file_path']}\nCode:\n{doc['code']}" for doc in top_3_methods)
    
    top_3_classes = class_docs[:3]
    classes_combined = "\n\n".join(f"File: {doc['file_path']}\nClass Info:\n{doc['source_code']} References: \n{doc['references']}  \n END OF ROW {i}" for i, doc in enumerate(top_3_classes))
    
    final_context = methods_combined + "\n below is class or constructor related code \n" + classes_combined
    
    total_time = time.time() - start_time
    timing_info["total_time"] = round(total_time, 2)
    timing_info["context_length"] = len(final_context)
    timing_info["results_count"] = {"methods": len(method_docs), "classes": len(class_docs)}
    
    app.logger.info(f"[CONTEXT RETRIEVAL] Completed in {total_time:.2f}s | Vector search: {search_time:.2f}s | Context: {len(final_context)} chars")
    
    return final_context, timing_info

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # This is an AJAX request
            answer_start_time = time.time()
            
            data = request.get_json()
            original_query = data['query']
            rerank = data.get('rerank', False)  # Extract rerank value
            selected_files = data.get('selected_files') or []
            user_id = session.get('user_id')
            if user_id is None:
                user_id = str(uuid.uuid4())
                session['user_id'] = user_id

            app.logger.info(f"[QUERY] {original_query}")

            # Ensure rerank is a boolean
            rerank = True if rerank in [True, 'true', 'True', '1'] else False

            # Parse optional @cs file filter directive and clean query
            cleaned_query, cs_file_filters = parse_cs_file_filter(original_query)
            file_filters = selected_files or cs_file_filters
            
            # Log file filtering info
            if file_filters:
                app.logger.info(f"[QUERY] File filters resolved: {file_filters}")
            if cs_file_filters:
                app.logger.info(f"[QUERY] Parsed @cs filters: {cs_file_filters}")

            # Cleaned user query (no @codebase or @cs boilerplate)
            if '@codebase' in cleaned_query:
                user_query = cleaned_query.replace('@codebase', '').strip()
            else:
                user_query = cleaned_query.strip()

            # Collect all timing data
            timing_log = {
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "query": original_query,
                "cleaned_query": cleaned_query,
                "rerank_enabled": rerank,
                "file_filters": file_filters,
            }

            # Step 1: Always perform context retrieval for this query
            context, context_timing = generate_context(user_query, rerank, file_filters, table_sets)
            timing_log["context_retrieval"] = context_timing
            # Cache last context per user (optional)
            try:
                app.redis_client.set(f"user:{user_id}:chat_context", context)
            except Exception as e:
                app.logger.warning(f"Failed to cache context in Redis: {e}")
            
            # Step 2: Truncate context if needed (reduced from 12000 to 8000 for faster processing)
            context_for_llm = context[:8000]
            if len(context) > 8000:
                timing_log["context_truncated"] = {"original_length": len(context), "truncated_length": len(context_for_llm)}

            # Step 3: Generate answer using LLM
            response, answer_timing = openai_chat(user_query or cleaned_query, context_for_llm)
            timing_log["answer_generation"] = answer_timing

            # Step 4: Store conversation history
            redis_key = f"user:{user_id}:responses"
            combined_response = {'query': original_query, 'response': response}
            app.redis_client.rpush(redis_key, json.dumps(combined_response))

            total_time = time.time() - answer_start_time
            timing_log["total_time"] = round(total_time, 2)
            
            # Save timing log to JSON file
            save_timing_log(timing_log)
            
            app.logger.info(f"[TOTAL TIME] {total_time:.2f}s")
            app.logger.info("=" * 80)

            # Return the bot's response as JSON
            return jsonify({'response': response})

    # For GET requests and non-AJAX POST requests, render the template as before
    # Retrieve the conversation history to display
    user_id = session.get('user_id')
    if user_id:
        redis_key = f"user:{user_id}:responses"
        responses = app.redis_client.lrange(redis_key, -5, -1)
        responses = [json.loads(resp.decode()) for resp in responses]
        results = {'responses': responses}
    else:
        results = None

        # Group indexed files by folder for sidebar display
        files_by_folder = {}
        for f in INDEXED_CS_FILES:
            folder_name = "Other"
            if "_GameModules" in f.get("absolute_path", ""):
                folder_name = "GameModules"
            elif "_GamePlay" in f.get("absolute_path", ""):
                folder_name = "Gameplay"
            elif "_GameData" in f.get("absolute_path", ""):
                folder_name = "GameData"
            elif "_ExternalAssets" in f.get("absolute_path", ""):
                folder_name = "ExternalAssets"
            
            if folder_name not in files_by_folder:
                files_by_folder[folder_name] = []
            files_by_folder[folder_name].append(f)
        
        return render_template('query_form.html', results=results, indexed_files=INDEXED_CS_FILES, files_by_folder=files_by_folder)

if __name__ == "__main__":
    # Allow running without arguments - will auto-detect all available tables
    if len(sys.argv) < 2:
        print("No paths provided. Auto-detecting all available tables...")
        codebase_paths = None
    else:
        codebase_paths = sys.argv[1:]
    
    # Setup database - will auto-detect if no paths provided
    table_sets = setup_database(codebase_paths, auto_detect=True)
    # table_prefix_map is populated inside setup_database
    
    # For backward compatibility, also set global method_table and class_table
    # (use the first table set as default)
    if table_sets:
        method_table, class_table = table_sets[0]
    else:
        raise ValueError("No valid table sets found. Please check your database setup.")
    
    # Log which tables are loaded
    print(f"\n{'='*80}")
    print(f"✅ Loaded {len(table_sets)} table set(s)")
    if codebase_paths:
        print(f"   From paths: {codebase_paths}")
    else:
        print(f"   Auto-detected all available tables")
    print(f"{'='*80}\n")
    
    app.logger.info(f"Loaded {len(table_sets)} table set(s)")
    for i, (mt, ct) in enumerate(table_sets, 1):
        try:
            mt_name = str(mt).split("'")[1] if "'" in str(mt) else "unknown"
            ct_name = str(ct).split("'")[1] if "'" in str(ct) else "unknown"
            app.logger.info(f"  Table set {i}: {mt_name} / {ct_name}")
        except:
            app.logger.info(f"  Table set {i}: loaded")
    
    app.run(host='0.0.0.0', port=5001)
