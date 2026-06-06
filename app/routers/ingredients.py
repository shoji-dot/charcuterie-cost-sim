from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Annotated
from app.database import get_db
from app import models

router = APIRouter(prefix="/ingredients")
templates = Jinja2Templates(directory="app/templates")

CATEGORIES = ["肉", "野菜", "調味料", "油脂", "乳製品", "豆・穀物", "その他"]
UNITS = ["kg", "g", "L", "ml", "個", "枚", "本", "束", "缶"]


@router.get("", response_class=HTMLResponse)
async def ingredient_list(request: Request, db: Session = Depends(get_db)):
    masters = db.query(models.IngredientMaster).order_by(
        models.IngredientMaster.category, models.IngredientMaster.name
    ).all()
    return templates.TemplateResponse(
        request, "ingredients.html",
        {"masters": masters, "categories": CATEGORIES, "units": UNITS},
    )


@router.post("/save")
async def ingredient_save(
    request: Request,
    name: Annotated[str, Form()],
    unit_price: Annotated[float, Form()],
    price_unit: Annotated[str, Form()],
    category: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    existing = db.query(models.IngredientMaster).filter(
        models.IngredientMaster.name == name.strip()
    ).first()
    if existing:
        existing.unit_price = unit_price
        existing.price_unit = price_unit
        existing.category = category
    else:
        db.add(models.IngredientMaster(
            name=name.strip(),
            unit_price=unit_price,
            price_unit=price_unit,
            category=category,
        ))
    db.commit()
    return RedirectResponse("/ingredients", status_code=303)


@router.post("/delete/{master_id}")
async def ingredient_delete(master_id: int, db: Session = Depends(get_db)):
    m = db.query(models.IngredientMaster).filter(models.IngredientMaster.id == master_id).first()
    if m:
        db.delete(m)
        db.commit()
    return RedirectResponse("/ingredients", status_code=303)
