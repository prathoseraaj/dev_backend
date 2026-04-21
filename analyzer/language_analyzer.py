import os
import json
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from google import genai
from google.genai import types



SUPPORTED_LANGUAGES: Dict[str, Dict[str, str]] = {
    "python":     {"label": "Python",     "ext": ".py",   "comment": "#"},
    "javascript": {"label": "JavaScript", "ext": ".js",   "comment": "//"},
    "typescript": {"label": "TypeScript", "ext": ".ts",   "comment": "//"},
    "java":       {"label": "Java",       "ext": ".java", "comment": "//"},
    "c":          {"label": "C",          "ext": ".c",    "comment": "//"},
    "cpp":        {"label": "C++",        "ext": ".cpp",  "comment": "//"},
    "go":         {"label": "Go",         "ext": ".go",   "comment": "//"},
    "rust":       {"label": "Rust",       "ext": ".rs",   "comment": "//"},
    "kotlin":     {"label": "Kotlin",     "ext": ".kt",   "comment": "//"},
    "swift":      {"label": "Swift",      "ext": ".swift","comment": "//"},
    "ruby":       {"label": "Ruby",       "ext": ".rb",   "comment": "#"},
}

EXTENSION_MAP: Dict[str, str] = {
    meta["ext"]: lang for lang, meta in SUPPORTED_LANGUAGES.items()
}

def detect_language(source_code: str, file_name: Optional[str] = None) -> str:
    """
    Detect programming language. Priority:
      1. File extension (if file_name provided)
      2. Heuristic keyword matching
    Returns a language key like 'python', 'javascript', etc.
    """
    if file_name:
        for ext, lang in EXTENSION_MAP.items():
            if file_name.lower().endswith(ext):
                return lang

    code = source_code.strip()

    if "public class " in code or "System.out.println" in code or "public static void main" in code:
        return "java"

    if "#include <iostream>" in code or "std::" in code or "cout <<" in code:
        return "cpp"

    if "#include <stdio.h>" in code or "printf(" in code or "int main(" in code and "#include" in code:
        return "c"

    if "package main" in code or "func main()" in code or 'fmt.Println' in code:
        return "go"

    if "fn main()" in code or "println!(" in code or "let mut " in code:
        return "rust"

    if ": string" in code or ": number" in code or "interface " in code or ": boolean" in code:
        return "typescript"

    if "const " in code or "let " in code or "function " in code or "=>" in code:
        return "javascript"

    if "def " in code and "end" in code and "puts " in code:
        return "ruby"

    if "def " in code or "import " in code or "print(" in code or "class " in code:
        return "python"

    return "python"  # default fallback


class FunctionInfo(BaseModel):
    name: str
    args: List[str] = Field(default_factory=list)
    line_start: int = 1
    line_end: int = 1


class VariableChange(BaseModel):
    variable_name: str
    new_value: str


class StepLog(BaseModel):
    step_number: int
    description: str
    code_snippet: str
    variable_changes: List[VariableChange] = Field(default_factory=list)


class CodeInsights(BaseModel):
    functions: List[FunctionInfo] = Field(default_factory=list)
    loops_count: int = 0
    time_complexity: str
    space_complexity: str
    narration_script: List[str] = Field(
        description="3-5 sentence narration explaining the code, suitable for TTS."
    )
    logic_timeline: List[StepLog] = Field(default_factory=list)


class SimulatedTraceStep(BaseModel):
    step_number: int
    line_number: int
    description: str
    variables: Dict[str, Any] = Field(default_factory=dict)
    is_loop_iteration: bool = False
    loop_label: Optional[str] = None
    highlight_type: str = "normal"


class SimulatedTrace(BaseModel):
    title: str
    tracked_variables: List[str] = Field(default_factory=list)
    steps: List[SimulatedTraceStep] = Field(default_factory=list)


def _strip_additional_props(obj: Any) -> None:
    """Recursively remove 'additionalProperties' from Pydantic JSON schema for Gemini."""
    if isinstance(obj, dict):
        obj.pop("additionalProperties", None)
        for v in obj.values():
            _strip_additional_props(v)
    elif isinstance(obj, list):
        for item in obj:
            _strip_additional_props(item)


def _get_schema(model_class):
    schema = model_class.model_json_schema()
    _strip_additional_props(schema)
    return schema


def analyze_any_language(source_code: str, language: str) -> Optional[CodeInsights]:
    """
    Use LLM to extract structural insights from any language:
    functions, loops, complexity, narration, logic timeline.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[language_analyzer] No GEMINI_API_KEY")
        return None

    lang_label = SUPPORTED_LANGUAGES.get(language, {}).get("label", language.title())

    prompt = f"""You are an expert code analyzer for a cinematic code visualizer.

Analyze this {lang_label} code and return structured JSON with:
- All functions/methods with their names, argument names, and line numbers
- Count of loops (for, while, forEach, etc.)
- Time and space complexity (Big-O notation)
- A 3-5 sentence narration script (plain English, TTS-friendly)
- A logic timeline of 8-15 key execution steps

Source Code ({lang_label}):
```
{source_code}
```

Rules:
- line_start / line_end must be valid 1-based line numbers
- logic_timeline: each step has a step_number, description (brief), code_snippet (actual line), variable_changes
- narration_script: written as if explaining to a student, engaging and clear
"""

    try:
        client = genai.Client(api_key=api_key)
        schema = _get_schema(CodeInsights)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        return CodeInsights.model_validate_json(response.text)
    except Exception as e:
        print(f"[language_analyzer] Analysis error: {e}")
        return None



def simulate_trace(source_code: str, language: str, ast_metrics: dict) -> Optional[SimulatedTrace]:
    """
    LLM-simulates execution trace for non-Python languages.
    Since we can't run JS/Java/C++ natively, the LLM simulates it with concrete example input.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[language_analyzer] No GEMINI_API_KEY for trace simulation")
        return None

    lang_label = SUPPORTED_LANGUAGES.get(language, {}).get("label", language.title())
    functions = ast_metrics.get("functions", [])
    fn_name = functions[0].get("name", "main") if functions else "main"

    prompt = f"""You are a cinematic code execution visualizer.

Simulate the step-by-step execution of this {lang_label} code for a concrete small input.
Choose an interesting example (e.g. a small array, a number like 5 or 10).

Source Code ({lang_label}):
```
{source_code}
```

Rules:
1. Pick concrete input and trace actual execution (no abstract descriptions).
2. Produce 10-20 steps covering: function call, each loop iteration, key assignments, comparisons, return.
3. Each step MUST have:
   - step_number (1-based)
   - line_number (1-based, must match a real line in the code)
   - description (max 10 words, cinematic/vivid)
   - variables: flat dict of variable_name → current value (use null for uninitialized)
   - is_loop_iteration: true if inside a loop body
   - loop_label: "i=0, j=2" style string when inside a nested loop, else null
   - highlight_type: one of normal | branch_true | branch_false | swap | return | call
4. tracked_variables: list all variable names that appear in the trace
5. title: "{fn_name} — [example input]" e.g. "bubbleSort — [5,3,1,4,2]"
"""

    try:
        client = genai.Client(api_key=api_key)
        schema = _get_schema(SimulatedTrace)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        return SimulatedTrace.model_validate_json(response.text)
    except Exception as e:
        print(f"[language_analyzer] Trace simulation error: {e}")
        return None
