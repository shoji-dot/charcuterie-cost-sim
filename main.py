from fastapi import FastAPI
from sqlalchemy import text
from app.database import Base, engine, SessionLocal
from app.routers import calculator, pig, batch, settings, ingredients

Base.metadata.create_all(bind=engine)

_migrations = [
    "ALTER TABLE batch_ingredients ADD COLUMN price_per FLOAT DEFAULT 1",
    "ALTER TABLE batches ADD COLUMN portion_weight FLOAT",
    "ALTER TABLE batches ADD COLUMN portion_unit VARCHAR DEFAULT 'g'",
    "ALTER TABLE batch_ingredients ADD COLUMN price_unit VARCHAR DEFAULT 'kg'",
    "ALTER TABLE batches ADD COLUMN custom_rate FLOAT",
    "ALTER TABLE cuts ADD COLUMN gross_margin FLOAT",
    "ALTER TABLE cuts ADD COLUMN custom_gross_margin FLOAT",
    "ALTER TABLE recipe_templates ADD COLUMN default_customer_tier VARCHAR DEFAULT 'standard'",
    "ALTER TABLE recipe_templates ADD COLUMN default_gross_margin FLOAT",
    "ALTER TABLE batches ADD COLUMN waste_weight FLOAT",
    "ALTER TABLE batches ADD COLUMN raw_weight FLOAT",
]
with engine.connect() as conn:
    for sql in _migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
        except Exception:
            pass

from app.seed_recipes import seed
_db = SessionLocal()
try:
    seed(_db)
finally:
    _db.close()

app = FastAPI(title="Cost Simulator")
app.include_router(calculator.router)
app.include_router(pig.router)
app.include_router(batch.router)
app.include_router(settings.router)
app.include_router(ingredients.router)
