from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from analyzer.parser import parse_code
from analyzer.llm_extractor import extract_logic
from analyzer.veo_generator import generate_veo_video
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

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyze")
async def analyze_code(body: CodeRequest):
    ast_insight = parse_code(body.code)

    if "error" in ast_insight:
        return {"error": ast_insight["error"]}

    results = extract_logic(body.code, ast_insight)

    return {
        "functions": ast_insight["functions"],
        "loops": ast_insight["loops_count"],
        "time_complexity": results.time_complexity if results else None,
        "space_complexity": results.space_complexity if results else None,
        "narration_script": results.narration_script if results else [],
        "logic_timeline": [s.model_dump() for s in results.logic_timeline] if results else [],
        "timeline_steps": len(results.logic_timeline) if results else 0,
    }

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