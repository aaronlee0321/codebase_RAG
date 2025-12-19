#!/usr/bin/env python3
"""
Script to check if DatabaseManager.cs and GameDatabase.cs chunks are properly indexed in LanceDB.
"""

import os
import sys
import lancedb
import pandas as pd
from pathlib import Path

# Add parent directory to path to import create_tables (for embedding function registration)
sys.path.insert(0, str(Path(__file__).parent))
import create_tables

def normalize_path(p):
    """Normalize a file path for comparison"""
    if pd.isna(p) or p is None:
        return None
    try:
        p_str = str(p).strip()
        if not p_str:
            return None
        if os.path.isabs(p_str):
            return os.path.normcase(os.path.abspath(p_str))
        else:
            return os.path.normcase(os.path.abspath(p_str))
    except:
        return os.path.normcase(str(p)) if p else None

def check_table(table_name, target_files):
    """Check a specific table for target files"""
    print(f"\n{'='*80}")
    print(f"Checking table: {table_name}")
    print(f"{'='*80}")
    
    try:
        # Use the same database path as create_tables.py and app.py
        uri = "database"  # Relative to codebase_RAG root
        # If running from code_qa directory, go up one level
        if Path("database").exists():
            uri = "database"
        elif Path("../database").exists():
            uri = "../database"
        db = lancedb.connect(uri)
        table = db.open_table(table_name)
        
        # Get all data
        df = table.to_pandas()
        
        if df.empty:
            print(f"  ❌ Table {table_name} is EMPTY!")
            return
        
        print(f"  ✅ Table has {len(df)} rows")
        
        # Check for target files
        if "file_path" not in df.columns:
            print(f"  ❌ Table {table_name} has no 'file_path' column!")
            print(f"  Columns: {list(df.columns)}")
            return
        
        # Normalize target file paths
        target_normalized = {normalize_path(f) for f in target_files}
        
        # Check each target file
        for target_file in target_files:
            target_norm = normalize_path(target_file)
            print(f"\n  Looking for: {target_file}")
            print(f"  Normalized: {target_norm}")
            
            # Find matching rows
            matches = df[df["file_path"].apply(
                lambda p: normalize_path(p) == target_norm
            )]
            
            if matches.empty:
                print(f"  ❌ NO MATCHES FOUND for {target_file}")
                
                # Show sample paths in the table
                sample_paths = df["file_path"].head(5).unique().tolist()
                print(f"  Sample paths in table:")
                for sp in sample_paths:
                    print(f"    - {sp}")
                    print(f"      Normalized: {normalize_path(sp)}")
            else:
                print(f"  ✅ Found {len(matches)} matching row(s)")
                
                # Show details of first match
                first_match = matches.iloc[0]
                print(f"  First match details:")
                print(f"    - file_path: {first_match.get('file_path')}")
                if 'class_name' in first_match:
                    print(f"    - class_name: {first_match.get('class_name')}")
                if 'name' in first_match:
                    print(f"    - name (method): {first_match.get('name')}")
                if 'source_code' in first_match:
                    code_preview = str(first_match.get('source_code', ''))[:200]
                    print(f"    - source_code preview: {code_preview}...")
                if 'code' in first_match:
                    code_preview = str(first_match.get('code', ''))[:200]
                    print(f"    - code preview: {code_preview}...")
        
        # Show all unique file paths in the table
        print(f"\n  All unique file paths in {table_name}:")
        unique_paths = df["file_path"].unique()
        for i, path in enumerate(unique_paths[:10], 1):  # Show first 10
            print(f"    {i}. {path}")
        if len(unique_paths) > 10:
            print(f"    ... and {len(unique_paths) - 10} more")
            
    except Exception as e:
        print(f"  ❌ Error checking table {table_name}: {e}")
        import traceback
        traceback.print_exc()

def main():
    # Target files to check
    target_files = [
        r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GameData\Scripts\DatabaseManager.cs",
        r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GameData\Scripts\GameDatabase.cs"
    ]
    
    print("="*80)
    print("LanceDB Chunk Verification Script")
    print("="*80)
    print(f"\nChecking for chunks from:")
    for f in target_files:
        print(f"  - {f}")
    
    # Check both method and class tables for both folders
    tables_to_check = [
        "Scripts_method",
        "Scripts_class",
        "_GameData_method",
        "_GameData_class"
    ]
    
    for table_name in tables_to_check:
        check_table(table_name, target_files)
    
    print(f"\n{'='*80}")
    print("Summary")
    print(f"{'='*80}")
    print("\nIf chunks are found in _GameData_method or _GameData_class tables,")
    print("then they are properly indexed. If not, the tables may need to be recreated.")
    print("\nIf chunks are only in Scripts tables, then the preprocessing/indexing")
    print("for _GameData folder may not have worked correctly.")

if __name__ == "__main__":
    main()

