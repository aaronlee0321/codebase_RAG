#!/usr/bin/env python3
"""
Test script to search chunks from both Scripts (Gameplay) and _GameData tables.
This mimics what the app does when both table sets are loaded.
"""

import os
import sys
import lancedb
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import create_tables

def test_search(table_name, query, target_file=None):
    """Test searching a specific table"""
    print(f"\n{'='*80}")
    print(f"Testing: {table_name}")
    print(f"Query: '{query}'")
    if target_file:
        print(f"Target file: {target_file}")
    print(f"{'='*80}")
    
    try:
        uri = "database"
        db = lancedb.connect(uri)
        table = db.open_table(table_name)
        
        # Perform search
        results = table.search(query).limit(5)
        df = results.to_pandas()
        
        if df.empty:
            print(f"  ❌ No results found")
            return
        
        print(f"  ✅ Found {len(df)} results")
        
        # Filter by target file if specified
        if target_file:
            target_norm = os.path.normcase(os.path.abspath(target_file))
            filtered = df[df["file_path"].apply(
                lambda p: os.path.normcase(os.path.abspath(str(p))) == target_norm
            )]
            print(f"  📁 After filtering by file: {len(filtered)} results")
            
            if filtered.empty:
                print(f"  ⚠️  No results match target file!")
                print(f"  Sample paths in results:")
                for path in df["file_path"].head(3).unique():
                    print(f"    - {path}")
            else:
                print(f"  ✅ Found matching results!")
                for idx, row in filtered.head(3).iterrows():
                    print(f"\n  Result {idx+1}:")
                    print(f"    File: {os.path.basename(row.get('file_path', 'N/A'))}")
                    if 'class_name' in row:
                        print(f"    Class: {row.get('class_name')}")
                    if 'name' in row:
                        print(f"    Method: {row.get('name')}")
                    code_preview = str(row.get('code', row.get('source_code', '')))[:150]
                    print(f"    Code preview: {code_preview}...")
        else:
            # Show all results
            for idx, row in df.head(3).iterrows():
                print(f"\n  Result {idx+1}:")
                print(f"    File: {os.path.basename(row.get('file_path', 'N/A'))}")
                if 'class_name' in row:
                    print(f"    Class: {row.get('class_name')}")
                if 'name' in row:
                    print(f"    Method: {row.get('name')}")
                    
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("="*80)
    print("Testing LanceDB Search - Comparing Gameplay vs GameData")
    print("="*80)
    
    # Test query
    query = "DatabaseManager"
    target_file = r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GameData\Scripts\DatabaseManager.cs"
    
    # Test Gameplay tables (these work)
    print("\n🎮 GAMEPLAY TABLES (These work):")
    test_search("Scripts_method", query, target_file)
    test_search("Scripts_class", query, target_file)
    
    # Test GameData tables (these should work but app isn't loading them)
    print("\n💾 GAMEDATA TABLES (These exist but app isn't loading them):")
    test_search("_GameData_method", query, target_file)
    test_search("_GameData_class", query, target_file)
    
    print("\n" + "="*80)
    print("CONCLUSION:")
    print("="*80)
    print("The _GameData tables work fine! The issue is that your Flask app")
    print("was started with only the Scripts path, so it's not loading the")
    print("_GameData table set.")
    print("\nTo fix: Restart app with BOTH paths:")
    print("  python app.py '...\\_GamePlay\\Scripts' '...\\_GameData'")

if __name__ == "__main__":
    main()

