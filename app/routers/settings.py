from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Annotated
from datetime import datetime
from app.database import get_db
from app import models

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")


def get_current_monthly(db: Session) -> models.MonthlyCost | None:
    """最新の月次設定を取得"""
    return (
        db.query(models.MonthlyCost)
        .order_by(models.MonthlyCost.year.desc(), models.MonthlyCost.month.desc())
        .first()
    )


def calc_overhead(mc: models.MonthlyCost) -> dict:
    """固定費分析を計算"""
    total_fixed = mc.rent + mc.labor + mc.utilities + mc.supplies + mc.other
    fixed_per_kg = total_fixed / mc.production_kg if mc.production_kg > 0 else 0
    # 目標利益を出すために必要な最低売上/kg
    # 変動費(食材)は別途加算するため、ここでは固定費・利益の按分のみ
    # 推奨原価率の根拠:
    #   売上 = 食材費 + 固定費按分 + 利益
    #   原価率 = 食材費 / 売上  → 固定費と利益をどう扱うかを示す
    # 別の見方: 固定費按分 + 利益を "上乗せ係数" として可視化
    # 必要売上倍率 = 1 / (1 - 固定費率 - 目標利益率)
    # ここでは固定費を売上に対する比率で表現するため、売上の目安を平均原価から逆算
    # → 固定費/kg をシンプルに表示し、バッチ計算側で上乗せできるようにする
    return {
        "total_fixed": round(total_fixed),
        "fixed_per_kg": round(fixed_per_kg),
        "target_profit_rate_pct": round(mc.target_profit_rate * 100, 1),
        "rent": mc.rent,
        "labor": mc.labor,
        "utilities": mc.utilities,
        "supplies": mc.supplies,
        "other": mc.other,
    }


@router.get("", response_class=HTMLResponse)
async def settings_view(request: Request, db: Session = Depends(get_db)):
    now = datetime.now()
    mc = get_current_monthly(db)
    overhead = calc_overhead(mc) if mc else None
    history = (
        db.query(models.MonthlyCost)
        .order_by(models.MonthlyCost.year.desc(), models.MonthlyCost.month.desc())
        .limit(6)
        .all()
    )
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "mc": mc,
            "overhead": overhead,
            "history": history,
            "current_year": now.year,
            "current_month": now.month,
        },
    )


@router.post("/save")
async def settings_save(
    request: Request,
    year: Annotated[int, Form()],
    month: Annotated[int, Form()],
    rent: Annotated[float, Form()] = 0,
    labor: Annotated[float, Form()] = 0,
    utilities: Annotated[float, Form()] = 0,
    supplies: Annotated[float, Form()] = 0,
    other: Annotated[float, Form()] = 0,
    production_kg: Annotated[float, Form()] = 1,
    target_profit_rate: Annotated[float, Form()] = 20,
    takeout_packaging: Annotated[float, Form()] = 50,
    takeout_unit_weight: Annotated[float, Form()] = 0.2,
    eatin_multiplier: Annotated[float, Form()] = 1.15,
    notes: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    # 同月の設定があれば上書き
    existing = (
        db.query(models.MonthlyCost)
        .filter(models.MonthlyCost.year == year, models.MonthlyCost.month == month)
        .first()
    )
    if existing:
        existing.rent = rent
        existing.labor = labor
        existing.utilities = utilities
        existing.supplies = supplies
        existing.other = other
        existing.production_kg = production_kg
        existing.target_profit_rate = target_profit_rate / 100
        existing.takeout_packaging = takeout_packaging
        existing.takeout_unit_weight = takeout_unit_weight
        existing.eatin_multiplier = eatin_multiplier
        existing.notes = notes
    else:
        mc = models.MonthlyCost(
            year=year, month=month,
            rent=rent, labor=labor, utilities=utilities,
            supplies=supplies, other=other,
            production_kg=production_kg,
            target_profit_rate=target_profit_rate / 100,
            takeout_packaging=takeout_packaging,
            takeout_unit_weight=takeout_unit_weight,
            eatin_multiplier=eatin_multiplier,
            notes=notes,
        )
        db.add(mc)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/delete/{mc_id}")
async def settings_delete(mc_id: int, db: Session = Depends(get_db)):
    mc = db.query(models.MonthlyCost).filter(models.MonthlyCost.id == mc_id).first()
    if mc:
        db.delete(mc)
        db.commit()
    return RedirectResponse("/settings", status_code=303)
