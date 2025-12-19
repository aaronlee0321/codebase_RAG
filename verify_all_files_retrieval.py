#!/usr/bin/env python3
"""
Comprehensive verification script to test if all indexed files can be retrieved.
For each file, tests a simple query to ensure chunks are accessible.
"""

import os
import sys
import json
import lancedb
import sqlite3
import pandas as pd
from pathlib import Path

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
        return os.path.normcase(os.path.abspath(p_str))
    except:
        return os.path.normcase(str(p)) if p else None

def check_file_in_index(file_path, file_index_path="file_path_index.db"):
    """Check if a file exists in the SQLite index"""
    try:
        conn = sqlite3.connect(file_index_path)
        cursor = conn.cursor()
        
        norm_path = normalize_path(file_path)
        cursor.execute("""
            SELECT COUNT(*) FROM file_chunks 
            WHERE normalized_path = ?
        """, (norm_path,))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0, count
    except Exception as e:
        return False, 0

def check_file_in_lancedb(file_path, table_name, db):
    """Check if a file exists in a LanceDB table"""
    try:
        table = db.open_table(table_name)
        df = table.to_pandas()
        
        if df.empty:
            return False, 0
        
        norm_path = normalize_path(file_path)
        matches = df[df['file_path'].apply(lambda p: normalize_path(p) == norm_path)]
        return not matches.empty, len(matches)
    except Exception as e:
        return False, 0

def test_simple_query(file_path, db):
    """Test a simple query to see if we can retrieve chunks for this file"""
    try:
        # Try to search for the file by its basename
        file_basename = os.path.basename(file_path)
        query = file_basename.replace('.cs', '')
        
        # Search in both method and class tables
        all_tables = ['Scripts_method', 'Scripts_class', '_GameData_method', '_GameData_class', 
                     '_ExternalAssets_method', '_ExternalAssets_class', 
                     '_GameModules_method', '_GameModules_class']
        
        found_chunks = []
        for table_name in all_tables:
            try:
                table = db.open_table(table_name)
                results = table.search(query).limit(5)
                df = results.to_pandas()
                
                if not df.empty:
                    norm_path = normalize_path(file_path)
                    matches = df[df['file_path'].apply(lambda p: normalize_path(p) == norm_path)]
                    if not matches.empty:
                        found_chunks.append((table_name, len(matches)))
            except:
                continue
        
        return len(found_chunks) > 0, found_chunks
    except Exception as e:
        return False, []

def main():
    print("="*80)
    print("Comprehensive File Retrieval Verification")
    print("="*80)
    
    # Load indexed files
    indexed_files_path = "indexed_cs_files.json"
    if not os.path.exists(indexed_files_path):
        print(f"❌ {indexed_files_path} not found!")
        return
    
    with open(indexed_files_path, 'r', encoding='utf-8') as f:
        indexed_files = json.load(f)
    
    print(f"\n📊 Total indexed files: {len(indexed_files)}")
    
    # Connect to databases
    uri = "../database" if os.path.exists("../database") else "database"
    db = lancedb.connect(uri)
    
    file_index_path = "file_path_index.db"
    
    # Statistics
    stats = {
        'total': len(indexed_files),
        'in_sqlite_index': 0,
        'in_lancedb': 0,
        'queryable': 0,
        'missing': [],
        'issues': []
    }
    
    print(f"\n🔍 Verifying each file...")
    print("="*80)
    
    # Test a sample first
    sample_files = indexed_files[:10] if len(indexed_files) > 10 else indexed_files
    
    for i, file_info in enumerate(indexed_files, 1):
        file_path = file_info.get('absolute_path')
        file_name = file_info.get('file_name')
        
        if not file_path:
            stats['issues'].append((file_name, "No absolute_path in JSON"))
            continue
        
        # Check SQLite index
        in_index, index_count = check_file_in_index(file_path, file_index_path)
        if in_index:
            stats['in_sqlite_index'] += 1
        
        # Check LanceDB tables
        in_lancedb = False
        lancedb_count = 0
        for table_suffix in ['_method', '_class']:
            # Try to determine which table set this file belongs to
            if '_GameModules' in file_path:
                table_name = f'_GameModules{table_suffix}'
            elif '_GameData' in file_path:
                table_name = f'_GameData{table_suffix}'
            elif '_ExternalAssets' in file_path:
                table_name = f'_ExternalAssets{table_suffix}'
            elif '_GamePlay' in file_path:
                table_name = f'Scripts{table_suffix}'
            else:
                continue
            
            found, count = check_file_in_lancedb(file_path, table_name, db)
            if found:
                in_lancedb = True
                lancedb_count += count
        
        if in_lancedb:
            stats['in_lancedb'] += 1
        
        # Test simple query
        queryable, chunks = test_simple_query(file_path, db)
        if queryable:
            stats['queryable'] += 1
        else:
            stats['missing'].append((file_name, file_path, in_index, in_lancedb))
        
        # Progress update every 50 files
        if i % 50 == 0:
            print(f"  Processed {i}/{len(indexed_files)} files...")
    
    # Print results
    print("\n" + "="*80)
    print("VERIFICATION RESULTS")
    print("="*80)
    print(f"Total files: {stats['total']}")
    print(f"✅ In SQLite index: {stats['in_sqlite_index']} ({stats['in_sqlite_index']/stats['total']*100:.1f}%)")
    print(f"✅ In LanceDB tables: {stats['in_lancedb']} ({stats['in_lancedb']/stats['total']*100:.1f}%)")
    print(f"✅ Queryable (can retrieve chunks): {stats['queryable']} ({stats['queryable']/stats['total']*100:.1f}%)")
    print(f"❌ Missing/Not queryable: {len(stats['missing'])} ({len(stats['missing'])/stats['total']*100:.1f}%)")
    
    if stats['missing']:
        print(f"\n⚠️  Files that cannot be queried ({len(stats['missing'])} files):")
        print("-"*80)
        for file_name, file_path, in_index, in_lancedb in stats['missing'][:20]:  # Show first 20
            status = []
            if in_index:
                status.append("in_index")
            if in_lancedb:
                status.append("in_lancedb")
            status_str = ", ".join(status) if status else "NOT FOUND"
            print(f"  - {file_name}: {status_str}")
            print(f"    Path: {file_path}")
        
        if len(stats['missing']) > 20:
            print(f"  ... and {len(stats['missing']) - 20} more files")
    
    if stats['issues']:
        print(f"\n⚠️  Issues found ({len(stats['issues'])}):")
        for issue in stats['issues'][:10]:
            print(f"  - {issue[0]}: {issue[1]}")
    
    # Test specific problematic files mentioned by user
    print("\n" + "="*80)
    print("TESTING SPECIFIC FILES MENTIONED BY USER")
    print("="*80)
    
    test_files = [
        "AbilityKamikaze.cs",
        "AbilityStorm.cs", 
        "BounceUI.cs",
        "CameraScreenFXBehaviour.cs",
        "MatchmakingDocument.cs"
    ]
    
    for test_file in test_files:
        print(f"\n📄 Testing: {test_file}")
        # Find the file in indexed files
        found_file = None
        for f in indexed_files:
            if f.get('file_name') == test_file:
                found_file = f
                break
        
        if not found_file:
            print(f"  ❌ File not found in indexed_cs_files.json")
            continue
        
        file_path = found_file['absolute_path']
        print(f"  Path: {file_path}")
        
        # Check SQLite index
        in_index, index_count = check_file_in_index(file_path, file_index_path)
        print(f"  SQLite index: {'✅' if in_index else '❌'} ({index_count} chunks)")
        
        # Check LanceDB
        in_lancedb = False
        lancedb_details = []
        for table_suffix in ['_method', '_class']:
            if '_GameModules' in file_path:
                table_name = f'_GameModules{table_suffix}'
            elif '_GameData' in file_path:
                table_name = f'_GameData{table_suffix}'
            elif '_ExternalAssets' in file_path:
                table_name = f'_ExternalAssets{table_suffix}'
            elif '_GamePlay' in file_path:
                table_name = f'Scripts{table_suffix}'
            else:
                continue
            
            found, count = check_file_in_lancedb(file_path, table_name, db)
            if found:
                in_lancedb = True
                lancedb_details.append(f"{table_name}: {count} chunks")
        
        print(f"  LanceDB: {'✅' if in_lancedb else '❌'}")
        if lancedb_details:
            for detail in lancedb_details:
                print(f"    - {detail}")
        
        # Test query
        queryable, chunks = test_simple_query(file_path, db)
        print(f"  Queryable: {'✅' if queryable else '❌'}")
        if chunks:
            for table_name, count in chunks:
                print(f"    - {table_name}: {count} chunks found")

if __name__ == "__main__":
    main()


