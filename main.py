from os import truncate
import analyzer
from fastapi import FastAPI
from analyzer.parser import parse_code
from analyzer.llm_extractor import extract_logic
import uvicorn

app = FastAPI()

@app.post("/analyze")
async def analyze_code(code:str):
    ast_insight = parse_code(code)

    if "error" in ast_insight:
        return {"error": ast_insight["error"]}

    results = extract_logic(code, ast_insight)

    return {
        "functions": ast_insight["functions"],
        "loops": ast_insight["loops_count"],
        "time_complexity": results.time_complexity if results else None,
        "space_complexity": results.space_complexity if results else None,
        "timeline_steps": len(results.logic_timeline) if results else 0
    }

if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)