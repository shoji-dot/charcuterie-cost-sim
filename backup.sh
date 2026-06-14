#!/bin/bash
# ================================================================
# シャルキュトリー原価シュミレーター バックアップスクリプト
# 使い方:
#   ローカル: bash backup.sh
#   Railway:  railway run bash backup.sh
# ================================================================

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DATE=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[ERROR] DATABASE_URL が設定されていません"
  exit 1
fi

if echo "$DATABASE_URL" | grep -q "postgresql"; then
  # PostgreSQL (Railway 本番)
  OUTFILE="$BACKUP_DIR/backup_${DATE}.sql"
  echo "[INFO] pg_dump 開始: $OUTFILE"
  pg_dump "$DATABASE_URL" \
    --no-password \
    --format=plain \
    --no-owner \
    --no-acl \
    > "$OUTFILE"
  gzip "$OUTFILE"
  echo "[INFO] バックアップ完了: ${OUTFILE}.gz"
elif echo "$DATABASE_URL" | grep -q "sqlite"; then
  # SQLite (ローカル)
  DB_PATH=$(echo "$DATABASE_URL" | sed 's|sqlite:///||')
  OUTFILE="$BACKUP_DIR/backup_${DATE}.db"
  echo "[INFO] SQLite コピー: $DB_PATH -> $OUTFILE"
  cp "$DB_PATH" "$OUTFILE"
  echo "[INFO] バックアップ完了: $OUTFILE"
else
  echo "[ERROR] 対応していない DATABASE_URL フォーマットです"
  exit 1
fi

# 30日以上古いバックアップを削除
find "$BACKUP_DIR" -name "backup_*.sql.gz" -mtime +30 -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "backup_*.db" -mtime +30 -delete 2>/dev/null || true
echo "[INFO] 古いバックアップを整理しました"
