from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app import schemas, crud, models
from app.calculator import calculate, get_tier_label
from app.database import get_db
from typing import Annotated, Optional

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    recipes = crud.list_recipes(db)
    mc = (
        db.query(models.MonthlyCost)
        .order_by(models.MonthlyCost.year.desc(), models.MonthlyCost.month.desc())
        .first()
    )
    settings_summary = None
    if mc:
        total_fixed = mc.rent + mc.labor + mc.utilities + mc.supplies + mc.other
        settings_summary = {
            "year": mc.year, "month": mc.month,
            "total_fixed": total_fixed,
            "fixed_per_kg": round(total_fixed / mc.production_kg) if mc.production_kg else 0,
        }
    return templates.TemplateResponse("index.html", {
        "request": request,
        "recipes": recipes,
        "has_settings": mc is not None,
        "settings_summary": settings_summary,
    })


@router.get("/calc", response_class=HTMLResponse)
async def calc_form(request: Request):
    return templates.TemplateResponse("input.html", {"request": request, "error": None})


@router.post("/calc", response_class=HTMLResponse)
async def calc_submit(
    request: Request,
    raw_weight: Annotated[float, Form()],
    raw_price: Annotated[float, Form()],
    finished_weight: Annotated[float, Form()],
    customer_tier: Annotated[str, Form()],
    custom_gross_margin: Annotated[Optional[float], Form()] = None,
):
    try:
        if raw_weight <= 0 or raw_price <= 0 or finished_weight <= 0:
            raise ValueError("入力値エラー")
    except Exception:
        return templates.TemplateResponse(
            "input.html", {"request": request, "error": "入力値を確認してください"}
        )

    result = calculate(raw_weight, raw_price, finished_weight, customer_tier, custom_gross_margin)
    tier_label = get_tier_label(customer_tier, result["gross_margin"])
    inp = {
        "raw_weight": raw_weight, "raw_price": raw_price,
        "finished_weight": finished_weight, "customer_tier": customer_tier,
    }
    return templates.TemplateResponse(
        "result.html",
        {"request": request, "result": result, "input": inp, "tier_label": tier_label},
    )


@router.post("/save", response_class=HTMLResponse)
async def save_recipe(
    request: Request,
    name: Annotated[str, Form()],
    raw_weight: Annotated[float, Form()],
    raw_price: Annotated[float, Form()],
    finished_weight: Annotated[float, Form()],
    customer_tier: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    data = schemas.RecipeSave(
        name=name, raw_weight=raw_weight, raw_price=raw_price,
        finished_weight=finished_weight, customer_tier=customer_tier,
    )
    result = calculate(data.raw_weight, data.raw_price, data.finished_weight, data.customer_tier)
    crud.save_recipe(db, data, result)
    recipes = crud.list_recipes(db)
    mc = (
        db.query(models.MonthlyCost)
        .order_by(models.MonthlyCost.year.desc(), models.MonthlyCost.month.desc())
        .first()
    )
    settings_summary = None
    if mc:
        total_fixed = mc.rent + mc.labor + mc.utilities + mc.supplies + mc.other
        settings_summary = {
            "year": mc.year, "month": mc.month,
            "total_fixed": total_fixed,
            "fixed_per_kg": round(total_fixed / mc.production_kg) if mc.production_kg else 0,
        }
    return templates.TemplateResponse("index.html", {
        "request": request, "recipes": recipes, "saved": name,
        "has_settings": mc is not None, "settings_summary": settings_summary,
    })


@router.post("/delete/{recipe_id}", response_class=HTMLResponse)
async def delete_recipe(request: Request, recipe_id: int, db: Session = Depends(get_db)):
    crud.delete_recipe(db, recipe_id)
    recipes = crud.list_recipes(db)
    return templates.TemplateResponse("index.html", {"request": request, "recipes": recipes,
        "has_settings": False, "settings_summary": None})


@router.get("/recipe/{recipe_id}", response_class=HTMLResponse)
async def load_recipe(request: Request, recipe_id: int, db: Session = Depends(get_db)):
    recipe = crud.get_recipe(db, recipe_id)
    if not recipe:
        return templates.TemplateResponse("index.html", {"request": request, "recipes": [],
            "has_settings": False, "settings_summary": None})
    result = {
        "yield_rate": recipe.yield_rate,
        "cost_per_kg": recipe.cost_per_kg,
        "recommended_price": recipe.recommended_price,
        "gross_margin": recipe.gross_margin,
    }
    inp = {
        "raw_weight": recipe.raw_weight,
        "raw_price": recipe.raw_price,
        "finished_weight": recipe.finished_weight,
        "customer_tier": recipe.customer_tier,
    }
    tier_label = get_tier_label(recipe.customer_tier, recipe.gross_margin)
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "result": result,
            "input": inp,
            "tier_label": tier_label,
            "recipe_name": recipe.name,
        },
    )
