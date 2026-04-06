import analyzer
from fastapi import FastAPI
from analyzer.parser import parse_code
from analyzer.llm_extractor import extract_logic