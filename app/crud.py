from sqlalchemy.orm import Session
from app import models, schemas


def save_recipe(db: Session, data: schemas.RecipeSave, result: dict) -> models.Recipe:
    recipe = models.Recipe(
        name=data.name,
        raw_weight=data.raw_weight,
        raw_price=data.raw_price,
        finished_weight=data.finished_weight,
        customer_tier=data.customer_tier,
        **result,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


def list_recipes(db: Session) -> list[models.Recipe]:
    return db.query(models.Recipe).order_by(models.Recipe.created_at.desc()).all()


def get_recipe(db: Session, recipe_id: int) -> models.Recipe | None:
    return db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()


def delete_recipe(db: Session, recipe_id: int) -> bool:
    recipe = get_recipe(db, recipe_id)
    if not recipe:
        return False
    db.delete(recipe)
    db.commit()
    return True
