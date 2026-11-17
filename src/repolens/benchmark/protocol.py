"""Versioned evaluation inputs and a fixed, hash-bound run matrix."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator

CONFIGS = {
    'direct': ('direct', 'keyword', False, False),
    'single_keyword': ('single', 'keyword', False, False),
    'single_keyword_compressed': ('single', 'keyword', False, True),
    'collaborative_keyword': ('collaborative', 'keyword', False, False),
    'collaborative_keyword_compressed': ('collaborative', 'keyword', False, True),
    'collaborative_hybrid': ('collaborative', 'hybrid', False, False),
    'collaborative_hybrid_compressed': ('collaborative', 'hybrid', False, True),
    'collaborative_hybrid_rerank': ('collaborative', 'hybrid', True, False),
    'collaborative_hybrid_rerank_compressed': ('collaborative', 'hybrid', True, True),
}
CONFIGURATION=Literal['direct','single_keyword','single_keyword_compressed','collaborative_keyword','collaborative_keyword_compressed','collaborative_hybrid','collaborative_hybrid_compressed','collaborative_hybrid_rerank','collaborative_hybrid_rerank_compressed']


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def utcnow():return datetime.now(timezone.utc).isoformat()


class Strict(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)


class Source(Strict):
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    git_blob:str=Field(pattern=r'^[a-f0-9]{40}$')
    lines:int=Field(gt=0)


class Repository(Strict):
    id:str=Field(pattern=r'^[a-z0-9_-]{1,40}$')
    url:str=Field(pattern=r'^https://github\.com/[a-z0-9][a-z0-9-]{0,38}/[a-z0-9][a-z0-9_.-]{0,99}$')
    commit:str=Field(pattern=r'^[a-f0-9]{40}$')
    partition:Literal['development','reserved']
    sources:dict[str,Source]


class Anchor(Strict):
    path:str
    symbol:str
    start_line:int=Field(ge=1)
    end_line:int=Field(ge=1)
    @model_validator(mode='after')
    def bounds(self):
        if self.end_line<self.start_line:raise ValueError('invalid_anchor_range')
        return self


class Fact(Strict):
    id:str=Field(pattern=r'^[a-z0-9_-]{1,40}$')
    text:str=Field(min_length=1,max_length=2000)
    evidence:list[Anchor]=Field(min_length=1,max_length=10)


class Case(Strict):
    id:str=Field(pattern=r'^[a-z0-9_-]{1,60}$')
    repository:str
    category:Literal['architecture','implementation','docs_code','insufficient_evidence']
    question:str=Field(min_length=1,max_length=10000)
    facts:list[Fact]=Field(min_length=1,max_length=20)
    review_rule:str=Field(min_length=1,max_length=2000)
    @field_validator('question')
    @classmethod
    def canonical_question(cls,value):
        value=value.strip()
        if not value:raise ValueError('nonempty_question_required')
        return value


class Suite(Strict):
    schema_version:Literal[1]=1
    id:str=Field(pattern=r'^[a-z0-9_-]{1,60}$')
    annotation_status:Literal['draft_needs_independent_review','human_approved']
    annotation_reviewer:str|None=None
    repositories:list[Repository]=Field(min_length=1,max_length=10)
    cases:list[Case]=Field(min_length=1,max_length=300)
    @model_validator(mode='after')
    def references(self):
        repos={r.id:r for r in self.repositories}
        if len(repos)!=len(self.repositories) or len({c.id for c in self.cases})!=len(self.cases):raise ValueError('duplicate_suite_identifier')
        if self.annotation_status=='human_approved' and not (self.annotation_reviewer or '').strip():raise ValueError('annotation_reviewer_required')
        for repo in self.repositories:
            for path in repo.sources:
                if not path or '\\' in path or ':' in path or '..' in PurePosixPath(path).parts or PurePosixPath(path).is_absolute():raise ValueError('invalid_source_path')
        for case in self.cases:
            if case.repository not in repos:raise ValueError('unknown_case_repository')
            if len({fact.id for fact in case.facts})!=len(case.facts):raise ValueError('duplicate_fact_identifier')
            for fact in case.facts:
                for anchor in fact.evidence:
                    source=repos[case.repository].sources.get(anchor.path)
                    if source is None or anchor.end_line>source.lines:raise ValueError('unknown_anchor_source_or_range')
        return self


def api_origin(value):
    try:
        url=urlsplit(value)
        if url.scheme not in {'http','https'} or url.hostname not in {'localhost','127.0.0.1','::1'} or url.username is not None or url.password is not None or url.path not in {'','/'} or url.query or url.fragment or url.port==0:raise ValueError()
    except ValueError:raise ValueError('loopback_api_origin_required') from None
    return value.rstrip('/')


class Plan(Strict):
    schema_version:Literal[1]=1
    run_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    created_at:str
    suite:Suite
    suite_hash:str
    api_url:str
    case_ids:list[str]=Field(min_length=1)
    configurations:list[CONFIGURATION]=Field(min_length=1)
    repeats:int=Field(ge=1,le=3)
    timeout_seconds:float=Field(default=960.0,gt=0,le=1800)
    protocol_id:str|None=None
    @model_validator(mode='after')
    def frozen(self):
        api_origin(self.api_url)
        if self.suite_hash!=digest(self.suite.model_dump(mode='json')):raise ValueError('suite_hash_mismatch')
        if len(set(self.case_ids))!=len(self.case_ids) or not set(self.case_ids)<={c.id for c in self.suite.cases}:raise ValueError('invalid_plan_cases')
        if len(set(self.configurations))!=len(self.configurations):raise ValueError('duplicate_configuration')
        selected={c.repository for c in self.suite.cases if c.id in self.case_ids}
        if any(repo.partition=='reserved' and repo.id in selected for repo in self.suite.repositories) and not (self.protocol_id or '').strip():raise ValueError('reserved_partition_requires_frozen_protocol_id')
        return self


def create_plan(suite,api_url,configurations,repeats=3,partition='development',protocol_id=None,timeout_seconds=960.0,case_ids=None):
    selected={repo.id for repo in suite.repositories if partition=='all' or repo.partition==partition}
    available=[case.id for case in suite.cases if case.repository in selected]
    if case_ids and not set(case_ids)<=set(available):raise ValueError('case_not_in_selected_partition')
    return Plan(run_id=uuid4().hex,created_at=utcnow(),suite=suite,suite_hash=digest(suite.model_dump(mode='json')),api_url=api_origin(api_url),case_ids=[key for key in available if not case_ids or key in case_ids],configurations=configurations,repeats=repeats,protocol_id=protocol_id,timeout_seconds=timeout_seconds)


def matrix(plan):
    return [{'key':digest([case,configuration,repeat])[:24],'case_id':case,'configuration':configuration,'repeat':repeat} for case in plan.case_ids for configuration in plan.configurations for repeat in range(1,plan.repeats+1)]
