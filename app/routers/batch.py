from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Annotated, Optional
from app.database import get_db
from app import models
from app.calculator import get_cost_rate, get_tier_label, convert_to_price_unit

router = APIRouter(prefix="/batch")
templates = Jinja2Templates(directory="app/templates")

CATEGORIES = ["肉", "野菜", "調味料", "油脂", "乳製品", "豆・穀物", "その他"]
UNITS = ["kg", "g", "L", "ml", "個", "枚", "本", "束", "缶"]


def calc_batch(total_cost: float, finished_weight: float, customer_tier: str,
               custom_gross_margin: float = None) -> dict:
    cost_rate = get_cost_rate(customer_tier, custom_gross_margin)
    cost_per_kg = total_cost / finished_weight
    recommended_price = cost_per_kg / cost_rate
    gross_margin = (1 - cost_rate) * 100
    return {
        "total_cost": round(total_cost),
        "cost_per_kg": round(cost_per_kg),
        "recommended_price": round(recommended_price, -1),
        "gross_margin": round(gross_margin, 1),
        "custom_rate": cost_rate if customer_tier == "custom" else None,
    }


@router.get("", response_class=HTMLResponse)
async def batch_list(request: Request, db: Session = Depends(get_db)):
    templates_list = db.query(models.RecipeTemplate).order_by(models.RecipeTemplate.id).all()
    batches = db.query(models.Batch).order_by(models.Batch.created_at.desc()).limit(20).all()
    return templates.TemplateResponse(
        request, "batch_list.html",
        {"recipe_templates": templates_list, "batches": batches},
    )


@router.get("/new/{template_id}", response_class=HTMLResponse)
async def batch_new_form(request: Request, template_id: int, db: Session = Depends(get_db)):
    tmpl = db.query(models.RecipeTemplate).filter(models.RecipeTemplate.id == template_id).first()
    if not tmpl:
        return RedirectResponse("/batch", status_code=303)

    last_batch = (
        db.query(models.Batch)
        .filter(models.Batch.template_id == template_id)
        .order_by(models.Batch.created_at.desc())
        .first()
    )
    last_ing_map = {}
    if last_batch:
        for ing in last_batch.ingredients:
            last_ing_map[ing.name] = {
                "amount": ing.amount,
                "unit": ing.unit,
                "unit_price": ing.unit_price,
                "price_unit": ing.price_unit if ing.price_unit else "kg",
                "category": ing.category,
            }

    return templates.TemplateResponse(
        request, "batch_form.html",
        {
            "tmpl": tmpl,
            "categories": CATEGORIES,
            "units": UNITS,
            "last_batch": last_batch,
            "last_ing_map": last_ing_map,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def batch_new_custom(request: Request):
    return templates.TemplateResponse(
        request, "batch_form.html",
        {
            "tmpl": None,
            "categories": CATEGORIES,
            "units": UNITS,
        },
    )


@router.post("/save")
async def batch_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    name = form.get("batch_name", "")
    template_id = form.get("template_id")
    template_id = int(template_id) if template_id else None
    finished_weight = float(form.get("finished_weight", 1))
    customer_tier = form.get("customer_tier", "standard")
    custom_gm_raw = form.get("custom_gross_margin", "")
    custom_gross_margin = float(custom_gm_raw) if custom_gm_raw else None
    notes = form.get("notes", "")
    portion_weight_raw = form.get("portion_weight", "")
    portion_weight = float(portion_weight_raw) if portion_weight_raw else None
    portion_unit = form.get("portion_unit", "g")

    names = form.getlist("ing_name")
    amounts = form.getlist("ing_amount")
    units = form.getlist("ing_unit")
    unit_prices = form.getlist("ing_unit_price")
    price_units = form.getlist("ing_price_unit")
    cats = form.getlist("ing_category")

    ingredients = []
    total_cost = 0.0
    for n, a, u, p, pu, c in zip(names, amounts, units, unit_prices, price_units, cats):
        if not n or not a or not p:
            continue
        amount = float(a)
        price = float(p)
        price_unit = pu if pu else "kg"
        converted = convert_to_price_unit(amount, u, price_unit)
        subtotal = converted * price
        total_cost += subtotal
        ingredients.append({
            "name": n, "amount": amount, "unit": u,
            "unit_price": price, "price_per": 1.0,
            "price_unit": price_unit,
            "subtotal": subtotal, "category": c,
        })

    result = calc_batch(total_cost, finished_weight, customer_tier, custom_gross_margin)

    batch = models.Batch(
        template_id=template_id,
        name=name,
        finished_weight=finished_weight,
        customer_tier=customer_tier,
        custom_rate=result.pop("custom_rate"),
        notes=notes,
        portion_weight=portion_weight,
        portion_unit=portion_unit,
        **result,
    )
    db.add(batch)
    db.flush()

    for ing in ingredients:
        db.add(models.BatchIngredient(batch_id=batch.id, **ing))

    db.commit()
    return RedirectResponse(f"/batch/{batch.id}", status_code=303)


@router.get("/{batch_id}", response_class=HTMLResponse)
async def batch_detail(request: Request, batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(models.Batch).filter(models.Batch.id == batch_id).first()
    if not batch:
        return RedirectResponse("/batch", status_code=303)
    tier_label = get_tier_label(batch.customer_tier, batch.gross_margin)
    by_category = {}
    for ing in batch.ingredients:
        by_category.setdefault(ing.category, []).append(ing)

    mc = (
        db.query(models.MonthlyCost)
        .order_by(models.MonthlyCost.year.desc(), models.MonthlyCost.month.desc())
        .first()
    )
    full_price = None
    if mc and mc.production_kg > 0:
        overhead_per_kg = (mc.rent + mc.labor + mc.utilities + mc.supplies + mc.other) / mc.production_kg
        total_cost_per_kg = batch.cost_per_kg + overhead_per_kg
        recommended = total_cost_per_kg / (1 - mc.target_profit_rate)
        profit_per_kg = recommended - total_cost_per_kg
        takeout_per_item = recommended * mc.takeout_unit_weight + mc.takeout_packaging
        eatin_per_item = takeout_per_item * mc.eatin_multiplier
        full_price = {
            "recommended": round(recommended, -1),
            "overhead_per_kg": round(overhead_per_kg),
            "profit_per_kg": round(profit_per_kg),
            "takeout_per_item": round(takeout_per_item, -1),
            "eatin_per_item": round(eatin_per_item, -1),
        }

    return templates.TemplateResponse(
        request, "batch_result.html",
        {
            "batch": batch,
            "tier_label": tier_label,
            "by_category": by_category,
            "full_price": full_price,
            "mc": mc,
        },
    )


@router.post("/{batch_id}/delete")
async def batch_delete(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(models.Batch).filter(models.Batch.id == batch_id).first()
    if batch:
        db.delete(batch)
        db.commit()
    return RedirectResponse("/batch", status_code=303)


@router.get("/template/{template_id}/edit", response_class=HTMLResponse)
async def template_edit_form(request: Request, template_id: int, db: Session = Depends(get_db)):
    tmpl = db.query(models.RecipeTemplate).filter(models.RecipeTemplate.id == template_id).first()
    if not tmpl:
        return RedirectResponse("/batch", status_code=303)
    return templates.TemplateResponse(
        request, "template_edit.html",
        {"tmpl": tmpl, "categories": CATEGORIES, "units": UNITS},
    )


@router.post("/template/{template_id}/edit")
async def template_edit_save(request: Request, template_id: int, db: Session = Depends(get_db)):
    tmpl = db.query(models.RecipeTemplate).filter(models.RecipeTemplate.id == template_id).first()
    if not tmpl:
        return RedirectResponse("/batch", status_code=303)

    form = await request.form()
    tmpl.notes = form.get("notes", "")

    for old in tmpl.ingredients:
        db.delete(old)
    db.flush()

    names = form.getlist("ing_name")
    amounts = form.getlist("ing_amount")
    units_list = form.getlist("ing_unit")
    cats = form.getlist("ing_category")

    for n, a, u, c in zip(names, amounts, units_list, cats):
        if not n or not a:
            continue
        db.add(models.TemplateIngredient(
            template_id=template_id,
            name=n, default_amount=float(a), unit=u, category=c,
        ))
    db.commit()
    return RedirectResponse(f"/batch/new/{template_id}", status_code=303)


@router.get("/template/new", response_class=HTMLResponse)
async def template_new_form(request: Request):
    return templates.TemplateResponse(
        request, "template_edit.html",
        {"tmpl": None, "categories": CATEGORIES, "units": UNITS},
    )


@router.post("/template/new")
async def template_new_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    name = form.get("name", "").strip()
    if not name:
        return templates.TemplateResponse(
            request, "template_edit.html",
            {"tmpl": None, "categories": CATEGORIES, "units": UNITS, "error": "名前を入力してください"},
        )
    existing = db.query(models.RecipeTemplate).filter(models.RecipeTemplate.name == name).first()
    if existing:
        return RedirectResponse(f"/batch/template/{existing.id}/edit", status_code=303)

    tmpl = models.RecipeTemplate(name=name, notes=form.get("notes", ""))
    db.add(tmpl)
    db.flush()

    names = form.getlist("ing_name")
    amounts = form.getlist("ing_amount")
    units_list = form.getlist("ing_unit")
    cats = form.getlist("ing_category")
    for n, a, u, c in zip(names, amounts, units_list, cats):
        if not n or not a:
            continue
        db.add(models.TemplateIngredient(
            template_id=tmpl.id,
            name=n, default_amount=float(a), unit=u, category=c,
        ))
    db.commit()
    return RedirectResponse(f"/batch/new/{tmpl.id}", status_code=303)


@router.post("/template/{template_id}/delete")
async def template_delete(template_id: int, db: Session = Depends(get_db)):
    tmpl = db.query(models.RecipeTemplate).filter(models.RecipeTemplate.id == template_id).first()
    if tmpl:
        db.delete(tmpl)
        db.commit()
    return RedirectResponse("/batch", status_code=303)
