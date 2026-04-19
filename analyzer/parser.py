import ast
import os
from typing import Dict, Any, List, Optional


# ── AST Visitor ───────────────────────────────────────────────────────────────

class CodeAnalyzer(ast.NodeVisitor):

    def __init__(self):
        self.functions: List[Dict[str, Any]] = []
        self.classes: List[Dict[str, Any]] = []
        self.global_variables: List[str] = []
        self.loops: int = 0
        self.imports: List[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        args = [arg.arg for arg in node.args.args]
        self.functions.append({
            "name": node.name,
            "args": args,
            "line_start": node.lineno,
            "line_end": node.end_lineno
        })
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        self.classes.append({
            "name": node.name,
            "line_start": node.lineno,
            "line_end": node.end_lineno
        })
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        self.loops += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While):
        self.loops += 1
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        if isinstance(node.targets[0], ast.Name):
            self.global_variables.append(node.targets[0].id)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)


# ── Pass-2: Auto-repair empty block bodies ────────────────────────────────────

_BLOCK_KEYWORDS = (
    'def ', 'class ', 'for ', 'while ', 'if ', 'elif ',
    'else:', 'try:', 'except', 'finally:', 'with ',
    'async def ', 'async for ', 'async with ',
)


def _is_block_opener(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped or stripped.startswith('#'):
        return False
    code_part = stripped.split('#')[0].rstrip()
    if not code_part.endswith(':'):
        return False
    return any(stripped.startswith(kw) for kw in _BLOCK_KEYWORDS)


def _auto_repair(source_code: str) -> str:
    """Insert `pass` after block openers that have no body."""
    lines = source_code.splitlines()
    repaired = []
    for i, line in enumerate(lines):
        repaired.append(line)
        if _is_block_opener(line):
            indent = len(line) - len(line.lstrip())
            next_content = [l for l in lines[i + 1:] if l.strip()]
            if not next_content:
                repaired.append(' ' * (indent + 4) + 'pass')
            else:
                next_indent = len(next_content[0]) - len(next_content[0].lstrip())
                if next_indent <= indent:
                    repaired.append(' ' * (indent + 4) + 'pass')
    return '\n'.join(repaired)


# ── Pass-3: LLM-powered indentation reformat ──────────────────────────────────

def _llm_reformat(source_code: str) -> Optional[str]:
    """
    Ask Gemini to restore correct Python indentation — whitespace ONLY.
    Returns the reformatted source string, or None on failure.
    """
    try:
        from google import genai  # imported lazily — lives in venv

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("[parser] No GEMINI_API_KEY — skipping LLM reformat.")
            return None

        client = genai.Client(api_key=api_key)

        prompt = (
            "You are a Python code formatter. "
            "The code below was pasted by a user and has lost its indentation. "
            "Restore the correct Python indentation so the code is syntactically valid. "
            "Do NOT add, remove, or rename any functions, variables, or logic. "
            "Do NOT add markdown code fences, explanations, or comments. "
            "Return ONLY the raw Python source code with correct indentation.\n\n"
            f"{source_code}"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        fixed = response.text.strip()

        # Strip markdown fences if the model added them anyway
        if fixed.startswith("```"):
            lines_out = fixed.splitlines()
            if lines_out[-1].strip() == "```":
                lines_out = lines_out[1:-1]
            else:
                lines_out = lines_out[1:]
            fixed = "\n".join(lines_out).strip()

        return fixed if fixed else None

    except Exception as e:
        print(f"[parser] LLM reformat failed: {e}")
        return None


# ── Public entry point ────────────────────────────────────────────────────────

def parse_code(source_code: str) -> Dict[str, Any]:
    """
    Parse Python source → AST metrics dict.

    Three-pass strategy:
      Pass 1  — parse as-is
      Pass 2  — auto-repair empty block bodies, retry
      Pass 3  — LLM-based indentation reformat, retry

    When Pass 2 or 3 succeeds, the result dict includes "fixed_code" so the
    caller can echo the corrected source back to the user.
    """
    source_code = source_code.replace('\r\n', '\n').strip()

    def _run_ast(code: str) -> Dict[str, Any]:
        tree = ast.parse(code)
        analyzer = CodeAnalyzer()
        analyzer.visit(tree)
        return {
            "functions": analyzer.functions,
            "classes": analyzer.classes,
            "loops_count": analyzer.loops,
            "dependencies": list(set(analyzer.imports)),
            "variables": list(set(analyzer.global_variables)),
        }

    # ── Pass 1: raw parse
    try:
        return _run_ast(source_code)
    except SyntaxError:
        pass

    # ── Pass 2: auto-repair (empty block bodies)
    repaired = _auto_repair(source_code)
    try:
        result = _run_ast(repaired)
        result["fixed_code"] = repaired
        return result
    except SyntaxError:
        pass

    # ── Pass 3: LLM indentation reformat
    print("[parser] Syntax still broken after auto-repair — attempting LLM reformat…")
    llm_fixed = _llm_reformat(source_code)
    if llm_fixed:
        try:
            result = _run_ast(llm_fixed)
            result["fixed_code"] = llm_fixed
            print("[parser] LLM reformat succeeded.")
            return result
        except SyntaxError as e:
            return {"error": f"Syntax error even after auto-fix attempt: {str(e)}"}

    # All passes failed — surface the original error
    try:
        ast.parse(source_code)
    except SyntaxError as e:
        return {"error": f"Syntax error in your code: {str(e)}"}

    return {"error": "Unknown parse failure."}
