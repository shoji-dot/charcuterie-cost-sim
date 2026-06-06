from pydantic import BaseModel, field_validator
from typing import Literal, Optional
from datetime import datetime


class CalcInput(BaseModel):
    raw_weight: float
    raw_price: float
    finished_weight: float
    customer_tier: Literal["premium", "standard", "custom"]
    custom_gross_margin: Optional[float] = None  # カスタム選択時のみ使用 (%)

    @field_validator("raw_weight", "raw_price", "finished_weight")
    @classmethod
    def must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("0より大きい値を入力してください")
        return v


class CalcResult(BaseModel):
    yield_rate: float        # %
    cost_per_kg: float       # 円/kg
    recommended_price: float # 円/kg
    gross_margin: float      # %


class RecipeSave(BaseModel):
    name: str
    raw_weight: float
    raw_price: float
    finished_weight: float
    customer_tier: str  # "premium" / "standard" / "custom"


class RecipeOut(RecipeSave, CalcResult):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
