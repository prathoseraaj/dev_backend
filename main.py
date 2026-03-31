import os
import json
from dotenv import load_dotenv
from analyzer.parser import parse_code
from analyzer.llm_extractor import extract_logic

load_dotenv()

def generate_dev_doc(code: str):
    print("--- 1. Parsing Code (AST) ---")
    ast_insight = parse_code(code)
    
    if "error" in ast_insight:
        print("Parse failed:", ast_insight["error"])
        return
        
    print(f"Entities found: {ast_insight['functions']} functions, {ast_insight['loops_count']} loops.")
    
    print("\n--- 2. Connecting to Gemini API ---")
    results = extract_logic(code, ast_insight)
    
    if results:
        print("\n✅ Deep Explanation Finished. Output Dump:")
        print("========================")
        print("Time Complexity:", results.time_complexity)
        print("Space Complexity:", results.space_complexity)
        print("\nNarration Audio Script:")
        for sentence in results.narration_script:
            print(f"- {sentence}")
        print(f"\nTimeline Length: {len(results.logic_timeline)} steps")
    else:
        print("\n❌ LLM Failed to return Insights.")

if __name__ == "__main__":
    # We load in a test snippet
    with open("sample_code.py", "r") as f:
        src = f.read()

    generate_dev_doc(src)
