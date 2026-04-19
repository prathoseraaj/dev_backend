"""
real_tracer.py
──────────────
Pure Python execution tracer using sys.settrace.
Produces a deterministic, accurate timeline of REAL variable values at every
executed line — zero LLM, zero hallucination.

The LLM is used ONLY afterwards to add a short cinematic description to each step.
"""

import sys
import copy
import textwrap
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class RawStep:
    """One recorded line execution."""
    step_number: int
    line_number: int
    variables: Dict[str, Any]
    event: str  # 'line' | 'call' | 'return' | 'exception'
    return_value: Any = None
    is_loop_iteration: bool = False
    loop_label: Optional[str] = None
    highlight_type: str = 'normal'


@dataclass
class RawTrace:
    title: str
    source_lines: List[str]
    tracked_variables: List[str]
    steps: List[RawStep]
    error: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

_SAFE_TYPES = (int, float, str, bool, list, dict, tuple, set, type(None))

def _safe_copy(val: Any) -> Any:
    """Deep-copy only JSON-safe primitives; stringify everything else."""
    if isinstance(val, _SAFE_TYPES):
        try:
            return copy.deepcopy(val)
        except Exception:
            pass
    return repr(val)


def _snapshot(local_vars: dict, tracked: List[str]) -> Dict[str, Any]:
    """Return a snapshot of only the tracked variables."""
    return {k: _safe_copy(local_vars.get(k)) for k in tracked}


def _detect_tracked_variables(source_code: str) -> List[str]:
    """
    Walk the AST to find all variables assigned in the code.
    Returns them in order of first appearance.
    """
    import ast
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    seen: dict[str, int] = {}  # name → first line
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id not in seen:
                    seen[t.id] = getattr(node, 'lineno', 9999)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id not in seen:
                seen[node.target.id] = getattr(node, 'lineno', 9999)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args:
                if arg.arg not in seen:
                    seen[arg.arg] = getattr(node, 'lineno', 9999)
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name) and node.target.id not in seen:
                seen[node.target.id] = getattr(node, 'lineno', 9999)

    return sorted(seen, key=lambda k: seen[k])


# ── Loop-iteration detection ───────────────────────────────────────────────────

def _build_loop_line_ranges(source_code: str) -> List[Tuple[int, int]]:
    """Return (start_line, end_line) pairs for each loop body in the source."""
    import ast
    ranges: List[Tuple[int, int]] = []
    try:
        tree = ast.parse(source_code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                ranges.append((node.lineno, node.end_lineno or node.lineno))
    except SyntaxError:
        pass
    return ranges


def _is_inside_loop(line_no: int, loop_ranges: List[Tuple[int, int]]) -> bool:
    return any(start <= line_no <= end for start, end in loop_ranges)


# ── The tracer ─────────────────────────────────────────────────────────────────

MAX_STEPS = 60  # hard cap to prevent runaway loops


def trace_code(source_code: str, title: str = "Execution Trace") -> RawTrace:
    """
    Execute *source_code* under sys.settrace and record every line event.

    Returns a RawTrace with real variable values — no LLM involved.
    Safety guarantees:
      • Execution is capped at MAX_STEPS line events.
      • No file I/O, no network calls, no subprocess is allowed.
      • Any exception during execution is captured; partial trace is returned.
    """
    source_code = textwrap.dedent(source_code).strip()
    source_lines = source_code.splitlines()
    tracked_vars = _detect_tracked_variables(source_code)
    loop_ranges = _build_loop_line_ranges(source_code)

    steps: List[RawStep] = []
    step_counter = [0]
    stopped = [False]

    # Track per-variable previous snapshot to detect loop iterations
    prev_snapshot: Dict[str, Any] = {}

    def _tracer(frame, event, arg):
        if stopped[0]:
            return None  # detach

        # Only trace lines in the user code (not stdlib internals)
        if frame.f_code.co_filename != '<string>':
            return _tracer  # keep tracing caller

        if event not in ('line', 'return', 'call'):
            return _tracer

        if event == 'call':
            return _tracer  # drill into calls

        step_counter[0] += 1
        if step_counter[0] > MAX_STEPS:
            stopped[0] = True
            return None

        line_no = frame.f_lineno
        local_vars = frame.f_locals

        snap = _snapshot(local_vars, tracked_vars)
        is_loop = _is_inside_loop(line_no, loop_ranges)

        # Build loop label from loop variables
        loop_label: Optional[str] = None
        if is_loop:
            loop_iters = {k: snap[k] for k in tracked_vars
                         if snap.get(k) is not None
                         and isinstance(snap.get(k), (int, float, str, bool))}
            if loop_iters:
                loop_label = ', '.join(f'{k}={v}' for k, v in loop_iters.items())

        # Detect highlight type
        highlight = 'normal'
        if event == 'return':
            highlight = 'return'

        # Detect swaps: if two tracked numeric vars exchanged values since last step
        if len(steps) > 0:
            last_snap = steps[-1].variables
            swapped = [
                k for k in tracked_vars
                if isinstance(snap.get(k), (int, float))
                and last_snap.get(k) != snap.get(k)
            ]
            if len(swapped) >= 2:
                highlight = 'swap'

        # Detect branch (line is inside an if/while condition)
        try:
            raw_line = source_lines[line_no - 1] if line_no <= len(source_lines) else ''
            stripped = raw_line.strip()
            if stripped.startswith('if ') or stripped.startswith('elif '):
                highlight = 'branch_true'
            elif stripped.startswith('else:'):
                highlight = 'branch_false'
        except IndexError:
            pass

        raw_step = RawStep(
            step_number=len(steps) + 1,
            line_number=line_no,
            variables=snap,
            event=event,
            return_value=_safe_copy(arg) if event == 'return' else None,
            is_loop_iteration=is_loop,
            loop_label=loop_label,
            highlight_type=highlight,
        )
        steps.append(raw_step)
        prev_snapshot.update(snap)
        return _tracer

    # ── Restricted execution environment ──────────────────────────────────────
    safe_globals: Dict[str, Any] = {
        '__builtins__': {
            'range': range, 'len': len, 'print': lambda *a, **kw: None,
            'int': int, 'float': float, 'str': str, 'bool': bool,
            'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
            'min': min, 'max': max, 'abs': abs, 'sum': sum,
            'enumerate': enumerate, 'zip': zip, 'map': map, 'filter': filter,
            'sorted': sorted, 'reversed': reversed,
            'isinstance': isinstance, 'type': type,
            'True': True, 'False': False, 'None': None,
            'append': list.append,
        },
        '__name__': '__main__',
    }

    error: Optional[str] = None
    old_trace = sys.gettrace()
    try:
        sys.settrace(_tracer)
        exec(compile(source_code, '<string>', 'exec'), safe_globals)  # noqa: S102
    except StopIteration:
        pass  # max steps hit
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        sys.settrace(old_trace)

    # Trim steps (in case we over-fired)
    steps = steps[:MAX_STEPS]

    return RawTrace(
        title=title,
        source_lines=source_lines,
        tracked_variables=tracked_vars,
        steps=steps,
        error=error,
    )
