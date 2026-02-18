"""FastAPI dependency injection: singleton service instances."""

import logging
from functools import lru_cache
from typing import Optional

from fastapi import Request

from app.config import Settings
from app.services.coherence_check import CoherenceCheck
from app.services.constraint_validator import ConstraintValidator
from app.services.content_generator import ContentGenerator
from app.services.deck_planner import DeckPlanner
from app.services.input_parser import InputParser
from app.services.pptx_pipeline import PPTXPipeline
from app.services.template_registry import TemplateRegistry
from app.storage.local import LocalStorage
from app.store.sqlite import SQLiteJobStore

logger = logging.getLogger(__name__)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_storage(request: Request) -> LocalStorage:
    return request.app.state.storage


def get_job_store(request: Request) -> SQLiteJobStore:
    return request.app.state.job_store


def get_template_registry(request: Request) -> TemplateRegistry:
    return request.app.state.template_registry


def get_input_parser(request: Request) -> InputParser:
    return request.app.state.input_parser


def get_constraint_validator() -> ConstraintValidator:
    return ConstraintValidator()


def get_pipeline(request: Request) -> PPTXPipeline:
    return request.app.state.pipeline


def get_deck_planner(request: Request) -> Optional[DeckPlanner]:
    return getattr(request.app.state, "deck_planner", None)


def get_content_generator(request: Request) -> Optional[ContentGenerator]:
    return getattr(request.app.state, "content_generator", None)


def get_coherence_check(request: Request) -> Optional[CoherenceCheck]:
    return getattr(request.app.state, "coherence_check", None)
