#!/usr/bin/env python3
"""
Quick diagnostic script to check what tables exist and what the app should load.
"""

import os
import sys
import lancedb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import create_tables

def main():
    print("="*80)
    print("LanceDB Table Diagnostic")
    print("="*80)
    
    uri = "database"
    db = lancedb.connect(uri)
    
    # List all available tables
    print("\n📊 Available tables in database:")
    try:
        tables = db.list_tables()
        for table in tables:
            print(f"  - {table}")
    except Exception as e:
        print(f"  Error listing tables: {e}")
    
    # Check what tables the app would load based on typical paths
    print("\n🔍 What app.py would load:")
    print("\nIf started with:")
    print("  python app.py '...\\_GamePlay\\Scripts'")
    print("  → Would load: Scripts_method, Scripts_class")
    
    print("\nIf started with:")
    print("  python app.py '...\\_GameData'")
    print("  → Would load: _GameData_method, _GameData_class")
    
    print("\nIf started with BOTH:")
    print("  python app.py '...\\_GamePlay\\Scripts' '...\\_GameData'")
    print("  → Would load: Scripts_method, Scripts_class, _GameData_method, _GameData_class")
    
    # Test opening tables
    print("\n🧪 Testing table access:")
    test_tables = [
        "Scripts_method",
        "Scripts_class", 
        "_GameData_method",
        "_GameData_class"
    ]
    
    for table_name in test_tables:
        try:
            table = db.open_table(table_name)
            df = table.to_pandas()
            print(f"  ✅ {table_name}: {len(df)} rows")
            
            # Show unique file paths if available
            if not df.empty and "file_path" in df.columns:
                unique_paths = df["file_path"].unique()
                print(f"     Files: {len(unique_paths)} unique")
                for path in unique_paths[:2]:
                    print(f"       - {os.path.basename(path)}")
        except Exception as e:
            print(f"  ❌ {table_name}: {e}")
    
    print("\n" + "="*80)
    print("💡 Solution:")
    print("="*80)
    print("Restart your Flask app with BOTH paths:")
    print("  python app.py '...\\_GamePlay\\Scripts' '...\\_GameData'")
    print("\nOr modify app.py to automatically detect and load all available tables.")

if __name__ == "__main__":
    main()

