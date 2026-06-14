from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Recipe(Base):
    __tablename__ = "recipes"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    raw_weight = Column(Float, nullable=False)
    raw_price = Column(Float, nullable=False)
    finished_weight = Column(Float, nullable=False)
    customer_tier = Column(String, nullable=False)
    yield_rate = Column(Float, nullable=False)
    cost_per_kg = Column(Float, nullable=False)
    recommended_price = Column(Float, nullable=False)
    gross_margin = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class WholePig(Base):
    __tablename__ = "whole_pigs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    carcass_weight = Column(Float, nullable=False)
    purchase_price = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    cuts = relationship("Cut", back_populates="pig", cascade="all, delete-orphan")


class Cut(Base):
    __tablename__ = "cuts"
    id = Column(Integer, primary_key=True, index=True)
    pig_id = Column(Integer, ForeignKey("whole_pigs.id"), nullable=False)
    name = Column(String, nullable=False)
    raw_weight = Column(Float, nullable=False)
    finished_weight = Column(Float, nullable=False)
    customer_tier = Column(String, nullable=False)
    unit_cost = Column(Float, nullable=False)
    cost_per_kg = Column(Float, nullable=False)
    recommended_price = Column(Float, nullable=False)
    yield_rate = Column(Float, nullable=False)
    gross_margin = Column(Float, nullable=True)
    custom_gross_margin = Column(Float, nullable=True)
    target_revenue = Column(Float, nullable=False)
    pig = relationship("WholePig", back_populates="cuts")


# ── レシピテンプレート ─────────────────────────────────────────
class RecipeTemplate(Base):
    """レシピのマスターデータ（食材リスト付き）"""
    __tablename__ = "recipe_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    notes = Column(Text, nullable=True)
    ingredients = relationship(
        "TemplateIngredient", back_populates="template",
        cascade="all, delete-orphan", order_by="TemplateIngredient.id"
    )
    default_customer_tier = Column(String, default="standard")
    default_gross_margin = Column(Float, nullable=True)
    batches = relationship("Batch", back_populates="template")


class TemplateIngredient(Base):
    """レシピテンプレートのデフォルト食材"""
    __tablename__ = "template_ingredients"
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("recipe_templates.id"), nullable=False)
    name = Column(String, nullable=False)
    default_amount = Column(Float, nullable=False)
    unit = Column(String, nullable=False)
    category = Column(String, nullable=False)
    template = relationship("RecipeTemplate", back_populates="ingredients")


# ── バッチ（実際の生産記録）─────────────────────────────────────
class Batch(Base):
    """1回の仕込み記録（食材・原価計算結果）"""
    __tablename__ = "batches"
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("recipe_templates.id"), nullable=True)
    name = Column(String, nullable=False)
    finished_weight = Column(Float, nullable=False)
    customer_tier = Column(String, nullable=False)
    custom_rate = Column(Float, nullable=True)          # カスタム粗利時の原価率 (0.0〜1.0)
    total_cost = Column(Float, nullable=False)
    cost_per_kg = Column(Float, nullable=False)
    recommended_price = Column(Float, nullable=False)
    gross_margin = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    waste_weight = Column(Float, nullable=True)
    raw_weight = Column(Float, nullable=True)   # 仕込み前重量
    portion_weight = Column(Float, nullable=True)
    portion_unit = Column(String, default="g")
    created_at = Column(DateTime, default=datetime.utcnow)
    template = relationship("RecipeTemplate", back_populates="batches")
    ingredients = relationship(
        "BatchIngredient", back_populates="batch",
        cascade="all, delete-orphan", order_by="BatchIngredient.id"
    )


class BatchIngredient(Base):
    """バッチで実際に使った食材と価格"""
    __tablename__ = "batch_ingredients"
    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    unit = Column(String, nullable=False)
    unit_price = Column(Float, nullable=False)
    price_per = Column(Float, nullable=False, server_default="1")
    price_unit = Column(String, nullable=False, server_default="kg")
    subtotal = Column(Float, nullable=False)
    category = Column(String, nullable=False)
    batch = relationship("Batch", back_populates="ingredients")


# ── 固定費・経営設定 ──────────────────────────────────────────
class MonthlyCost(Base):
    """月次固定費と経営目標の設定"""
    __tablename__ = "monthly_costs"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    rent = Column(Float, default=0.0)
    labor = Column(Float, default=0.0)
    utilities = Column(Float, default=0.0)
    supplies = Column(Float, default=0.0)
    other = Column(Float, default=0.0)
    production_kg = Column(Float, nullable=False)
    target_profit_rate = Column(Float, default=0.20)
    takeout_packaging = Column(Float, default=50.0)
    takeout_unit_weight = Column(Float, default=0.2)
    eatin_multiplier = Column(Float, default=1.15)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── 食材マスター ──────────────────────────────────────────────
class IngredientMaster(Base):
    """よく使う食材の単価マスター"""
    __tablename__ = "ingredient_masters"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    unit_price = Column(Float, nullable=False)
    price_unit = Column(String, nullable=False, default="kg")
    category = Column(String, nullable=False, default="その他")
    updated_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # NULL = 有効, 設定済み = 論理削除
