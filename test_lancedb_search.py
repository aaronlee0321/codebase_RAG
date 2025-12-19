#!/usr/bin/env python3
"""
Script to test LanceDB search across all table sets, simulating what the app does.
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

def test_search(query, target_file=None):
    """Test search across all table sets, simulating app.py behavior"""
    print("="*80)
    print(f"Testing search for query: '{query}'")
    if target_file:
        print(f"Target file filter: {target_file}")
    print("="*80)
    
    uri = "database"
    db = lancedb.connect(uri)
    
    # Table sets to check (same as what app.py should use)
    table_sets = [
        ("Scripts_method", "Scripts_class"),
        ("_GameData_method", "_GameData_class")
    ]
    
    all_method_dfs = []
    all_class_dfs = []
    
    for method_table_name, class_table_name in table_sets:
        print(f"\n--- Checking {method_table_name} and {class_table_name} ---")
        
        try:
            method_table = db.open_table(method_table_name)
            class_table = db.open_table(class_table_name)
            
            # Perform search (same as app.py)
            print(f"  Searching {method_table_name}...")
            method_search = method_table.search(query).limit(20)
            method_df = method_search.to_pandas()
            
            print(f"  Searching {class_table_name}...")
            class_search = class_table.search(query).limit(20)
            class_df = class_search.to_pandas()
            
            print(f"  ✅ {method_table_name}: {len(method_df)} results")
            print(f"  ✅ {class_table_name}: {len(class_df)} results")
            
            # Show sample file paths
            if not method_df.empty and "file_path" in method_df.columns:
                unique_method_paths = method_df["file_path"].unique()[:3]
                print(f"  Sample method file paths:")
                for p in unique_method_paths:
                    print(f"    - {p}")
            
            if not class_df.empty and "file_path" in class_df.columns:
                unique_class_paths = class_df["file_path"].unique()[:3]
                print(f"  Sample class file paths:")
                for p in unique_class_paths:
                    print(f"    - {p}")
            
            all_method_dfs.append(method_df)
            all_class_dfs.append(class_df)
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
            continue
    
    # Combine all dataframes (same as app.py)
    print(f"\n--- Combining results from all tables ---")
    if all_method_dfs:
        combined_method_df = pd.concat(all_method_dfs, ignore_index=True)
        print(f"  Combined method results: {len(combined_method_df)} rows")
    else:
        combined_method_df = pd.DataFrame()
        print(f"  No method results")
    
    if all_class_dfs:
        combined_class_df = pd.concat(all_class_dfs, ignore_index=True)
        print(f"  Combined class results: {len(combined_class_df)} rows")
    else:
        combined_class_df = pd.DataFrame()
        print(f"  No class results")
    
    # Apply file filter if provided
    if target_file:
        print(f"\n--- Applying file filter ---")
        allowed_set = {normalize_path(target_file)}
        print(f"  Allowed path (normalized): {list(allowed_set)[0]}")
        
        if not combined_method_df.empty and "file_path" in combined_method_df.columns:
            before_count = len(combined_method_df)
            sample_before = combined_method_df["file_path"].head(3).tolist()
            print(f"  Method results before filter: {before_count}")
            print(f"  Sample paths before filter:")
            for p in sample_before:
                print(f"    - {p}")
                print(f"      Normalized: {normalize_path(p)}")
            
            def matches_filter(p):
                norm = normalize_path(p)
                if norm is None:
                    return False
                return norm in allowed_set
            
            filtered_method_df = combined_method_df[combined_method_df["file_path"].apply(matches_filter)]
            after_count = len(filtered_method_df)
            print(f"  Method results after filter: {after_count}")
            
            if after_count > 0:
                print(f"  ✅ FOUND MATCHING METHODS!")
                print(f"  Sample matches:")
                for idx, row in filtered_method_df.head(3).iterrows():
                    print(f"    - file: {row.get('file_path')}")
                    print(f"      class: {row.get('class_name')}")
                    print(f"      method: {row.get('name')}")
            else:
                print(f"  ❌ NO MATCHING METHODS FOUND")
        
        if not combined_class_df.empty and "file_path" in combined_class_df.columns:
            before_count = len(combined_class_df)
            sample_before = combined_class_df["file_path"].head(3).tolist()
            print(f"  Class results before filter: {before_count}")
            print(f"  Sample paths before filter:")
            for p in sample_before:
                print(f"    - {p}")
                print(f"      Normalized: {normalize_path(p)}")
            
            def matches_filter(p):
                norm = normalize_path(p)
                if norm is None:
                    return False
                return norm in allowed_set
            
            filtered_class_df = combined_class_df[combined_class_df["file_path"].apply(matches_filter)]
            after_count = len(filtered_class_df)
            print(f"  Class results after filter: {after_count}")
            
            if after_count > 0:
                print(f"  ✅ FOUND MATCHING CLASSES!")
                print(f"  Sample matches:")
                for idx, row in filtered_class_df.head(3).iterrows():
                    print(f"    - file: {row.get('file_path')}")
                    print(f"      class: {row.get('class_name')}")
            else:
                print(f"  ❌ NO MATCHING CLASSES FOUND")
    else:
        # Show all unique file paths
        print(f"\n--- All unique file paths in results ---")
        if not combined_method_df.empty and "file_path" in combined_method_df.columns:
            unique_paths = combined_method_df["file_path"].unique()
            print(f"  Method files ({len(unique_paths)} unique):")
            for p in unique_paths[:10]:
                print(f"    - {p}")
        
        if not combined_class_df.empty and "file_path" in combined_class_df.columns:
            unique_paths = combined_class_df["file_path"].unique()
            print(f"  Class files ({len(unique_paths)} unique):")
            for p in unique_paths[:10]:
                print(f"    - {p}")

def main():
    # Test queries
    test_queries = [
        ("summarise this", r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GameData\Scripts\DatabaseManager.cs"),
        ("DatabaseManager", r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GameData\Scripts\DatabaseManager.cs"),
        ("GameDatabase", r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GameData\Scripts\GameDatabase.cs"),
    ]
    
    for query, target_file in test_queries:
        test_search(query, target_file)
        print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()

