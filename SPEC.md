# シャルキュトリー原価シミュレーター — 仕様書

最終更新: 2026-06-11

---

## 1. アプリ概要

シャルキュトリー（加工肉）の製造原価を計算・記録・分析する業務アプリ。
FastAPI + SQLite + Jinja2 によるサーバーサイドレンダリング。
ローカル環境またはRailway（本番）で動作し、iPhoneのPWAとして利用可能。

---

## 2. 技術スタック

| 項目 | 内容 |
|------|------|
| バックエンド | FastAPI (Python) |
| ORM | SQLAlchemy |
| DB | SQLite（ローカル）/ PostgreSQL（Railway本番）|
| テンプレート | Jinja2 |
| スタイル | インラインCSS（ダークテーマ） |
| PDF出力 | ReportLab |
| フロントJS | バニラJS（フレームワークなし）|
| デプロイ | Railway |

---

## 3. 画面一覧とURL

| 画面 | URL | 説明 |
|------|-----|------|
| ホーム | `GET /` | 月次サマリー・最近の仕込み・ナビ |
| シンプル計算 | `GET /calc` | 単品の原価計算（レシピ保存なし） |
| 計算結果（単品）| `GET /recipe/{id}` | 保存済み単品レシピの結果 |
| レシピ計算一覧 | `GET /batch` | レシピテンプレート一覧 + 計算履歴 |
| 仕込みフォーム | `GET /batch/new/{template_id}` | テンプレートから計算入力 |
| 仕込みフォーム（空）| `GET /batch/new` | 指定なし計算入力 |
| 仕込み結果詳細 | `GET /batch/{id}` | 計算結果・原価推移グラフ・逆引き計算 |
| 仕込み編集 | `GET /batch/{id}/edit` | 計算内容の修正 |
| レシピテンプレート新規 | `GET /batch/template/new` | テンプレート作成 |
| レシピテンプレート編集 | `GET /batch/template/{id}/edit` | テンプレート編集 |
| ランキング | `GET /batch/ranking` | レシピ別粗利ランキング |
| 豚一頭管理一覧 | `GET /pig` | 登録済み丸豚の一覧 |
| 豚一頭管理新規 | `GET /pig/new` | 丸豚の登録 |
| 豚一頭管理詳細 | `GET /pig/{id}` | 部位別原価・収支サマリー |
| 固定費設定 | `GET /settings` | 月次固定費・経営設定 |
| 食材マスター | `GET /ingredients` | よく使う食材の単価マスター管理 |

---

## 4. データモデル

### Recipe（単品計算の保存履歴）
| カラム | 型 | 説明 |
|--------|----|------|
| id | Integer PK | |
| name | String | レシピ名 |
| raw_weight | Float | 仕込み前重量(kg) |
| raw_price | Float | 仕込み前総額(円) |
| finished_weight | Float | 完成量(kg) |
| customer_tier | String | premium / standard / custom |
| yield_rate | Float | 歩留まり率(%) |
| cost_per_kg | Float | 原価/kg |
| recommended_price | Float | 推奨販売価格/kg |
| gross_margin | Float | 粗利率(%) |
| created_at | DateTime | |

### WholePig（丸豚）
| カラム | 型 | 説明 |
|--------|----|------|
| id | Integer PK | |
| name | String | 管理名 |
| carcass_weight | Float | 枝肉重量(kg) |
| purchase_price | Float | 仕入れ値(円) |
| created_at | DateTime | |

### Cut（部位）
| カラム | 型 | 説明 |
|--------|----|------|
| id | Integer PK | |
| pig_id | FK→WholePig | |
| name | String | 部位名 |
| raw_weight | Float | 生重量(kg) |
| finished_weight | Float | 完成量(kg) |
| customer_tier | String | premium / standard / custom |
| custom_gross_margin | Float? | カスタム粗利率(%) |
| unit_cost | Float | 部位コスト(円) |
| cost_per_kg | Float | 原価/kg |
| recommended_price | Float | 推奨価格/kg |
| yield_rate | Float | 歩留まり率(%) |
| gross_margin | Float | 粗利率(%) |
| target_revenue | Float | 目標売上(円) |

### RecipeTemplate（レシピテンプレート）
| カラム | 型 | 説明 |
|--------|----|------|
| id | Integer PK | |
| name | String UNIQUE | レシピ名 |
| notes | Text? | 備考 |
| default_customer_tier | String | デフォルト粗利区分 |
| default_gross_margin | Float? | デフォルトカスタム粗利率 |

### TemplateIngredient（テンプレートの食材）
| カラム | 型 | 説明 |
|--------|----|------|
| id | Integer PK | |
| template_id | FK→RecipeTemplate | |
| name | String | 食材名 |
| default_amount | Float | デフォルト量 |
| unit | String | 単位(kg/g/L等) |
| category | String | カテゴリ |

### Batch（仕込み記録）
| カラム | 型 | 説明 |
|--------|----|------|
| id | Integer PK | |
| template_id | FK→RecipeTemplate? | 使用テンプレート |
| name | String | 仕込み名 |
| finished_weight | Float | 完成量(kg) |
| raw_weight | Float? | 仕込み前重量(kg) |
| waste_weight | Float? | 廃棄量(kg) |
| customer_tier | String | premium / standard / custom |
| custom_rate | Float? | カスタム時の原価率(0.0〜1.0) |
| total_cost | Float | 食材原価合計(円) |
| cost_per_kg | Float | 原価/kg |
| recommended_price | Float | 推奨販売価格/kg |
| gross_margin | Float | 粗利率(%) |
| portion_weight | Float? | 1食あたり重量 |
| portion_unit | String | g / kg |
| notes | Text? | 備考 |
| created_at | DateTime | |

### BatchIngredient（仕込みの食材明細）
| カラム | 型 | 説明 |
|--------|----|------|
| id | Integer PK | |
| batch_id | FK→Batch | |
| name | String | 食材名 |
| amount | Float | 使用量 |
| unit | String | 単位 |
| unit_price | Float | 単価 |
| price_per | Float | 単価の基準量（常に1.0）|
| price_unit | String | 単価の単位(kg/g等) |
| subtotal | Float | 小計(円) |
| category | String | カテゴリ |

### MonthlyCost（月次固定費・経営設定）
| カラム | 型 | 説明 |
|--------|----|------|
| id | Integer PK | |
| year / month | Integer | 対象年月 |
| rent | Float | 家賃(円) |
| labor | Float | 人件費(円) |
| utilities | Float | 光熱費(円) |
| supplies | Float | 消耗品費(円) |
| other | Float | その他固定費(円) |
| production_kg | Float | 月間生産量(kg) |
| target_profit_rate | Float | 目標利益率(0.0〜1.0) |
| takeout_packaging | Float | テイクアウト包材費(円) |
| takeout_unit_weight | Float | テイクアウト1食重量(kg) |
| eatin_multiplier | Float | イートイン価格倍率 |
| notes | Text? | 備考 |

### IngredientMaster（食材マスター）
| カラム | 型 | 説明 |
|--------|----|------|
| id | Integer PK | |
| name | String UNIQUE | 食材名 |
| unit_price | Float | 単価 |
| price_unit | String | 単価単位(kg/g等) |
| category | String | カテゴリ |
| updated_at | DateTime | |

---

## 5. 原価計算ロジック

### 粗利区分と原価率

| 区分 | customer_tier | 原価率 | 粗利率 |
|------|--------------|--------|--------|
| 高粗利 | premium | 25% | 75% |
| 標準粗利 | standard | 35% | 65% |
| カスタム | custom | (100-指定粗利率)% | 指定値 |

### 計算式

```
原価/kg       = 食材原価合計 ÷ 完成量(kg)
推奨販売価格/kg = 原価/kg ÷ 原価率
粗利率        = (1 - 原価率) × 100
歩留まり率     = 完成量 ÷ 仕込み前重量 × 100
```

### 丸豚の部位原価配分

```
部位コスト = 丸豚仕入れ値 × (部位生重量 ÷ 枝肉重量)
原価/kg    = 部位コスト ÷ 部位完成量
```

### 固定費込み販売価格（バッチ詳細で参考表示）

```
固定費/kg      = 月間固定費合計 ÷ 月間生産量
全コスト/kg    = 食材原価/kg + 固定費/kg
推奨価格(全込) = 全コスト/kg ÷ (1 - 目標利益率)
テイクアウト/食 = 推奨価格(全込) × 1食重量 + 包材費
イートイン/食  = テイクアウト/食 × イートイン倍率
```

---

## 6. 機能一覧

### 6-1. レシピ計算（Batch）

- レシピテンプレートから仕込みフォームを呼び出し、食材・量・単価を入力して計算
- 食材カテゴリ: 肉/野菜/調味料/油脂/乳製品/豆・穀物/その他
- 単位: kg/g/L/ml/個/枚/本/束/缶（異種単位組み合わせ時はエラー）
- 食材マスターから単価自動補完
- 前回バッチの食材・量を初期値として表示
- 廃棄ロス補正: 仕込み前重量・廃棄量を入力→実歩留まり率をリアルタイム表示（JS）
- 計算結果: 原価/kg・推奨価格・粗利率・食材明細
- 販売価格の逆引き計算: 目標価格を入力→粗利率を即時表示（JS、保存なし）
- 原価推移グラフ: 同テンプレートの過去バッチをSVGグラフで表示
- 値上げアラート: 前回同テンプレートバッチと比較し3%超の値上がりで⚠バッジ表示
- バッチ一覧: 20件/ページのページネーション
- CSV出力: 全バッチ履歴（BOM付きUTF-8、Excel対応）
- PDF出力: 月次原価レポート（年月選択、ReportLab）

### 6-2. レシピテンプレート管理

- 新規作成・編集・削除
- 複製（「コピー」サフィックスで重複名回避）
- デフォルト粗利区分の設定

### 6-3. 粗利ランキング

- 全バッチをレシピ名でグループ集計
- 粗利額順/粗利率順のトグル切り替え（URLパラメータ `?sort=profit|margin`）
- 表示項目: 総粗利額・平均粗利率・粗利/kg・回数・総重量

### 6-4. 豚一頭管理（WholePig）

- 丸豚（枝肉重量・仕入れ値）を登録
- 部位ごとに生重量・完成量・粗利区分を入力→原価自動計算
- 部位別標準歩留まりのベンチマーク値を表示（ヒレ90%/ロース80%等）
- 部位の粗利設定をインライン編集・再計算（✏ボタン）
- 全体収支サマリー: 目標売上合計・仕入れ値・推定粗利・未割当重量

### 6-5. 固定費・経営設定

- 年月単位で家賃・人件費・光熱費・消耗品・その他を登録
- 月間生産量・目標利益率・テイクアウト設定（包材費・1食重量・イートイン倍率）
- 直近6ヶ月の履歴表示・削除
- 設定済みの場合、ホームに固定費/kg サマリーを表示

### 6-6. 食材マスター

- 食材名・単価・単価単位・カテゴリを登録・編集・削除（UPSERT）
- 仕込みフォームで食材名入力時に自動補完

### 6-7. ホームダッシュボード

- 当月仕込み実績: 食材原価合計・推定粗利合計・最高原価レシピ
- 最近の仕込み（直近3件）
- 固定費設定バナー（未設定時は警告、設定済みは固定費/kgを表示）
- 単品計算の保存履歴

### 6-8. シンプル単品計算

- 仕込み前重量・仕入れ値・完成量・粗利区分を入力して即時計算
- 結果をレシピとして保存可能

---

## 7. ファイル構成

```
app/
  models.py          # SQLAlchemyモデル定義（全テーブル）
  calculator.py      # 原価計算ロジック（純粋関数）
  database.py        # DB接続・セッション管理
  crud.py            # Recipe CRUD（単品計算用）
  schemas.py         # Pydanticスキーマ（単品計算用）
  seed_recipes.py    # 初期データ投入スクリプト
  routers/
    calculator.py    # / /calc /save /delete /recipe ルート
    batch.py         # /batch/* ルート（レシピ計算・テンプレート）
    pig.py           # /pig/* ルート（丸豚管理）
    settings.py      # /settings/* ルート（固定費設定）
    ingredients.py   # /ingredients/* ルート（食材マスター）
  templates/
    base.html        # 共通レイアウト・ナビ
    index.html       # ホーム
    input.html       # シンプル計算フォーム
    result.html      # シンプル計算結果
    batch_list.html  # レシピ計算一覧
    batch_form.html  # 仕込みフォーム
    batch_result.html# 仕込み結果詳細
    batch_edit.html  # 仕込み編集
    batch_ranking.html # ランキング
    template_edit.html # テンプレート編集
    pig_list.html    # 丸豚一覧
    pig_new.html     # 丸豚登録
    pig_detail.html  # 丸豚詳細
    settings.html    # 固定費設定
    ingredients.html # 食材マスター
main.py              # アプリエントリーポイント・DBマイグレーション
```

---

## 8. DBマイグレーション方針

`main.py` 起動時に `_migrations` リストの `ALTER TABLE` を `try/except` で実行。
既にカラムが存在する場合はエラーを無視してスキップ。

---

## 9. 単位変換ルール

同一グループ内のみ変換可能。異種グループはエラー。

| グループ | 単位 |
|----------|------|
| 重量 | kg, g |
| 容量 | L, ml |
| 個数 | 個, 枚, 本, 束, 缶 |

変換倍率: kg↔g (×1000/÷1000)、L↔ml (×1000/÷1000)

---

## 10. CSV / PDF 出力仕様

### CSV（`GET /batch/export/csv`）
- 全バッチ履歴（作成日時降順）
- BOM付きUTF-8（Excel文字化け対策）
- カラム: 日付・バッチ名・レシピ・完成量・廃棄量・総原価・原価/kg・推奨価格/kg・粗利率・区分

### PDF（`GET /batch/export/pdf?year=YYYY&month=MM`）
- 指定年月のバッチ一覧レポート
- ReportLab + HeiseiKakuGo-W5フォント（日本語対応）
- サマリーカード（回数・総原価・総重量・平均粗利率）＋バッチ一覧テーブル

---

## 11. 開発・運用メモ

- **OneDriveの日本語パス問題**: Bashでの直接ファイル操作が截断されることがある。Pythonファイルの編集は `python3 -c` による文字列置換を使用。
- **gitのindex.lockエラー**: PowerShellで `Remove-Item .git\index.lock -ErrorAction SilentlyContinue` を実行してから `git add/commit/push`。
- **Railway本番DB**: PostgreSQL（環境変数 `DATABASE_URL` で切り替え）。
- **PWA対応**: `base.html` に `<meta name="viewport">` 設定済み。
