from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from analyzer.parser import parse_code
from analyzer.llm_extractor import extract_logic
from analyzer.veo_generator import generate_veo_video
from analyzer.step_tracer import generate_trace
from analyzer.language_analyzer import (
    detect_language,
    analyze_any_language,
    simulate_trace,
    SUPPORTED_LANGUAGES,
)
from dotenv import load_dotenv
import uvicorn

load_dotenv()

app = FastAPI(title="CodeKino API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CodeRequest(BaseModel):
    code: str
    language: Optional[str] = None   # if None → auto-detect
    file_name: Optional[str] = None  # used for extension-based detection


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/languages")
def list_languages():
    """Return all supported languages for the frontend selector."""
    return {
        "languages": [
            {"key": k, "label": v["label"], "ext": v["ext"]}
            for k, v in SUPPORTED_LANGUAGES.items()
        ]
    }


# ── Analyze ───────────────────────────────────────────────────────────────────

@app.post("/analyze")
async def analyze_code(body: CodeRequest):
    """
    Multi-language analysis endpoint.
    - Python → AST parser + LLM extractor (existing flow)
    - Other  → LLM-based analysis (language_analyzer)
    """
    language = body.language or detect_language(body.code, body.file_name)

    if language == "python":
        # ── Python path: full AST + LLM extractor ────────────────────────────
        ast_insight = parse_code(body.code)

        if "error" in ast_insight:
            return {"error": ast_insight["error"]}

        effective_code = ast_insight.pop("fixed_code", None) or body.code
        results = extract_logic(effective_code, ast_insight)

        response = {
            "language": "python",
            "functions": ast_insight["functions"],
            "loops": ast_insight["loops_count"],
            "time_complexity": results.time_complexity if results else None,
            "space_complexity": results.space_complexity if results else None,
            "narration_script": results.narration_script if results else [],
            "logic_timeline": [s.model_dump() for s in results.logic_timeline] if results else [],
            "timeline_steps": len(results.logic_timeline) if results else 0,
        }
        if effective_code != body.code:
            response["fixed_code"] = effective_code
        return response

    else:
        # ── Non-Python path: LLM-based analysis ──────────────────────────────
        results = analyze_any_language(body.code, language)

        if not results:
            return {"error": f"Failed to analyze {language} code. Check that the backend has a valid GEMINI_API_KEY."}

        return {
            "language": language,
            "functions": [fn.model_dump() for fn in results.functions],
            "loops": results.loops_count,
            "time_complexity": results.time_complexity,
            "space_complexity": results.space_complexity,
            "narration_script": results.narration_script,
            "logic_timeline": [s.model_dump() for s in results.logic_timeline],
            "timeline_steps": len(results.logic_timeline),
        }


# ── Trace ─────────────────────────────────────────────────────────────────────

@app.post("/trace")
async def trace_code(body: CodeRequest):
    """
    Multi-language trace endpoint.
    - Python  → Hybrid: sys.settrace (real values) + LLM for descriptions
    - Others  → LLM simulates execution with a concrete example input
    """
    language = body.language or detect_language(body.code, body.file_name)

    if language == "python":
        # ── Python: real execution tracer ─────────────────────────────────────
        ast_insight = parse_code(body.code)

        if "error" in ast_insight:
            return {"error": ast_insight["error"]}

        effective_code = ast_insight.pop("fixed_code", None) or body.code
        result = generate_trace(effective_code, ast_insight)

        if not result:
            return {"error": "Failed to generate execution trace"}

        if not result.steps:
            return {"error": result.error or "No execution steps recorded"}

        data = result.model_dump()
        if effective_code != body.code:
            data["fixed_code"] = effective_code
        return data

    else:
        # ── Non-Python: LLM simulated trace ───────────────────────────────────
        # First do a lightweight analysis to get function names, then simulate trace
        analysis = analyze_any_language(body.code, language)
        ast_metrics = {}
        if analysis:
            ast_metrics = {
                "functions": [fn.model_dump() for fn in analysis.functions],
                "loops_count": analysis.loops_count,
            }

        sim = simulate_trace(body.code, language, ast_metrics)
        if not sim or not sim.steps:
            return {"error": f"Could not simulate execution for {language} code."}

        # Convert SimulatedTrace → TraceResult-compatible shape
        source_lines = body.code.splitlines()
        steps = []
        for s in sim.steps:
            steps.append({
                "step_number": s.step_number,
                "line_number": max(1, min(s.line_number, len(source_lines))),
                "description": s.description,
                "memory": {"variables": s.variables},
                "is_loop_iteration": s.is_loop_iteration,
                "loop_label": s.loop_label,
                "highlight_type": s.highlight_type or "normal",
            })

        return {
            "title": sim.title,
            "language": language,
            "source_lines": source_lines,
            "tracked_variables": sim.tracked_variables,
            "steps": steps,
        }


# ── Video ─────────────────────────────────────────────────────────────────────

class VideoRequest(BaseModel):
    prompt: str

@app.post("/generate-video")
async def generate_video(body: VideoRequest):
    uri = generate_veo_video(body.prompt)
    if uri:
        return {"status": "success", "video_uri": uri}
    return {"status": "error", "message": "Failed to generate video"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
