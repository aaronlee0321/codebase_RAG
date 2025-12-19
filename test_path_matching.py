#!/usr/bin/env python3
"""
Test script to diagnose path matching issues between database and filters.
Run this to verify that path normalization and filtering work correctly.
"""

import os
import sys
import lancedb
import pandas as pd
from pathlib import Path

def normalize_path_consistent(p):
    """Consistent path normalization used throughout the app."""
    if p is None:
        return None
    try:
        p_str = str(p).strip()
        if not p_str:
            return None
        abs_path = os.path.abspath(p_str)
        norm_path = os.path.normcase(abs_path)
        return norm_path
    except Exception as e:
        return None

def main():
    # Connect to database
    if os.path.exists("../database"):
        uri = "../database"
    else:
        uri = "database"
    
    db = lancedb.connect(uri)
    table = db.open_table("_GameModules_method")
    df = table.to_pandas()
    
    # Test file path
    target_file = "AbilityBearTrap.cs"
    filter_path = r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GameModules\TankFusionModule\Scripts\Ability\AbilityBearTrap.cs"
    filter_norm = normalize_path_consistent(filter_path)
    
    print(f"Filter path: {filter_path}")
    print(f"Filter normalized: {filter_norm}")
    print(f"\nSearching for files containing '{target_file}'...")
    print("=" * 80)
    
    # Find all files with AbilityBearTrap in the path
    matches = df[df['file_path'].str.contains('AbilityBearTrap', case=False, na=False)]
    print(f"Found {len(matches)} rows matching 'AbilityBearTrap'")
    
    if len(matches) > 0:
        unique_paths = matches['file_path'].unique()
        print(f"\nUnique paths in DB ({len(unique_paths)}):")
        for i, path in enumerate(unique_paths[:5], 1):
            norm_db = normalize_path_consistent(path)
            matches_filter = (norm_db == filter_norm)
            print(f"  {i}. {path}")
            print(f"     Normalized: {norm_db}")
            print(f"     Matches filter: {matches_filter}")
            print()
        
        # Test filtering
        print("Testing filter function:")
        print("-" * 80)
        def matches_filter(p):
            norm = normalize_path_consistent(p)
            if norm is None:
                return False
            return norm == filter_norm
        
        filtered = df[df["file_path"].apply(matches_filter)]
        print(f"Rows after filtering: {len(filtered)}")
        if len(filtered) > 0:
            print("✅ Filtering works!")
            print(f"Sample rows:")
            for idx, row in filtered.head(3).iterrows():
                print(f"  - {row.get('class_name', 'N/A')}.{row.get('name', 'N/A')}")
        else:
            print("❌ Filtering failed - no rows matched")
            print("\nChecking why...")
            # Check if any paths are close
            all_norms = df['file_path'].apply(normalize_path_consistent)
            close_matches = []
            for norm in all_norms.unique()[:100]:
                if norm and filter_norm and norm.endswith('abilitybeartrap.cs'):
                    close_matches.append(norm)
            if close_matches:
                print(f"Found {len(close_matches)} paths ending with 'abilitybeartrap.cs':")
                for cm in close_matches[:3]:
                    print(f"  {cm}")
    else:
        print(f"❌ No rows found with 'AbilityBearTrap' in file_path")
        print("\nChecking what files ARE in the database...")
        sample_paths = df['file_path'].unique()[:10]
        print("Sample paths in DB:")
        for p in sample_paths:
            print(f"  {p}")

if __name__ == "__main__":
    main()

