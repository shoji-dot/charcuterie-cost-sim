# シャルキュトリー原価シュミレーター 監査レポート
**監査日**: 2026-06-14  
**対象**: main.py / app/ 全体（models, routers, templates, calculator）

---

## 総合評価: 61 / 100

基本機能は動作するが、認証・CSRF・データ永続性に重大リスクあり。  
本番運用前にCritical/Highを全修正すること。

---

## Critical（即修正）

### C-1: SQLiteのデータ消失リスク
**場所**: `app/database.py` L8  
`DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")`

Railway上で `DATABASE_URL` が未設定のままだと `dev.db` (エフェメラルディスク) に書き込む。  
**デプロイのたびにデータがリセットされる。**

修正:
```python
# DATABASE_URL が未設定なら起動を止める
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required. Set it in Railway environment variables.")
```
Railway の Variables タブで `DATABASE_URL` を PostgreSQL サービスにリンクすること。

---

### C-2: マイグレーション管理がない
**場所**: `main.py` L8-27

起動時に生 SQL を `try/except` でスルーする方式は、失敗を検知できない。  
スキーマ変更のたびに手動追記が必要で、本番 DB がどのバージョンか追跡できない。

修正: **Alembic** を導入し、バージョン管理されたマイグレーションを使う。
```
pip install alembic
alembic init migrations
# 以後 alembic revision --autogenerate / alembic upgrade head
```

---

### C-3: 認証が一切ない
**場所**: 全ルーター

URLを知っていれば誰でも全データを閲覧・編集・削除できる。  
社内利用でも誤操作・意図しないアクセスのリスクがある。

修正候補（シンプル順）:
1. Basic 認証（nginx / Railway のアクセス制限）
2. `fastapi-users` によるセッション認証
3. VPN 経由アクセス限定

---

### C-4: CSRF 保護がない
**場所**: 全 POST フォーム

フォームに CSRF トークンがない。外部サイトから任意の POST を送られる可能性がある。

修正:
```python
# starlette-csrf ミドルウェアを追加
pip install starlette-csrf
from starlette_csrf import CSRFMiddleware
app.add_middleware(CSRFMiddleware, secret="<random-secret>")
```
テンプレートに `<input type="hidden" name="csrftoken" value="{{ request.state.csrftoken }}">` を追加。

---

## High（本番前修正推奨）

### H-1: バックアップが存在しない
Railway PostgreSQL を使っている場合でも、自動バックアップが有効か確認すること。  
Railway の Backups タブ（有料プランのみ）を確認するか、pg_dump を定期実行するスクリプトを用意。

```bash
# 例: Railway CLI で pg_dump
railway run pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql
```

---

### H-2: 食材削除でバッチ履歴の整合性が壊れる
**場所**: `app/routers/ingredients.py` `/delete/{master_id}`

食材マスターを削除しても、既存の `BatchIngredient` に `master_id` の外部キーがない（名前紐付け）。  
単価同期も削除後は機能しなくなる。  
→ 食材マスターは「論理削除」（is_active フラグ）にすべき。

---

### H-3: バッチ削除が即時・復元不可
**場所**: `batch.py` `POST /{batch_id}/delete`

確認ダイアログなし（HTML 側に `onsubmit="return confirm()"` もない）。  
削除後の復元手段がない。  
→ 確認モーダルの追加、またはソフトデリート（`deleted_at` カラム）を実装。

---

### H-4: `reportlab` が requirements.txt に含まれているか不明
**場所**: `batch.py` PDF 出力ルーター

```python
from reportlab.lib.pagesizes import A4  # 実行時インポート
```
`requirements.txt` に `reportlab` がなければ Railway でクラッシュする。確認・追記すること。

---

### H-5: price_per フィールドの冗長・混乱
**場所**: `models.py` `BatchIngredient` / `batch.py` L255

`unit_price` と `price_per` が併存し、`price_per=1.0` がハードコードされている。  
今回の price sync でも `bi.price_per = unit_price` と設定しており意味が曖昧。  
→ `price_per` を廃止し `unit_price` に一本化すること。

---

## Medium（改善推奨）

### M-1: ログ出力がない
FastAPI のデフォルトログのみ。エラー発生時のデバッグが困難。
```python
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```
エラーハンドラーで `logger.exception()` を呼ぶ。

---

### M-2: 404 / 500 カスタムエラーページがない
FastAPI のデフォルト JSON レスポンスが返る。PWA として利用する場合に UX が悪い。
```python
@app.exception_handler(404)
async def not_found(req, exc):
    return templates.TemplateResponse(req, "404.html", status_code=404)
```

---

### M-3: SQLite 用 `check_same_thread` 設定漏れ
**場所**: `app/database.py`

SQLite をローカル開発で使う場合、FastAPI のマルチスレッド環境でエラーが出ることがある。
```python
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)
```

---

### M-4: シードデータが毎回上書き実行される
**場所**: `main.py` L29-33

`seed(_db)` は起動のたびに実行される。現状は同名チェックで冪等だが、  
シードデータの単価を手動修正してもすぐ上書きされる可能性はない（同名チェックあり）。  
ただし起動時間が長くなる。フラグ管理（`app_settings` テーブルに `seeded` フラグ）を推奨。

---

### M-5: 食材マスター一覧にページネーションがない
70件超のシードデータ登録後、一覧ページが縦長になる。  
カテゴリ折りたたみまたは仮想スクロールを検討。

---

### M-6: `template_edit.html` に masters_map が渡されていない
**場所**: `batch.py` L701-708

テンプレート編集画面では食材マスターから単価を引けない。  
`GET /template/{id}/edit` に `masters_map` を渡すことで改善できる。

---

## Low（余裕があれば）

- **テストがない**: pytest + TestClient でルーターの結合テストを追加
- **型アノテーションの不整合**: `crud.py` で `models.Recipe | None` など Python 3.10+ 型が混在
- **原価率がハードコード**: `calculator.py` の 0.25 / 0.35 を `settings` テーブルから取得できると柔軟
- **CSV 出力の文字コード**: BOM 付き UTF-8 は対応済みで良い点だが、Mac Excel との互換テスト推奨
- **モバイル: input type=number の小数点**: iOS Safari では `step="0.001"` が `.` か `,` かロケール依存

---

## 良い点

- `get_db()` で `try/except/finally` によるロールバック・クローズ設計が適切
- Jinja2 の `{{ }}` による自動エスケープで HTML インジェクションを防いでいる
- モーダル内の食材名を `textContent` でセット（今回修正済み）→ XSS 防止
- `convert_to_price_unit` で単位換算を計算ロジックに分離している
- CSV エクスポート・PDF エクスポートが実装済み
- 値上げアラート機能（前回バッチとの原価差異）が業務に直結している
- 食材マスター単価変更時に BatchIngredient を同期する仕組みを実装済み（今回追加）

---

## 改善ロードマップ

### 今週
1. **C-4** CSRF ミドルウェア追加
2. **H-3** バッチ削除確認ダイアログ追加（1行の JS 修正）
3. **H-4** `requirements.txt` に `reportlab` があることを確認
4. **M-3** SQLite の `check_same_thread` 設定

### 今月
1. **C-3** Basic 認証またはアクセス制限の実装
2. **C-1** Railway で `DATABASE_URL` が PostgreSQL に正しくリンクされているか確認
3. **H-1** pg_dump バックアップスクリプト作成・定期実行
4. **H-2** 食材マスターのソフトデリート実装
5. **M-1** ロギング追加

### 3か月以内
1. **C-2** Alembic 導入・マイグレーション管理
2. **M-6** テンプレート編集に masters_map を渡す
3. **H-5** `price_per` フィールド廃止・統一
4. テスト追加（pytest）
5. 原価率の設定画面化
