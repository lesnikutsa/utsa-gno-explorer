"""Bounded one-shot indexing orchestration."""
from __future__ import annotations
from dataclasses import dataclass

from scripts.inspect_rpc import RpcError
from .config import DEFAULT_MAX_HEIGHTS
from .parsers import parse_height
from .rpc import fetch_height

@dataclass(frozen=True)
class RangePlan:
    start_height:int; end_height:int; count:int; finalized_tip:int; dry_run:bool
@dataclass(frozen=True)
class RunSummary:
    plan:RangePlan; processed:list[int]; dry_run:bool

def plan_range(checkpoint:int|None,start_height:int|None,end_height:int|None,max_heights:int|None,finalized_tip:int,hard_max:int,dry_run:bool)->RangePlan:
    if checkpoint is None and start_height is None:
        raise ValueError("--start-height is required for an empty database")
    start = start_height if start_height is not None else checkpoint + 1
    if checkpoint is not None and start_height is None and start != checkpoint + 1:
        raise ValueError("resume must be sequential")
    if start < 1: raise ValueError("start height must be positive")
    limit = max_heights if max_heights is not None else DEFAULT_MAX_HEIGHTS
    if limit < 1: raise ValueError("max heights must be positive")
    end = end_height if end_height is not None else start + limit - 1
    if end < start: raise ValueError("end height must be >= start height")
    count = end - start + 1
    if count > hard_max: raise ValueError(f"requested range has {count} heights, above hard limit {hard_max}")
    if end > finalized_tip: raise ValueError(f"requested end height {end} is above finalized_tip {finalized_tip}")
    return RangePlan(start,end,count,finalized_tip,dry_run)

class IndexerService:
    def __init__(self, rpc_client, db, chain_id:str, rpc_url:str, finalized_tip:int):
        self.rpc_client=rpc_client; self.db=db; self.chain_id=chain_id; self.rpc_url=rpc_url; self.finalized_tip=finalized_tip
    def run(self, plan:RangePlan, fail_after_parse_height:int|None=None)->RunSummary:
        processed=[]
        expected=plan.start_height
        for h in range(plan.start_height, plan.end_height+1):
            if h != expected: raise RpcError("non-sequential height plan")
            block,commit,validators=fetch_height(self.rpc_client,h)
            parsed=parse_height(h,block,commit,validators)
            if fail_after_parse_height == h: raise RuntimeError("injected failure after parse")
            if not plan.dry_run: self.db.write_height(parsed,self.chain_id,self.rpc_url,self.finalized_tip)
            processed.append(h); expected+=1
        return RunSummary(plan,processed,plan.dry_run)
