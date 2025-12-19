#!/usr/bin/env python3
"""
Create a SQLite index that maps file paths to table names and row positions.
This enables efficient file-based filtering before vector search.
"""

import os
import sys
import sqlite3
import lancedb
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import create_tables

def normalize_path(p):
    """Normalize a file path for consistent storage and lookup"""
    if pd.isna(p) or p is None:
        return None
    try:
        p_str = str(p).strip()
        if not p_str:
            return None
        return os.path.normcase(os.path.abspath(p_str))
    except:
        return os.path.normcase(str(p)) if p else None

def create_file_index():
    """Create SQLite index of all file paths in LanceDB tables"""
    index_db_path = "file_path_index.db"
    
    # Remove old index if exists
    if os.path.exists(index_db_path):
        os.remove(index_db_path)
    
    # Create new index database
    conn = sqlite3.connect(index_db_path)
    cursor = conn.cursor()
    
    # Create table
    cursor.execute("""
        CREATE TABLE file_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_path TEXT NOT NULL,
            original_path TEXT NOT NULL,
            table_name TEXT NOT NULL,
            chunk_type TEXT NOT NULL,
            class_name TEXT,
            method_name TEXT,
            row_index INTEGER,
            UNIQUE(normalized_path, table_name, row_index)
        )
    """)
    
    # Create index for fast lookups
    cursor.execute("CREATE INDEX idx_normalized_path ON file_chunks(normalized_path)")
    cursor.execute("CREATE INDEX idx_table_name ON file_chunks(table_name)")
    
    # Connect to LanceDB - use parent database (where all tables are stored)
    if os.path.exists("../database"):
        uri = "../database"
    elif os.path.exists("database"):
        uri = "database"
    else:
        raise ValueError("Could not find database directory")
    db = lancedb.connect(uri)
    
    # Get all available tables
    try:
        tables_response = db.list_tables()
        available_tables = tables_response.tables if hasattr(tables_response, 'tables') else []
    except:
        available_tables = []
    
    print(f"Indexing {len(available_tables)} tables...")
    
    total_chunks = 0
    
    # Process each table
    for table_name in available_tables:
        if not isinstance(table_name, str):
            continue
            
        if not (table_name.endswith("_method") or table_name.endswith("_class")):
            continue
        
        try:
            table = db.open_table(table_name)
            df = table.to_pandas()
            
            if df.empty:
                continue
            
            chunk_type = "method" if table_name.endswith("_method") else "class"
            
            print(f"  Processing {table_name} ({len(df)} rows)...")
            
            # Insert each row into index
            for idx, row in df.iterrows():
                file_path = row.get("file_path")
                if not file_path:
                    continue
                
                norm_path = normalize_path(file_path)
                if not norm_path:
                    continue
                
                class_name = row.get("class_name", "")
                method_name = row.get("name", "") if chunk_type == "method" else ""
                
                cursor.execute("""
                    INSERT INTO file_chunks 
                    (normalized_path, original_path, table_name, chunk_type, class_name, method_name, row_index)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (norm_path, str(file_path), table_name, chunk_type, class_name, method_name, idx))
                
                total_chunks += 1
            
            conn.commit()
            print(f"    ✅ Indexed {len(df)} chunks from {table_name}")
            
        except Exception as e:
            print(f"    ❌ Error processing {table_name}: {e}")
            continue
    
    conn.close()
    
    print(f"\n✅ File path index created: {index_db_path}")
    print(f"   Total chunks indexed: {total_chunks}")
    
    # Verify index
    conn = sqlite3.connect(index_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT normalized_path) FROM file_chunks")
    unique_files = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM file_chunks")
    total_rows = cursor.fetchone()[0]
    conn.close()
    
    print(f"   Unique files: {unique_files}")
    print(f"   Total chunk entries: {total_rows}")

if __name__ == "__main__":
    create_file_index()

