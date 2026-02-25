from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SimOrderCreateRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    side: Side
    qty: float = Field(..., gt=0)


class SimPolyBetCreateRequest(BaseModel):
    market_id: str = Field(..., min_length=1, max_length=128)
    outcome: str = Field(..., min_length=1, max_length=64)
    amount: float = Field(..., gt=0)


class SimPolySellCreateRequest(BaseModel):
    market_id: str = Field(..., min_length=1, max_length=128)
    outcome: str = Field(..., min_length=1, max_length=64)
    shares: float = Field(..., gt=0)
