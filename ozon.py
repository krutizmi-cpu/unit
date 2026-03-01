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
    
    # Извлекаем параметры из sidebar (переданы из app.py)
    buyout_rate = params.get('buyout', 85) / 100.0
    defect_rate = params.get('defect', 2) / 100.0
    adv_rate = params.get('ad', 10) / 100.0
    boost_rate = params.get('boost', 5) / 100.0
    target_m = params.get('target_margin', 20) / 100.0
    tax_regime = params.get('tax_regime', "УСН Доходы (6%)")

    # Дополнительный параметр в основном блоке (специфичный для Ozon)
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        model = st.radio("Модель работы", ["FBO", "FBS"], index=0, horizontal=True)
    with col_opt2:
        storage_days = st.number_input("Срок хранения (дней)", 0, 365, 45)

    # БЛОК 1. Каталог товаров (Единая база ПИМ)
    st.subheader("1. Выбор товара из PIM")
    try:
        all_products = conn.execute(
            "SELECT sku, name, length_cm, width_cm, height_cm, weight_kg, cost FROM products"
        ).fetchall()
        
        if not all_products:
            st.warning("Каталог PIM пуст. Добавьте товары в разделе PIM.")
            return
            
        df_pim = pd.DataFrame(all_products, columns=["SKU", "Название", "Д, см", "Ш, см", "В, см", "Вес, кг", "Себестоимость"])
        selected_sku = st.selectbox("Выберите SKU для расчета", df_pim["SKU"].tolist())
        product = df_pim[df_pim["SKU"] == selected_sku].iloc[0]
        
        st.info(f"Выбран: **{product['Название']}** | Себестоимость: **{product['Себестоимость']} ₽**")

        # БЛОК 2. Расчет
        if st.button("🚀 Рассчитать целевую цену на полку"):
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
            # Ищем цену X, при которой (X - X*расходы_в_% - расходы_фикс) - Налог = Прибыль
            # Для упрощения: X * (1 - комиссии% - маркетинг% - маржа%) = Себестоимость + Логистика
            total_pct_expenses = comm_rate + adv_rate + boost_rate + target_m
            
            # Учет выкупаемости и брака в логистике и реализации
            # Эффективная выручка с учетом возвратов
            denom = (1 - total_pct_expenses) * buyout_rate * (1 - defect_rate)
            
            if denom > 0:
                price_shelf = (cost + logistics_fix) / denom
                
                # Расчет налога (через общую функцию)
                tax_val, profit_val, margin_actual = calc_tax(price_shelf, cost + logistics_fix + (price_shelf * (total_pct_expenses - target_m)), tax_regime)

                st.success(f"### Рекомендуемая цена на полке: {round(price_shelf, 0)} ₽")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Чистая прибыль", f"{round(profit_val, 0)} ₽")
                    st.write(f"Логистика: {round(logistics_fix, 0)} ₽")
                with col2:
                    st.write(f"Комиссия ({int(comm_rate*100)}%): {round(price_shelf * comm_rate, 0)} ₽")
                    st.write(f"Маркетинг ({int((adv_rate+boost_rate)*100)}%): {round(price_shelf * (adv_rate + boost_rate), 0)} ₽")
                with col3:
                    st.write(f"Налог ({tax_regime}): {tax_val} ₽")
                    st.write(f"Выкупаемость: {int(buyout_rate*100)}%")
            else:
                st.error("Ошибка расчета: слишком высокие процентные расходы. Снизьте маржу или расходы на рекламу.")
    except Exception as e:
        st.error(f"Ошибка при работе с БД: {e}")
