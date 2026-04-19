"""
step_tracer.py  (Hybrid: Real Tracer + LLM Narration Only)
────────────────────────────────────────────────────────────
Architecture:
  Code → sys.settrace → RawTrace (100% accurate runtime values)
                      ↓
               LLM → short cinematic descriptions only

Benefits:
  ✅ Zero hallucination — variables are REAL Python values
  ✅ LLM calls are tiny (descriptions, not execution)
  ✅ Works on free Gemini tier easily
  ✅ Fast — sys.settrace is instant
"""

import os
import json
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from analyzer.real_tracer import trace_code, RawTrace, RawStep


# ── Output models (unchanged shape — frontend stays the same) ──────────────────

class MemoryState(BaseModel):
    variables: Dict[str, Any] = Field(default_factory=dict)


class TraceStep(BaseModel):
    step_number: int
    line_number: int
    description: str
    memory: MemoryState
    is_loop_iteration: bool = False
    loop_label: Optional[str] = None
    highlight_type: str = 'normal'


class TraceResult(BaseModel):
    title: str
    language: str = 'python'
    source_lines: List[str]
    tracked_variables: List[str]
    steps: List[TraceStep]
    error: Optional[str] = None


# ── LLM narration (descriptions only, not execution) ──────────────────────────

def _llm_describe_steps(
    source_lines: List[str],
    raw_steps: List[RawStep],
) -> List[str]:
    """
    Ask Gemini to write ONE short cinematic description for each step.
    This is the ONLY LLM call in the entire trace pipeline.
    Input is tiny → fits free tier comfortably.
    Returns a list of description strings (same length as raw_steps).
    Falls back to auto-generated descriptions if LLM fails.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return [_auto_describe(s, source_lines) for s in raw_steps]

    # Build a compact summary for the LLM (no variable values, just events)
    step_summaries = []
    for s in raw_steps:
        line_text = (
            source_lines[s.line_number - 1].strip()
            if s.line_number <= len(source_lines)
            else ""
        )
        step_summaries.append({
            "step": s.step_number,
            "line": s.line_number,
            "code": line_text,
            "highlight": s.highlight_type,
            "is_loop": s.is_loop_iteration,
        })

    prompt = (
        "You are a cinematic computer science educator.\n"
        "Below is a list of code execution steps (line number + executed code + event type).\n"
        "Write ONE short description per step — max 10 words each, vivid, like movie subtitles.\n"
        "Return a JSON array of strings, one per step, in order.\n\n"
        f"Steps:\n{json.dumps(step_summaries, indent=2)}\n\n"
        "Return ONLY a JSON array like: [\"description 1\", \"description 2\", ...]"
    )

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        text = response.text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        descriptions = json.loads(text)
        if isinstance(descriptions, list) and len(descriptions) == len(raw_steps):
            return [str(d) for d in descriptions]
    except Exception as e:
        print(f"[step_tracer] LLM description failed: {e}")

    # Fallback: auto-generate descriptions from code
    return [_auto_describe(s, source_lines) for s in raw_steps]


def _auto_describe(step: RawStep, source_lines: List[str]) -> str:
    """Generate a readable description without LLM."""
    line_text = (
        source_lines[step.line_number - 1].strip()
        if step.line_number <= len(source_lines)
        else ""
    )
    prefix = {
        'return':       '↩ Return:',
        'swap':         '⇄ Swap:',
        'branch_true':  '✓ Branch true:',
        'branch_false': '✗ Branch false:',
        'call':         '→ Call:',
    }.get(step.highlight_type, f'Line {step.line_number}:')
    return f"{prefix} {line_text[:60]}"


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_trace(source_code: str, ast_metrics: dict) -> TraceResult | None:
    """
    Hybrid trace pipeline:
      1. Run real Python tracer → RawTrace (accurate)
      2. Ask LLM for descriptions only (tiny, cheap)
      3. Assemble final TraceResult
    """
    # ── Step 1: Real execution trace ──────────────────────────────────────────
    title = _build_title(source_code, ast_metrics)
    raw: RawTrace = trace_code(source_code, title=title)

    if not raw.steps:
        error_msg = raw.error or "No steps were recorded. Is the code runnable?"
        return TraceResult(
            title=title,
            source_lines=raw.source_lines,
            tracked_variables=raw.tracked_variables,
            steps=[],
            error=error_msg,
        )

    # ── Step 2: LLM descriptions (cheap, one call) ────────────────────────────
    descriptions = _llm_describe_steps(raw.source_lines, raw.steps)

    # ── Step 3: Assemble final result ─────────────────────────────────────────
    steps: List[TraceStep] = []
    for i, raw_step in enumerate(raw.steps):
        steps.append(TraceStep(
            step_number=raw_step.step_number,
            line_number=raw_step.line_number,
            description=descriptions[i],
            memory=MemoryState(variables=raw_step.variables),
            is_loop_iteration=raw_step.is_loop_iteration,
            loop_label=raw_step.loop_label,
            highlight_type=raw_step.highlight_type,
        ))

    return TraceResult(
        title=title,
        language='python',
        source_lines=raw.source_lines,
        tracked_variables=raw.tracked_variables,
        steps=steps,
        error=raw.error,  # include any runtime error as a warning
    )


def _build_title(source_code: str, ast_metrics: dict) -> str:
    """Build a short descriptive title from AST info."""
    functions = ast_metrics.get("functions", [])
    if functions:
        fn = functions[0]
        name = fn.get("name", "function")
        args = fn.get("args", [])
        return f"{name}({', '.join(args)}) — Live Trace"
    # Fallback: use first non-empty line
    for line in source_code.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:50]
    return "Execution Trace"
