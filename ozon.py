# ozon.py
import streamlit as st
import pandas as pd
import requests

# 1. СПРАВОЧНИК КОМИССИЙ (из Вашего Excel / API)
# С 6 апреля 2026 тарифы могут достигать 50%+
CATEGORY_COMMISSIONS = {
    "Электроника": 15.0,
    "Смартфоны": 10.0,
    "Одежда и обувь": 25.0,
    "Спорт и отдых": 15.0,
    "Товары для детей": 18.0,
    "Прочее": 20.0,
}

def get_logistics_fbo(vol_liters, weight_kg, days=45):
    """Расчет логистики Ozon FBO с учетом хранения 45 дней"""
    processing = 30.0
    delivery = 50.0 + max(0, weight_kg - 1) * 5.0 + max(0, vol_liters - 5) * 10.0
    
    # Хранение: 14 дней бесплатно, далее допустим 5 руб/литр/день
    storage_days = max(0, days - 14)
    storage_cost = storage_days * vol_liters * 5.0
    
    return processing, delivery, storage_cost

def get_logistics_fbs(vol_liters, weight_kg):
    """Расчет логистики Ozon FBS"""
    processing = 25.0
    delivery = 60.0 + max(0, weight_kg - 1) * 7.0 + max(0, vol_liters - 5) * 12.0
    return processing, delivery, 0.0

def render(conn, get_ai_category, normalize_value, calc_tax, params: dict):
    st.header("Ozon — Расчёт целевой цены (Юнит-экономика)")
    
    # ПАРАМЕТРЫ МЕНЕДЖЕРА (Правый блок)
    with st.sidebar:
        st.divider()
        st.subheader("📊 Параметры менеджера")
        model = st.radio("Модель работы", ["FBO", "FBS"], index=0)
        buyout_rate = st.slider("Выкупаемость, %", 10, 100, 85) / 100.0
        defect_rate = st.slider("Брак, %", 0, 20, 2) / 100.0
        adv_rate = st.slider("Реклама, %", 0, 50, 10) / 100.0
        boost_rate = st.slider("Буст продаж, %", 0, 20, 5) / 100.0
        target_m = st.slider("Целевая маржа, %", 0, 50, 20) / 100.0
        storage_days = st.number_input("Срок хранения (дней)", 0, 365, 45)

    # БЛОК 1. Каталог товаров (Единая база ПИМ)
    st.subheader("1. Выбор товара из PIM")
    all_products = conn.execute(
        "SELECT sku, name, length_cm, width_cm, height_cm, weight_kg, cost FROM products"
    ).fetchall()
    
    if not all_products:
        st.warning("Каталог PIM пуст. Добавьте товары в разделе PIM.")
        return

    df_pim = pd.DataFrame(all_products, columns=["SKU", "Название", "Д, см", "Ш, см", "В, см", "Вес, кг", "Себестоимость"])
    selected_sku = st.selectbox("Выберите SKU для расчета", df_pim["SKU"].tolist())
    product = df_pim[df_pim["SKU"] == selected_sku].iloc[0]

    # БЛОК 2. Расчет
    if st.button("🚀 Рассчитать цену на полку"):
        l, w, h, wt, cost = product["Д, см"], product["Ш, см"], product["В, см"], product["Вес, кг"], product["Себестоимость"]
        vol_l = (l * w * h) / 1000.0
        
        # 1. Логистика
        if model == "FBO":
            proc, deliv, stor = get_logistics_fbo(vol_l, wt, storage_days)
        else:
            proc, deliv, stor = get_logistics_fbs(vol_l, wt)
            
        logistics_fix = proc + deliv + stor
        
        # 2. Комиссия (AI или ручной выбор)
        cat_list = list(CATEGORY_COMMISSIONS.keys())
        category = get_ai_category(product["Название"], cat_list, conn, "ozon")
        comm_rate = CATEGORY_COMMISSIONS.get(category, 20.0) / 100.0
        
        # 3. ФОРМУЛА ОБРАТНОГО РАСЧЕТА
        # Чистая доля от цены = (1-комиссия)*(1-маркетинг)*(1-буст)*(1-маржа)*выкупаемость*(1-брак)
        # Упрощенная сумма процентных расходов
        total_pct = comm_rate + adv_rate + boost_rate + target_m
        
        denom = (1 - total_pct) * buyout_rate * (1 - defect_rate)
        
        if denom > 0:
            price_shelf = (cost + logistics_fix) / denom
            
            # Детализация
            st.success(f"### Рекомендуемая цена на полке: {round(price_shelf, 0)} ₽")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Прибыль (целевая)", f"{round(price_shelf * target_m, 0)} ₽")
                st.write(f"Логистика и хранение: {round(logistics_fix, 0)} ₽")
            with col2:
                st.write(f"Комиссия ({int(comm_rate*100)}%): {round(price_shelf * comm_rate, 0)} ₽")
                st.write(f"Реклама + Буст: {round(price_shelf * (adv_rate + boost_rate), 0)} ₽")
            with col3:
                st.write(f"Ожидаемый невыкуп/брак: {round(price_shelf * (1-buyout_rate + defect_rate), 0)} ₽")
        else:
            st.error("Ошибка расчета: слишком высокие процентные расходы. Снизьте маржу или расходы на рекламу.")
