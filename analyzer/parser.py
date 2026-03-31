import ast
from typing import Dict, Any, List

class CodeAnalyzer(ast.NodeVisitor):

    def __init__(self):
        self.functions: List[Dict[str, Any]] = []
        self.classes: List[Dict[str, Any]] = []
        self.global_variables: List[str] = []
        self.loops: int = 0
        self.imports: List[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Extracts function details."""
        args = [arg.arg for arg in node.args.args]
        self.functions.append({
            "name": node.name,
            "args": args,
            "line_start": node.lineno,
            "line_end": node.end_lineno
        })
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """Extracts class details."""
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
        """Extract global assignments"""
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


def parse_code(source_code: str) -> Dict[str, Any]:

    try:
        tree = ast.parse(source_code)
        analyzer = CodeAnalyzer()
        analyzer.visit(tree)
        
        return {
            "functions": analyzer.functions,
            "classes": analyzer.classes,
            "loops_count": analyzer.loops,
            "dependencies": list(set(analyzer.imports)),
            "variables": list(set(analyzer.global_variables))
        }
    except SyntaxError as e:
        return {"error": f"Invalid syntax in provided code: {str(e)}"}
