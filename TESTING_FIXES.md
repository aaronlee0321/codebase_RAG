# Testing Guide for Path Resolution and File Filtering Fixes

## Summary of Fixes

### 1. **Fixed @filename.cs Path Resolution**
- Enhanced `_resolve_cs_file_filters()` to better handle:
  - Filenames without `.cs` extension
  - Case-insensitive matching
  - Partial path matching (e.g., "Scripts/GameManager.cs")
  - Direct absolute path input
- Added logging to track path resolution

### 2. **Improved Path Normalization**
- Moved `normalize_path_consistent()` earlier in the file so it's available during initialization
- Replaced all direct `os.path.normcase(os.path.abspath(...))` calls with `normalize_path_consistent()`
- Ensures consistent path normalization across the entire application

### 3. **Added Fallback Logic**
- Enhanced `get_tables_for_files()` to:
  - Accept optional `table_sets` parameter for fallback search
  - Fall back to direct LanceDB table search when SQLite index lookup fails
  - Search through all available table sets to find matching files

### 4. **Direct File Lookup (Critical Fix)**
- When file filters are specified, the system now:
  1. **First** performs a direct file lookup to get ALL chunks from target files
  2. **Then** performs semantic search to get relevant chunks
  3. Combines both results and removes duplicates
  4. Filters to ensure only target files remain

This ensures that even if semantic search doesn't return the target file in top results, we still get chunks from it.

## How to Test

### Test 1: Basic File Resolution
1. Restart the Flask app:
   ```powershell
   cd "C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\code_qa"
   python app.py
   ```

2. Try queries with different filename formats:
   - `@AbilityBearTrap.cs summarize this`
   - `@AbilityBearTrap summarize this` (without .cs)
   - `@TankFusionModule/Scripts/Ability/AbilityBearTrap.cs summarize this` (partial path)

3. **Expected Results:**
   - Logs should show `[FILE RESOLUTION] Resolved 1 token(s) to 1 path(s)`
   - Logs should show `[CONTEXT RETRIEVAL] Performing direct file lookup for 1 file(s)`
   - Logs should show `[CONTEXT RETRIEVAL] Direct lookup found X method chunks from target files`
   - Logs should show `[CONTEXT RETRIEVAL] ✅ Successfully filtered to X method chunks from target files`
   - The response should contain actual code from AbilityBearTrap.cs, not "There is no logic..."

### Test 2: Path Normalization Consistency
1. Check the logs for path normalization:
   - Look for `[CONTEXT RETRIEVAL] Sample normalized DB paths:` 
   - Look for `[CONTEXT RETRIEVAL] Allowed normalized paths:`
   - These should match (case-insensitive, same absolute path)

2. **Expected Results:**
   - Normalized paths should be consistent (all lowercase, absolute paths)
   - Filter paths should match DB paths after normalization

### Test 3: SQLite Index Fallback
1. Temporarily rename the SQLite index:
   ```powershell
   cd "C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\code_qa"
   rename file_path_index.db file_path_index.bak
   ```

2. Restart the app and try: `@AbilityBearTrap.cs summarize this`

3. **Expected Results:**
   - Logs should show `[FILE INDEX] SQLite lookup failed: ..., trying fallback`
   - Logs should show `[FILE INDEX] Using fallback: searching X table set(s) directly`
   - Logs should show `[FILE INDEX] Fallback: Found files in _GameModules_method table`
   - The query should still work and return results

4. Restore the index:
   ```powershell
   rename file_path_index.bak file_path_index.db
   ```

### Test 4: Direct File Lookup Verification
1. Try a query that semantic search might not return in top results:
   - `@AbilityBearTrap.cs what is the first variable shown`

2. **Expected Results:**
   - Logs should show `[CONTEXT RETRIEVAL] Performing direct file lookup for 1 file(s)`
   - Logs should show `[CONTEXT RETRIEVAL] Direct lookup found X method chunks from target files`
   - Even if semantic search returns 0 results, direct lookup should provide chunks
   - The response should contain actual code from the file

### Test 5: Multiple Files
1. Try querying multiple files:
   - `@AbilityBearTrap.cs, @AbilityKamikaze.cs summarize both files`

2. **Expected Results:**
   - Logs should show `[FILE RESOLUTION] Resolved 2 token(s) to 2 path(s)`
   - Logs should show chunks from both files
   - Response should contain information from both files

## Diagnostic Scripts

### test_path_matching.py
Run this script to verify path matching works correctly:
```powershell
cd "C:\Users\CPU12391\Desktop\GDD_RAG_Gradio\codebase_RAG\code_qa"
python test_path_matching.py
```

**Expected Output:**
- Should find AbilityBearTrap.cs in the database
- Should show that normalized paths match
- Should show "✅ Filtering works!" with sample rows

## Common Issues and Solutions

### Issue: "No methods matched filter"
**Cause:** Path normalization mismatch or file not in database
**Solution:** 
- Check logs for normalized paths comparison
- Verify file exists in database using `test_path_matching.py`
- Ensure SQLite index is up to date

### Issue: "Direct lookup found 0 chunks"
**Cause:** File path doesn't match exactly
**Solution:**
- Check that the file exists in `indexed_cs_files.json`
- Verify path normalization is working correctly
- Check that the file was actually indexed in the database

### Issue: Still getting "There is no logic..."
**Cause:** Direct lookup might be failing or returning empty results
**Solution:**
- Check logs for `[CONTEXT RETRIEVAL] Direct lookup found X chunks`
- Verify the file has actual code chunks (not just empty/placeholder content)
- Check that the file is in the correct table (_GameModules_method vs _GameModules_class)

## Success Indicators

✅ **All tests pass if:**
1. File resolution logs show correct path mapping
2. Direct file lookup finds chunks from target files
3. Filtering successfully reduces results to target files only
4. Responses contain actual code content, not "There is no logic..."
5. Path normalization is consistent across all logs

## Next Steps

If all tests pass, the fixes are working correctly. If issues persist:
1. Check the logs for specific error messages
2. Run `test_path_matching.py` to verify path matching
3. Verify the SQLite index is up to date
4. Check that files are actually indexed in the database

