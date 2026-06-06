from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Annotated
from app.database import get_db
from app import models
from app.calculator import COST_RATE

router = APIRouter(prefix="/pig")
templates = Jinja2Templates(directory="app/templates")

PRESET_CUTS = ["ヒレ", "ロース", "肩ロース", "バラ", "モモ", "カタ", "スネ", "端肉"]


def calc_cut(carcass_weight: float, purchase_price: float,
             raw_weight: float, finished_weight: float, customer_tier: str) -> dict:
    """部位1点の原価計算"""
    unit_cost_rate = raw_weight / carcass_weight          # 重量比で原価を按分
    unit_cost = purchase_price * unit_cost_rate           # 部位原料原価 (円)
    cost_per_kg = unit_cost / finished_weight             # 完成品原価/kg
    cost_rate = COST_RATE[customer_tier]
    recommended_price = cost_per_kg / cost_rate           # 推奨販売価格/kg
    yield_rate = (finished_weight / raw_weight) * 100
    target_revenue = recommended_price * finished_weight  # 売上目標 (円)
    return {
        "unit_cost": round(unit_cost),
        "cost_per_kg": round(cost_per_kg),
        "recommended_price": round(recommended_price, -1),
        "yield_rate": round(yield_rate, 1),
        "target_revenue": round(target_revenue),
    }


def pig_summary(pig: models.WholePig) -> dict:
    """1頭全体の収支サマリー"""
    total_revenue = sum(c.target_revenue for c in pig.cuts)
    total_cost = pig.purchase_price
    allocated_weight = sum(c.raw_weight for c in pig.cuts)
    unallocated = pig.carcass_weight - allocated_weight
    gross_profit = total_revenue - total_cost
    margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    return {
        "total_revenue": round(total_revenue),
        "total_cost": round(total_cost),
        "gross_profit": round(gross_profit),
        "margin": round(margin, 1),
        "allocated_weight": round(allocated_weight, 2),
        "unallocated": round(unallocated, 2),
        "carcass_unit_price": round(pig.purchase_price / pig.carcass_weight, 1),
    }


# --- 1頭一覧 ---
@router.get("", response_class=HTMLResponse)
async def pig_list(request: Request, db: Session = Depends(get_db)):
    pigs = db.query(models.WholePig).order_by(models.WholePig.created_at.desc()).all()
    return templates.TemplateResponse("pig_list.html", {"request": request, "pigs": pigs})


# --- 新規1頭登録フォーム ---
@router.get("/new", response_class=HTMLResponse)
async def pig_new_form(request: Request):
    return templates.TemplateResponse("pig_new.html", {"request": request, "error": None})


# --- 新規1頭登録 ---
@router.post("/new")
async def pig_new_submit(
    request: Request,
    name: Annotated[str, Form()],
    carcass_weight: Annotated[float, Form()],
    purchase_price: Annotated[float, Form()],
    db: Session = Depends(get_db),
):
    if carcass_weight <= 0 or purchase_price <= 0:
        return templates.TemplateResponse(
            "pig_new.html", {"request": request, "error": "正の数を入力してください"}
        )
    pig = models.WholePig(name=name, carcass_weight=carcass_weight, purchase_price=purchase_price)
    db.add(pig)
    db.commit()
    db.refresh(pig)
    return RedirectResponse(f"/pig/{pig.id}", status_code=303)


# --- 部位一覧 + 収支 ---
@router.get("/{pig_id}", response_class=HTMLResponse)
async def pig_detail(request: Request, pig_id: int, db: Session = Depends(get_db)):
    pig = db.query(models.WholePig).filter(models.WholePig.id == pig_id).first()
    if not pig:
        return RedirectResponse("/pig", status_code=303)
    summary = pig_summary(pig)
    return templates.TemplateResponse(
        "pig_detail.html",
        {
            "request": request,
            "pig": pig,
            "summary": summary,
            "presets": PRESET_CUTS,
            "error": None,
        },
    )


# --- 部位追加 ---
@router.post("/{pig_id}/cut")
async def cut_add(
    request: Request,
    pig_id: int,
    name: Annotated[str, Form()],
    raw_weight: Annotated[float, Form()],
    finished_weight: Annotated[float, Form()],
    customer_tier: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    pig = db.query(models.WholePig).filter(models.WholePig.id == pig_id).first()
    if not pig:
        return RedirectResponse("/pig", status_code=303)

    result = calc_cut(pig.carcass_weight, pig.purchase_price, raw_weight, finished_weight, customer_tier)
    cut = models.Cut(
        pig_id=pig_id, name=name,
        raw_weight=raw_weight, finished_weight=finished_weight, customer_tier=customer_tier,
        **result,
    )
    db.add(cut)
    db.commit()
    return RedirectResponse(f"/pig/{pig_id}", status_code=303)


# --- 部位削除 ---
@router.post("/{pig_id}/cut/{cut_id}/delete")
async def cut_delete(pig_id: int, cut_id: int, db: Session = Depends(get_db)):
    cut = db.query(models.Cut).filter(models.Cut.id == cut_id, models.Cut.pig_id == pig_id).first()
    if cut:
        db.delete(cut)
        db.commit()
    return RedirectResponse(f"/pig/{pig_id}", status_code=303)


# --- 1頭削除 ---
@router.post("/{pig_id}/delete")
async def pig_delete(pig_id: int, db: Session = Depends(get_db)):
    pig = db.query(models.WholePig).filter(models.WholePig.id == pig_id).first()
    if pig:
        db.delete(pig)
        db.commit()
    return RedirectResponse("/pig", status_code=303)
