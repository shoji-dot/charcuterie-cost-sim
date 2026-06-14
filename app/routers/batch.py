from fastapi import APIRouter, Request, Form, Depends
import csv
import io
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from datetime import date
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Annotated, Optional
from app.database import get_db
from app import models
from app.calculator import get_cost_rate, get_tier_label, convert_to_price_unit

router = APIRouter(prefix="/batch")
templates = Jinja2Templates(directory="app/templates")

CATEGORIES = ["肉", "野菜", "調味料", "油脂", "乳製品", "豆", "穀物", "その他"]
UNITS = ["kg", "g", "L", "ml", "個", "枚", "本", "束", "缶"]

# 変換可能な単位グループ（同グループ内のみ変換可能）
_UNIT_GROUPS = {
    "kg": "weight", "g": "weight",
    "L": "volume", "ml": "volume",
    "個": "count", "枚": "count", "本": "count", "束": "count", "缶": "count",
}


def _units_compatible(from_unit: str, to_unit: str) -> bool:
    """異種単位（g→L など）の組み合わせを検知"""
    if from_unit == to_unit:
        return True
    g1 = _UNIT_GROUPS.get(from_unit)
    g2 = _UNIT_GROUPS.get(to_unit)
    if g1 is None or g2 is None:
        return True  # 未知単位はスルー
    return g1 == g2


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


@router.get("/ranking", response_class=HTMLResponse)
async def batch_ranking(request: Request, db: Session = Depends(get_db), sort: str = "profit"):
    """粗利額・粗利率ランキング（レシピ別集計）"""
    batches = db.query(models.Batch).all()

    # レシピ名でグループ集計
    groups: dict = {}
    for b in batches:
        key = b.name
        gross_profit = b.recommended_price * b.finished_weight - b.total_cost
        if key not in groups:
            groups[key] = {
                "name": key,
                "batch_count": 0,
                "total_gross_profit": 0.0,
                "total_weight": 0.0,
                "total_cost": 0.0,
                "total_revenue": 0.0,
                "margin_sum": 0.0,
            }
        g = groups[key]
        g["batch_count"] += 1
        g["total_gross_profit"] += gross_profit
        g["total_weight"] += b.finished_weight
        g["total_cost"] += b.total_cost
        g["total_revenue"] += b.recommended_price * b.finished_weight
        g["margin_sum"] += b.gross_margin

    ranked = []
    for g in groups.values():
        avg_margin = g["margin_sum"] / g["batch_count"] if g["batch_count"] else 0
        profit_per_kg = g["total_gross_profit"] / g["total_weight"] if g["total_weight"] else 0
        ranked.append({
            "name": g["name"],
            "batch_count": g["batch_count"],
            "total_gross_profit": round(g["total_gross_profit"]),
            "total_weight": round(g["total_weight"], 1),
            "avg_margin": round(avg_margin, 1),
            "profit_per_kg": round(profit_per_kg),
        })

    sort_key = "avg_margin" if sort == "margin" else "total_gross_profit"
    ranked.sort(key=lambda x: x[sort_key], reverse=True)

    return templates.TemplateResponse(
        request, "batch_ranking.html",
        {"ranked": ranked, "sort": sort},
    )


@router.get("", response_class=HTMLResponse)
async def batch_list(request: Request, db: Session = Depends(get_db), page: int = 1):
    from datetime import date
    PER_PAGE = 20
    templates_list = db.query(models.RecipeTemplate).order_by(models.RecipeTemplate.id).all()
    total = db.query(models.Batch).count()
    batches = (
        db.query(models.Batch)
        .order_by(models.Batch.created_at.desc())
        .offset((page - 1) * PER_PAGE)
        .limit(PER_PAGE)
        .all()
    )
    today = date.today()
    total_pages = (total + PER_PAGE - 1) // PER_PAGE

    # 値上げアラートマップ: batch_id -> diff_pct (3%超の場合のみ)
    alert_map = {}
    for b in batches:
        if b.template_id:
            prev = (
                db.query(models.Batch)
                .filter(
                    models.Batch.template_id == b.template_id,
                    models.Batch.id != b.id,
                    models.Batch.created_at < b.created_at,
                )
                .order_by(models.Batch.created_at.desc())
                .first()
            )
            if prev and prev.cost_per_kg > 0:
                diff_pct = (b.cost_per_kg - prev.cost_per_kg) / prev.cost_per_kg * 100
                if diff_pct > 3.0:
                    alert_map[b.id] = round(diff_pct, 1)

    return templates.TemplateResponse(
        request, "batch_list.html",
        {"recipe_templates": templates_list, "batches": batches,
         "now_month": today.month, "now_year": today.year,
         "alert_map": alert_map,
         "page": page, "total_pages": total_pages, "total": total},
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

    masters = db.query(models.IngredientMaster).all()
    masters_map = {m.name: {"unit_price": m.unit_price, "price_unit": m.price_unit, "category": m.category} for m in masters}

    return templates.TemplateResponse(
        request, "batch_form.html",
        {
            "tmpl": tmpl,
            "categories": CATEGORIES,
            "units": UNITS,
            "last_batch": last_batch,
            "last_ing_map": last_ing_map,
            "masters_map": masters_map,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def batch_new_custom(request: Request, db: Session = Depends(get_db)):
    masters = db.query(models.IngredientMaster).all()
    masters_map = {m.name: {"unit_price": m.unit_price, "price_unit": m.price_unit, "category": m.category} for m in masters}
    return templates.TemplateResponse(
        request, "batch_form.html",
        {"tmpl": None, "categories": CATEGORIES, "units": UNITS, "masters_map": masters_map},
    )


@router.post("/save")
async def batch_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    # --- 入力値取得・型変換（エラーハンドリング付き）---
    try:
        name = form.get("batch_name", "").strip() or "名称未設定"
        template_id = form.get("template_id")
        template_id = int(template_id) if template_id else None
        finished_weight = float(form.get("finished_weight") or 0)
        if finished_weight <= 0:
            raise ValueError("完成量は0より大きい値を入力してください")
        customer_tier = form.get("customer_tier", "standard")
        custom_gm_raw = form.get("custom_gross_margin", "")
        custom_gross_margin = float(custom_gm_raw) if custom_gm_raw else None
        notes = form.get("notes", "")
        portion_weight_raw = form.get("portion_weight", "")
        portion_weight = float(portion_weight_raw) if portion_weight_raw else None
        portion_unit = form.get("portion_unit", "g")
        waste_weight_raw = form.get("waste_weight", "")
        waste_weight = float(waste_weight_raw) if waste_weight_raw else None
        raw_weight_raw = form.get("raw_weight", "")
        raw_weight = float(raw_weight_raw) if raw_weight_raw else None
    except ValueError as e:
        return templates.TemplateResponse(
            request, "batch_form.html",
            {"tmpl": None, "categories": CATEGORIES, "units": UNITS,
             "error": f"入力値エラー: {e}"},
        )

    names = form.getlist("ing_name")
    amounts = form.getlist("ing_amount")
    units = form.getlist("ing_unit")
    unit_prices = form.getlist("ing_unit_price")
    price_units = form.getlist("ing_price_unit")
    cats = form.getlist("ing_category")

    # --- 食材パース（異種単位チェック付き）---
    ingredients = []
    unit_errors = []
    total_cost = 0.0
    for n, a, u, p, pu, c in zip(names, amounts, units, unit_prices, price_units, cats):
        if not n or not a or not p:
            continue
        try:
            amount = float(a)
            price = float(p)
        except ValueError:
            continue
        price_unit = pu if pu else "kg"
        if not _units_compatible(u, price_unit):
            unit_errors.append(f"{n}: {u} → {price_unit} は変換不可")
            continue
        converted = convert_to_price_unit(amount, u, price_unit)
        subtotal = converted * price
        total_cost += subtotal
        ingredients.append({
            "name": n, "amount": amount, "unit": u,
            "unit_price": price, "price_per": 1.0,
            "price_unit": price_unit,
            "subtotal": subtotal, "category": c,
        })

    if unit_errors:
        tmpl = db.query(models.RecipeTemplate).filter(
            models.RecipeTemplate.id == template_id).first() if template_id else None
        return templates.TemplateResponse(
            request, "batch_form.html",
            {"tmpl": tmpl, "categories": CATEGORIES, "units": UNITS,
             "error": "単位エラー: " + " / ".join(unit_errors)},
        )

    result = calc_batch(total_cost, finished_weight, customer_tier, custom_gross_margin)

    batch = models.Batch(
        template_id=template_id,
        name=name,
        finished_weight=finished_weight,
        customer_tier=customer_tier,
        custom_rate=result.pop("custom_rate"),
        notes=notes,
        waste_weight=waste_weight,
        raw_weight=raw_weight,
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



@router.get("/{batch_id}/edit", response_class=HTMLResponse)
async def batch_edit_form(request: Request, batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(models.Batch).filter(models.Batch.id == batch_id).first()
    if not batch:
        return RedirectResponse("/batch", status_code=303)
    masters = db.query(models.IngredientMaster).all()
    masters_map = {m.name: {"unit_price": m.unit_price, "price_unit": m.price_unit, "category": m.category} for m in masters}
    return templates.TemplateResponse(
        request, "batch_edit.html",
        {"batch": batch, "categories": CATEGORIES, "units": UNITS, "masters_map": masters_map},
    )


@router.post("/{batch_id}/edit")
async def batch_edit_save(request: Request, batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(models.Batch).filter(models.Batch.id == batch_id).first()
    if not batch:
        return RedirectResponse("/batch", status_code=303)

    form = await request.form()
    try:
        name = form.get("batch_name", "").strip() or "名称未設定"
        finished_weight = float(form.get("finished_weight") or 0)
        if finished_weight <= 0:
            raise ValueError("完成量は0より大きい値を入力してください")
        customer_tier = form.get("customer_tier", "standard")
        custom_gm_raw = form.get("custom_gross_margin", "")
        custom_gross_margin = float(custom_gm_raw) if custom_gm_raw else None
        notes = form.get("notes", "")
        portion_weight_raw = form.get("portion_weight", "")
        portion_weight = float(portion_weight_raw) if portion_weight_raw else None
        portion_unit = form.get("portion_unit", "g")
        waste_weight_raw = form.get("waste_weight", "")
        waste_weight = float(waste_weight_raw) if waste_weight_raw else None
        raw_weight_raw = form.get("raw_weight", "")
        raw_weight = float(raw_weight_raw) if raw_weight_raw else None
    except ValueError as e:
        masters = db.query(models.IngredientMaster).all()
        masters_map = {m.name: {"unit_price": m.unit_price, "price_unit": m.price_unit, "category": m.category} for m in masters}
        return templates.TemplateResponse(
            request, "batch_edit.html",
            {"batch": batch, "categories": CATEGORIES, "units": UNITS,
             "masters_map": masters_map, "error": f"入力値エラー: {e}"},
        )

    names = form.getlist("ing_name")
    amounts = form.getlist("ing_amount")
    units_list = form.getlist("ing_unit")
    unit_prices = form.getlist("ing_unit_price")
    price_units = form.getlist("ing_price_unit")
    cats = form.getlist("ing_category")

    ingredients = []
    unit_errors = []
    total_cost = 0.0
    for n, a, u, p, pu, c in zip(names, amounts, units_list, unit_prices, price_units, cats):
        if not n or not a or not p:
            continue
        try:
            amount = float(a)
            price = float(p)
        except ValueError:
            continue
        price_unit = pu if pu else "kg"
        if not _units_compatible(u, price_unit):
            unit_errors.append(f"{n}: {u} → {price_unit} は変換不可")
            continue
        converted = convert_to_price_unit(amount, u, price_unit)
        subtotal = converted * price
        total_cost += subtotal
        ingredients.append({
            "name": n, "amount": amount, "unit": u,
            "unit_price": price, "price_per": 1.0,
            "price_unit": price_unit,
            "subtotal": subtotal, "category": c,
        })

    if unit_errors:
        masters = db.query(models.IngredientMaster).all()
        masters_map = {m.name: {"unit_price": m.unit_price, "price_unit": m.price_unit, "category": m.category} for m in masters}
        return templates.TemplateResponse(
            request, "batch_edit.html",
            {"batch": batch, "categories": CATEGORIES, "units": UNITS,
             "masters_map": masters_map, "error": "単位エラー: " + " / ".join(unit_errors)},
        )

    result = calc_batch(total_cost, finished_weight, customer_tier, custom_gross_margin)

    batch.name = name
    batch.finished_weight = finished_weight
    batch.customer_tier = customer_tier
    batch.custom_rate = result.pop("custom_rate")
    batch.notes = notes
    batch.waste_weight = waste_weight
    batch.portion_weight = portion_weight
    batch.portion_unit = portion_unit
    batch.total_cost = result["total_cost"]
    batch.cost_per_kg = result["cost_per_kg"]
    batch.recommended_price = result["recommended_price"]
    batch.gross_margin = result["gross_margin"]

    for old in list(batch.ingredients):
        db.delete(old)
    db.flush()
    for ing in ingredients:
        db.add(models.BatchIngredient(batch_id=batch.id, **ing))

    db.commit()
    return RedirectResponse(f"/batch/{batch_id}", status_code=303)


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

    # 値上げアラート：同テンプレートの直前バッチと比較
    cost_alert = None
    if batch.template_id:
        prev_batch = (
            db.query(models.Batch)
            .filter(
                models.Batch.template_id == batch.template_id,
                models.Batch.id != batch.id,
                models.Batch.created_at < batch.created_at,
            )
            .order_by(models.Batch.created_at.desc())
            .first()
        )
        if prev_batch and prev_batch.cost_per_kg > 0:
            diff_pct = (batch.cost_per_kg - prev_batch.cost_per_kg) / prev_batch.cost_per_kg * 100
            if diff_pct > 3.0:
                cost_alert = {
                    "prev_cost_per_kg": round(prev_batch.cost_per_kg),
                    "curr_cost_per_kg": round(batch.cost_per_kg),
                    "diff": round(batch.cost_per_kg - prev_batch.cost_per_kg),
                    "diff_pct": round(diff_pct, 1),
                    "prev_date": prev_batch.created_at.strftime("%m/%d"),
                    "prev_name": prev_batch.name,
                }

    # 原価推移：同テンプレートの全バッチ（古い順）
    cost_history = []
    if batch.template_id:
        history_batches = (
            db.query(models.Batch)
            .filter(models.Batch.template_id == batch.template_id)
            .order_by(models.Batch.created_at.asc())
            .all()
        )
        cost_history = [
            {
                "date": b.created_at.strftime("%m/%d"),
                "cost_per_kg": round(b.cost_per_kg),
                "is_current": b.id == batch.id,
            }
            for b in history_batches
        ]

    return templates.TemplateResponse(
        request, "batch_result.html",
        {
            "batch": batch,
            "tier_label": tier_label,
            "by_category": by_category,
            "full_price": full_price,
            "mc": mc,
            "cost_alert": cost_alert,
            "cost_history": cost_history,
        },
    )


@router.get("/export/csv")
async def batch_export_csv(db: Session = Depends(get_db)):
    """バッチ履歴をCSVでダウンロード"""
    batches = db.query(models.Batch).order_by(models.Batch.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "日付", "バッチ名", "レシピ", "完成量(kg)", "廃棄量(kg)",
        "総原価(円)", "原価/kg(円)", "推奨価格/kg(円)", "粗利率(%)", "区分",
    ])
    for b in batches:
        if b.customer_tier == "premium":
            tier = "高粗利"
        elif b.customer_tier == "standard":
            tier = "標準粗利"
        else:
            tier = f"カスタム粗利"
        recipe = b.template.name if b.template else ""
        writer.writerow([
            b.created_at.strftime("%Y-%m-%d"),
            b.name,
            recipe,
            b.finished_weight,
            b.waste_weight or "",
            b.total_cost,
            b.cost_per_kg,
            b.recommended_price,
            b.gross_margin,
            tier,
        ])

    output.seek(0)
    # BOM付きUTF-8でExcelでも文字化けしない
    content_bytes = ("\ufeff" + output.getvalue()).encode("utf-8")
    return StreamingResponse(
        iter([content_bytes]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=batch_history.csv"},
    )


@router.get("/export/pdf")
async def batch_export_pdf(
    db: Session = Depends(get_db),
    year: int = None,
    month: int = None,
):
    """月次原価レポートをPDFでダウンロード"""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    # 日本語フォント登録
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    JP = "HeiseiKakuGo-W5"

    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month

    # 対象バッチ取得
    from sqlalchemy import extract
    batches = (
        db.query(models.Batch)
        .filter(
            extract("year", models.Batch.created_at) == year,
            extract("month", models.Batch.created_at) == month,
        )
        .order_by(models.Batch.created_at)
        .all()
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=18*mm, bottomMargin=18*mm,
    )

    def p(text, size=10, bold=False, color=colors.black, align="LEFT"):
        style = ParagraphStyle(
            "s", fontName=JP, fontSize=size, textColor=color,
            alignment={"LEFT": 0, "CENTER": 1, "RIGHT": 2}[align],
            leading=size * 1.4,
        )
        if bold:
            style.fontName = JP
        return Paragraph(text, style)

    story = []

    # タイトル
    story.append(p(f"{year}年{month}月　月次原価レポート", size=16, bold=True, align="CENTER"))
    story.append(Spacer(1, 6*mm))

    if not batches:
        story.append(p("該当月のデータがありません", size=11, color=colors.grey, align="CENTER"))
    else:
        # サマリー計算
        total_batches = len(batches)
        total_cost = sum(b.total_cost for b in batches)
        total_weight = sum(b.finished_weight for b in batches)
        avg_margin = sum(b.gross_margin for b in batches) / total_batches

        # サマリーカード
        summary_data = [
            ["仕込み回数", "総食材原価", "総完成量", "平均粗利率"],
            [
                f"{total_batches} 回",
                f"¥{total_cost:,.0f}",
                f"{total_weight:.1f} kg",
                f"{avg_margin:.1f}%",
            ],
        ]
        st = Table(summary_data, colWidths=[43*mm, 43*mm, 43*mm, 43*mm])
        st.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), JP),
            ("FONTSIZE", (0,0), (-1,0), 9),
            ("FONTSIZE", (0,1), (-1,1), 13),
            ("FONTNAME", (0,1), (-1,1), JP),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#888888")),
            ("BACKGROUND", (0,1), (-1,1), colors.HexColor("#16213e")),
            ("TEXTCOLOR", (0,1), (-1,1), colors.white),
            ("ROWBACKGROUNDS", (0,0), (-1,-1), None),
            ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#333333")),
            ("INNERGRID", (0,0), (-1,-1), 0.5, colors.HexColor("#333333")),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))
        story.append(st)
        story.append(Spacer(1, 8*mm))

        # バッチ一覧テーブル
        story.append(p("仕込み履歴", size=11, bold=True))
        story.append(Spacer(1, 3*mm))

        headers = ["日付", "仕込み名", "完成量", "食材原価", "原価/kg", "推奨価格/kg", "粗利率"]
        rows = [headers]
        for b in batches:
            tier = "高粗利" if b.customer_tier == "premium" else ("標準" if b.customer_tier == "standard" else "カスタム")
            rows.append([
                b.created_at.strftime("%m/%d"),
                b.name[:16],
                f"{b.finished_weight}kg",
                f"¥{b.total_cost:,.0f}",
                f"¥{b.cost_per_kg:,.0f}",
                f"¥{b.recommended_price:,.0f}",
                f"{b.gross_margin}%",
            ])

        col_w = [16*mm, 44*mm, 18*mm, 24*mm, 22*mm, 26*mm, 17*mm]
        t = Table(rows, colWidths=col_w, repeatRows=1)
        row_colors = []
        for i in range(1, len(rows)):
            bg = colors.HexColor("#16213e") if i % 2 == 0 else colors.HexColor("#1a1a2e")
            row_colors.append(("BACKGROUND", (0,i), (-1,i), bg))

        t.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), JP),
            ("FONTSIZE", (0,0), (-1,-1), 8.5),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0f3460")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("TEXTCOLOR", (0,1), (-1,-1), colors.HexColor("#eaeaea")),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("ALIGN", (1,1), (1,-1), "LEFT"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#333")),
            ("INNERGRID", (0,0), (-1,-1), 0.3, colors.HexColor("#2a2a4a")),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ] + row_colors))
        story.append(t)

    story.append(Spacer(1, 8*mm))
    story.append(p(f"出力日: {today.strftime('%Y年%m月%d日')}", size=8, color=colors.grey, align="RIGHT"))

    doc.build(story)
    buf.seek(0)
    filename = f"report_{year}{month:02d}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
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
    new_name = form.get("name", tmpl.name).strip()

    # M-2: 重複名チェック（自分自身は除外）
    if new_name != tmpl.name:
        dup = db.query(models.RecipeTemplate).filter(
            models.RecipeTemplate.name == new_name,
            models.RecipeTemplate.id != template_id
        ).first()
        if dup:
            return templates.TemplateResponse(
                request, "template_edit.html",
                {"tmpl": tmpl, "categories": CATEGORIES, "units": UNITS,
                 "error": f"「{new_name}」は既に存在します"},
            )
    tmpl.name = new_name
    tmpl.notes = form.get("notes", "")
    def_tier = form.get("default_customer_tier", "standard")
    def_gm_raw = form.get("default_gross_margin", "")
    tmpl.default_customer_tier = def_tier
    tmpl.default_gross_margin = float(def_gm_raw) if def_gm_raw and def_tier == "custom" else None

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

    def_tier = form.get("default_customer_tier", "standard")
    def_gm_raw = form.get("default_gross_margin", "")
    def_gm = float(def_gm_raw) if def_gm_raw else None
    tmpl = models.RecipeTemplate(
        name=name, notes=form.get("notes", ""),
        default_customer_tier=def_tier,
        default_gross_margin=def_gm if def_tier == "custom" else None,
    )
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


@router.post("/template/{template_id}/duplicate")
async def template_duplicate(template_id: int, db: Session = Depends(get_db)):
    """レシピテンプレートを複製する"""
    src = db.query(models.RecipeTemplate).filter(models.RecipeTemplate.id == template_id).first()
    if not src:
        return RedirectResponse("/batch", status_code=303)

    # 重複しない名前を生成
    base_name = src.name + " (コピー)"
    new_name = base_name
    count = 1
    while db.query(models.RecipeTemplate).filter(models.RecipeTemplate.name == new_name).first():
        count += 1
        new_name = f"{base_name}{count}"

    new_tmpl = models.RecipeTemplate(
        name=new_name,
        notes=src.notes,
        default_customer_tier=src.default_customer_tier,
        default_gross_margin=src.default_gross_margin,
    )
    db.add(new_tmpl)
    db.flush()

    for ing in src.ingredients:
        db.add(models.TemplateIngredient(
            template_id=new_tmpl.id,
            name=ing.name,
            default_amount=ing.default_amount,
            unit=ing.unit,
            category=ing.category,
        ))

    db.commit()
    return RedirectResponse(f"/batch/template/{new_tmpl.id}/edit", status_code=303)


@router.post("/template/{template_id}/delete")
async def template_delete(template_id: int, db: Session = Depends(get_db)):
    tmpl = db.query(models.RecipeTemplate).filter(models.RecipeTemplate.id == template_id).first()
    if tmpl:
        db.delete(tmpl)
        db.commit()
    return RedirectResponse("/batch", status_code=303)
