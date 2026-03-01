import streamlit as st
import sqlite3
import sys
import os
from openai import OpenAI

# Добавляем текущую директорию в путь для импорта локальных модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

st.set_page_config(
    page_title="B2B Unit Economics Service",
    layout="wide",
    page_icon="📦"
)

DB_PATH = "products_storage.db"

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE,
            name TEXT,
            length_cm REAL,
            width_cm REAL,
            height_cm REAL,
            weight_kg REAL,
            cost REAL DEFAULT 0
        )
    """)
    
    cols = [r[1] for r in c.execute("PRAGMA table_info(products)")]
    if "cost" not in cols:
        c.execute("ALTER TABLE products ADD COLUMN cost REAL DEFAULT 0")
        
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_cache (
            name TEXT,
            client TEXT,
            category TEXT,
            PRIMARY KEY (name, client)
        )
    """)
    conn.commit()
    return conn

def normalize_value(raw, unit):
    try:
        v = float(str(raw).replace(",", ".").strip())
    except (ValueError, TypeError):
        return 0.0
    u = str(unit).strip().lower() if unit else ""
    if u in ("мм", "mm"): return v / 10.0
    if u in ("г", "g", "гр", "gr"): return v / 1000.0
    return v

def get_ai_category(name: str, categories: list, conn, client_key: str) -> str:
    c = conn.cursor()
    row = c.execute(
        "SELECT category FROM ai_cache WHERE name=? AND client=?", 
        (name, client_key)
    ).fetchone()
    if row:
        return row[0]
    
    api_key = st.session_state.get("openai_key", "")
    if not api_key or not categories:
        return categories[0] if categories else "Неизвестно"
        
    try:
        client = OpenAI(api_key=api_key)
        cats_str = "\
".join(f"- {cat}" for cat in categories)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    f"Ты классификатор товаров для маркетплейса {client_key}. "
                    "Выбери ОДНУ категорию из списка. Ответь ТОЛЬКО её названием."
                )},
                {"role": "user", "content": f"Товар: {name}\
Категории:\
{cats_str}"}
            ],
            max_tokens=60,
            temperature=0
        )
        category = resp.choices[0].message.content.strip()
        if category not in categories:
            category = categories[0]
    except Exception:
        category = categories[0] if categories else "Неизвестно"
        
    c.execute(
        "INSERT OR REPLACE INTO ai_cache (name, client, category) VALUES (?,?,?)",
        (name, client_key, category)
    )
    conn.commit()
    return category

def calc_tax(revenue: float, cost_total: float, regime: str):
    profit_before = revenue - cost_total
    rates = {
        "ОСНО (25% от прибыли)": ("profit", 0.25),
        "УСН Доходы (6%)": ("revenue", 0.06),
        "УСН Доходы-Расходы (15%)": ("profit", 0.15),
        "АУСН (8% от дохода)": ("revenue", 0.08),
        "УСН с НДС 5%": ("revenue", 0.05),
        "УСН с НДС 7%": ("revenue", 0.07),
    }
    mode, rate = rates.get(regime, ("profit", 0.0))
    if mode == "revenue":
        tax = revenue * rate
    else:
        tax = max(profit_before * rate, 0)
    profit_after = profit_before - tax
    margin_after = (profit_after / revenue * 100) if revenue > 0 else 0
    return round(tax, 2), round(profit_after, 2), round(margin_after, 1)

# ── Инициализация БД ──────────────────────────────────────────────
conn = init_db()

# ── Обработка API ключа (Secrets / Session State) ─────────────────
if "openai_key" not in st.session_state:
    secret_key = st.secrets.get("OPENAI_API_KEY")
    if secret_key:
        st.session_state["openai_key"] = secret_key
    else:
        st.session_state["openai_key"] = ""

# ── Выбор раздела ─────────────────────────────────────────────
st.markdown("### 🛠️ Управление сервисом")
client_choice = st.selectbox(
    "Выберите клиента или раздел",
    ["Ozon (FBO/FBS)", "PIM (единая база)", "М.Видео (FBS)", "Лемана Про (FBS)", "Ситилинк (FBS)", "Спортмастер (FBS)"],
    key="client_choice"
)

# ── Боковая панель ────────────────────────────────────────
if "PIM" not in client_choice:
    with st.sidebar:
        st.title("📦 Unit Economics")
        st.divider()
        st.subheader("⚙️ Параметры расчёта")
        tax_regime = st.selectbox(
            "Система налогообложения",
            [
                "ОСНО (25% от прибыли)", "УСН Доходы (6%)", "УСН Доходы-Расходы (15%)", 
                "АУСН (8% от дохода)", "УСН с НДС 5%", "УСН с НДС 7%"
            ],
            key="tax_regime"
        )
        params = {"tax_regime": tax_regime}

# ── Рендеринг ──────────────────────────────────────────────
if client_choice == "Ozon (FBO/FBS)":
    import ozon
    ozon.render(conn, get_ai_category, normalize_value, calc_tax, params)
elif client_choice == "PIM (единая база)":
    import pim
    pim.render(conn, normalize_value, st.session_state.get("openai_key", ""))
elif client_choice == "М.Видео (FBS)":
    import mvideo
    mvideo.render(conn, get_ai_category, normalize_value, calc_tax, params)
elif client_choice == "Лемана Про (FBS)":
    import lemanpro_fbs
    lemanpro_fbs.render(conn, get_ai_category, normalize_value, calc_tax, params)
elif client_choice == "Ситилинк (FBS)":
    import citilink
    citilink.render(conn, get_ai_category, normalize_value, calc_tax, params)
elif client_choice == "Спортмастер (FBS)":
    import sportmaster_fbs
    sportmaster_fbs.render(conn, get_ai_category, normalize_value, calc_tax, params)
else:
    st.info("🔧 Раздел находится в разработке.")
