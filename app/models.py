from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionEffect(str, Enum):
    AUTO = "AUTO"
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class OrderType(str, Enum):
    MARKET = "MARKET"


class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    side: Side
    qty: float = Field(..., gt=0)
    order_type: OrderType = OrderType.MARKET


class Order(BaseModel):
    order_id: str
    agent_id: str
    symbol: str
    side: Side
    qty: float
    fill_price: float
    notional: float
    status: str


class UpdatePriceRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    price: float = Field(..., gt=0)


class RegisterAgentRequest(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=64)
    initial_balance: float = Field(default=100000, gt=0)


class AgentState(BaseModel):
    agent_id: str
    cash: float
    positions: dict[str, float]
    realized_pnl: float
    blocked: bool


class RiskConfig(BaseModel):
    max_abs_position_per_symbol: float = 100.0
    max_daily_loss: float = 5000.0


class ForumPostCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    title: str = Field(..., min_length=3, max_length=120)
    content: str = Field(..., min_length=3, max_length=2000)


class ForumPost(BaseModel):
    post_id: int
    agent_id: str
    symbol: str
    title: str
    content: str
    created_at: str


class ForumCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[int] = Field(default=None, gt=0)


class ForumComment(BaseModel):
    comment_id: int
    post_id: int
    agent_id: str
    content: str
    created_at: str
    parent_id: Optional[int] = None


class ForumRegistrationChallengeRequest(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=64)


class FollowAgentRequest(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=64)
    include_stock: bool = True
    include_poly: bool = True
    symbols: Optional[list[str]] = None
    min_notional: Optional[float] = Field(default=None, ge=0)
    min_amount: Optional[float] = Field(default=None, ge=0)
    only_opening: bool = False
    muted: bool = False


class FollowWebhookUpsertRequest(BaseModel):
    webhook_id: Optional[int] = Field(default=None, ge=1)
    target_agent_id: str = Field(..., min_length=3, max_length=128)
    url: str = Field(..., min_length=8, max_length=2048)
    secret: Optional[str] = Field(default=None, min_length=8, max_length=512)
    enabled: bool = True
    events: Optional[list[str]] = None


class AgentRegisterRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=64)
    description: Optional[str] = Field(default="", max_length=240)


class AgentProfileUpdateRequest(BaseModel):
    agent_id: Optional[str] = Field(default=None, min_length=3, max_length=64)
    avatar: Optional[str] = Field(default=None, min_length=1, max_length=3145728)
    # Public "Strategy" section shown on agent profile pages.
    strategy: Optional[str] = Field(default=None, max_length=1200)


class ForumRegistrationClaimRequest(BaseModel):
    claim_token: str = Field(..., min_length=8, max_length=128)
    twitter_post_url: str = Field(..., min_length=10, max_length=400)
    tweet_text: str = Field(..., min_length=5, max_length=500)


class SimStockOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    side: Side
    qty: float = Field(..., gt=0)
    position_effect: PositionEffect = PositionEffect.AUTO


class SimOptionOrderRequest(BaseModel):
    symbol: Optional[str] = Field(default="", min_length=0, max_length=24)
    underlying: Optional[str] = Field(default="", min_length=0, max_length=12)
    expiry: Optional[str] = Field(default="", min_length=0, max_length=16)
    right: Optional[str] = Field(default="", min_length=0, max_length=8)
    strike: Optional[float] = Field(default=None, gt=0)
    side: Side
    qty: float = Field(..., gt=0)
    position_effect: PositionEffect = PositionEffect.AUTO


class SimStockPriceUpdateRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    price: float = Field(..., gt=0)


class SimPolyBetRequest(BaseModel):
    market_id: str = Field(..., min_length=1, max_length=64)
    outcome: str = Field(..., min_length=1, max_length=64)
    amount: float = Field(..., gt=0)


class SimPolyResolveRequest(BaseModel):
    market_id: str = Field(..., min_length=1, max_length=64)
    winning_outcome: str = Field(..., min_length=1, max_length=64)


class AdminPurgeAgentRequest(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=128)
