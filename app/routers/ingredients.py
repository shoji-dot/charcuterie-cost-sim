import logging
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Annotated
from app.database import get_db
from app import models

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingredients")
templates = Jinja2Templates(directory="app/templates")

CATEGORIES = ["肉", "野菜", "調味料", "油脂", "乳製品", "豆", "穀物", "その他"]
UNITS = ["kg", "g", "L", "ml", "個", "枚", "本", "束", "缶"]

SEED_INGREDIENTS = [
    ("豚バラ肉", 1200, "kg", "肉"),
    ("豚ロース肉", 1000, "kg", "肉"),
    ("豚肩ロース", 880, "kg", "肉"),
    ("豚もも肉", 750, "kg", "肉"),
    ("豚ヒレ肉", 1500, "kg", "肉"),
    ("豚スペアリブ", 900, "kg", "肉"),
    ("豚背脂", 300, "kg", "肉"),
    ("豚ひき肉", 700, "kg", "肉"),
    ("豚レバー", 400, "kg", "肉"),
    ("豚頭肉", 500, "kg", "肉"),
    ("鴨むね肉", 2000, "kg", "肉"),
    ("鴨もも肉", 1800, "kg", "肉"),
    ("牛タン", 2800, "kg", "肉"),
    ("ニンニク", 1500, "kg", "野菜"),
    ("タマネギ", 200, "kg", "野菜"),
    ("エシャロット", 1200, "kg", "野菜"),
    ("ショウガ", 600, "kg", "野菜"),
    ("パセリ", 500, "束", "野菜"),
    ("タイム", 400, "束", "野菜"),
    ("ローリエ", 300, "束", "野菜"),
    ("ローズマリー", 400, "束", "野菜"),
    ("セージ", 400, "束", "野菜"),
    ("マジョラム", 600, "束", "野菜"),
    ("オレガノ", 600, "束", "野菜"),
    ("セロリ", 300, "kg", "野菜"),
    ("チャービル", 800, "束", "野菜"),
    ("塩", 200, "kg", "調味料"),
    ("岩塩", 500, "kg", "調味料"),
    ("黒こしょう", 3000, "kg", "調味料"),
    ("白こしょう", 3500, "kg", "調味料"),
    ("上白糖", 200, "kg", "調味料"),
    ("きび砂糖", 500, "kg", "調味料"),
    ("ピンクソルト", 2000, "kg", "調味料"),
    ("亜硝酸塩", 3000, "kg", "調味料"),
    ("ジュニパーベリー", 4000, "kg", "調味料"),
    ("ナツメグ", 5000, "kg", "調味料"),
    ("クローブ", 4000, "kg", "調味料"),
    ("シナモン", 3000, "kg", "調味料"),
    ("パプリカパウダー", 2000, "kg", "調味料"),
    ("キャラウェイ", 3500, "kg", "調味料"),
    ("コリアンダー", 1500, "kg", "調味料"),
    ("フェンネルシード", 3000, "kg", "調味料"),
    ("チリパウダー", 2500, "kg", "調味料"),
    ("カルダモン", 8000, "kg", "調味料"),
    ("白ワイン", 800, "L", "調味料"),
    ("赤ワイン", 800, "L", "調味料"),
    ("ブランデー", 2000, "L", "調味料"),
    ("ポートワイン", 1500, "L", "調味料"),
    ("カルヴァドス", 3000, "L", "調味料"),
    ("日本酒", 400, "L", "調味料"),
    ("みりん", 600, "L", "調味料"),
    ("醤油", 500, "L", "調味料"),
    ("ラード", 400, "kg", "油脂"),
    ("サラダ油", 400, "L", "油脂"),
    ("オリーブオイル", 1500, "L", "油脂"),
    ("バター", 800, "kg", "油脂"),
    ("グースファット", 900, "kg", "油脂"),
    ("生クリーム", 1500, "L", "乳製品"),
    ("牛乳", 250, "L", "乳製品"),
    ("クリームチーズ", 1500, "kg", "乳製品"),
    ("粉乳", 1000, "kg", "乳製品"),
    ("大豆タンパク", 800, "kg", "豆"),
    ("大豆", 300, "kg", "豆"),
    ("パン粉", 400, "kg", "穀物"),
    ("小麦粉", 200, "kg", "穀物"),
    ("片栗粉", 300, "kg", "穀物"),
    ("コーンスターチ", 400, "kg", "穀物"),
    ("豚腸ケーシング", 3000, "kg", "その他"),
    ("コラーゲンケーシング", 5000, "kg", "その他"),
    ("スモークチップ", 1000, "kg", "その他"),
    ("氷", 100, "kg", "その他"),
    ("ゼラチン", 3000, "kg", "その他"),
    ("カラギーナン", 5000, "kg", "その他"),
]


@router.get("", response_class=HTMLResponse)
async def ingredient_list(request: Request, db: Session = Depends(get_db)):
    masters = db.query(models.IngredientMaster).filter(
        models.IngredientMaster.deleted_at.is_(None)
    ).order_by(
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
    clean_name = name.strip()
    existing = db.query(models.IngredientMaster).filter(
        models.IngredientMaster.name == clean_name
    ).first()
    if existing:
        existing.unit_price = unit_price
        existing.price_unit = price_unit
        existing.category = category
        existing.updated_at = datetime.utcnow()
        existing.deleted_at = None
        logger.info("master updated: %s", clean_name)
    else:
        db.add(models.IngredientMaster(
            name=clean_name,
            unit_price=unit_price,
            price_unit=price_unit,
            category=category,
        ))
        logger.info("master created: %s", clean_name)
    db.flush()

    batch_ings = db.query(models.BatchIngredient).filter(
        models.BatchIngredient.name == clean_name
    ).all()
    for bi in batch_ings:
        bi.unit_price = unit_price
        bi.price_unit = price_unit
        amount_converted = bi.amount
        if bi.unit == "kg" and price_unit == "g":
            amount_converted = bi.amount * 1000
        elif bi.unit == "g" and price_unit == "kg":
            amount_converted = bi.amount / 1000
        elif bi.unit == "L" and price_unit == "ml":
            amount_converted = bi.amount * 1000
        elif bi.unit == "ml" and price_unit == "L":
            amount_converted = bi.amount / 1000
        bi.subtotal = round(amount_converted * unit_price, 2)

    db.commit()
    return RedirectResponse("/ingredients", status_code=303)


@router.post("/delete/{master_id}")
async def ingredient_delete(master_id: int, db: Session = Depends(get_db)):
    m = db.query(models.IngredientMaster).filter(models.IngredientMaster.id == master_id).first()
    if m:
        m.deleted_at = datetime.utcnow()
        db.commit()
        logger.info("master deleted: id=%s name=%s", master_id, m.name)
    return RedirectResponse("/ingredients", status_code=303)


@router.post("/seed")
async def ingredient_seed(db: Session = Depends(get_db)):
    added = 0
    for name, price, unit, cat in SEED_INGREDIENTS:
        existing = db.query(models.IngredientMaster).filter(
            models.IngredientMaster.name == name
        ).first()
        if not existing:
            db.add(models.IngredientMaster(
                name=name, unit_price=price, price_unit=unit, category=cat
            ))
            added += 1
        elif existing.deleted_at is not None:
            existing.deleted_at = None
            added += 1
    db.commit()
    logger.info("seed done: %d added", added)
    return RedirectResponse("/ingredients", status_code=303)
