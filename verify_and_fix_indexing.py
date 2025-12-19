#!/usr/bin/env python3
"""
Verify that _GameData files are indexed the same way as Scripts files,
and re-index if needed to ensure paths match correctly.
"""

import os
import sys
import lancedb
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import create_tables

def normalize_path(p):
    """Normalize path for comparison"""
    if pd.isna(p) or p is None:
        return None
    try:
        p_str = str(p).strip()
        if not p_str:
            return None
        return os.path.normcase(os.path.abspath(p_str))
    except:
        return os.path.normcase(str(p)) if p else None

def verify_table(table_name, expected_files):
    """Verify a table contains the expected files"""
    print(f"\n{'='*80}")
    print(f"Verifying: {table_name}")
    print(f"{'='*80}")
    
    try:
        uri = "database"
        db = lancedb.connect(uri)
        table = db.open_table(table_name)
        df = table.to_pandas()
        
        if df.empty:
            print(f"  ❌ Table is empty!")
            return False
        
        print(f"  ✅ Table has {len(df)} rows")
        
        # Check file paths
        if "file_path" not in df.columns:
            print(f"  ❌ No file_path column!")
            return False
        
        # Get unique file paths
        unique_paths = df["file_path"].unique()
        print(f"  📁 Found {len(unique_paths)} unique files:")
        for path in unique_paths:
            print(f"     - {path}")
        
        # Check if expected files are present
        expected_normalized = {normalize_path(f) for f in expected_files}
        found_normalized = {normalize_path(p) for p in unique_paths}
        
        missing = expected_normalized - found_normalized
        if missing:
            print(f"  ⚠️  Missing files:")
            for f in missing:
                print(f"     - {f}")
            return False
        else:
            print(f"  ✅ All expected files found!")
            return True
            
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("="*80)
    print("Verifying Indexing: Scripts vs _GameData")
    print("="*80)
    
    # Expected files for Scripts (Gameplay)
    scripts_files = [
        r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GamePlay\Scripts\GameManager.cs",
        r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GamePlay\Scripts\SceneLoader.cs",
        r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GamePlay\Scripts\IInitializableManager.cs",
    ]
    
    # Expected files for _GameData
    gamedata_files = [
        r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GameData\Scripts\DatabaseManager.cs",
        r"C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\tank_online_1-dev\Assets\_GameData\Scripts\GameDatabase.cs",
    ]
    
    print("\n📊 Checking Scripts tables (Gameplay - these work):")
    scripts_method_ok = verify_table("Scripts_method", scripts_files)
    scripts_class_ok = verify_table("Scripts_class", scripts_files)
    
    print("\n📊 Checking _GameData tables (these should match Scripts format):")
    gamedata_method_ok = verify_table("_GameData_method", gamedata_files)
    gamedata_class_ok = verify_table("_GameData_class", gamedata_files)
    
    print("\n" + "="*80)
    print("Summary")
    print("="*80)
    
    if scripts_method_ok and scripts_class_ok:
        print("✅ Scripts tables are correctly indexed")
    else:
        print("❌ Scripts tables have issues")
    
    if gamedata_method_ok and gamedata_class_ok:
        print("✅ _GameData tables are correctly indexed")
        print("\n💡 The indexing is correct! The issue is that your Flask app")
        print("   is not loading the _GameData table set.")
        print("\n   Solution: Restart your Flask app (it will auto-detect all tables):")
        print("   python app.py")
    else:
        print("❌ _GameData tables need to be re-indexed")
        print("\n   Run these commands to re-index:")
        print("   python preprocessing.py '...\\_GameData'")
        print("   python create_tables.py '...\\_GameData'")

if __name__ == "__main__":
    main()

