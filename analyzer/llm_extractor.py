import os
import json
from pydantic import BaseModel, Field
from typing import List
from google import genai
from google.genai import types

class VariableChange(BaseModel):
    variable_name: str
    new_value: str

class StepLog(BaseModel):
    step_number: int
    description: str = Field(description="A brief description of what happens at this step.")
    code_snippet: str = Field(description="The exact snippet or line of code executed.")
    variable_changes: List[VariableChange] = Field(description="Variables that change at this step.")

class CodeInsights(BaseModel):
    time_complexity: str
    space_complexity: str
    narration_script: List[str] = Field(description="A plain English narration that explains the function step by step. Designed to be spoken by TTS.")
    logic_timeline: List[StepLog]

def extract_logic(source_code: str, ast_metrics: dict) -> CodeInsights | None:

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Missing GEMINI_API_KEY in environment variables.")
        return None
        
    client = genai.Client(api_key=api_key)

    prompt = f"""
    You are an expert technical documenter and video instructor. We are building an animation explaining this python code.
    Below is the raw code and the structural AST analysis.
    
    AST Analysis:
    {json.dumps(ast_metrics, indent=2)}

    Raw Source Code:
    ```python
    {source_code}
    ```

    Breakdown exactly how this code works step-by-step. Include the time/space complexities, list the variables mutating at each step, and write an engaging 3-5 sentence narration script that a TTS engine could read out loud.
    """

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CodeInsights,
            ),
        )
        validated_data = CodeInsights.model_validate_json(response.text)
        return validated_data
    except Exception as e:
        print(f"Error during extraction: {e}")
        return None
