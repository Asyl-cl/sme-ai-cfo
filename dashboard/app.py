import json, os
import pandas as pd
import streamlit as st
from core import metrics, forecast, cashflow, debts as debts_mod, effect as effect_mod, bank as bank_mod
from ai import qa

st.set_page_config(page_title="ИИ-финдиректор", layout="wide")
fmt = lambda n: f"{n:,.0f}".replace(",", " ")

sets = [d for d in ("sample", "sample2", "sample3") if os.path.exists(f"data/{d}/sales.csv")]
choice = st.sidebar.selectbox("Набор данных", sets)
st.sidebar.caption("Тестовые (синтетические) данные. Расчёты — код, ИИ только объясняет.")


@st.cache_data
def load(d):
    p = f"data/{d}/"
    return (pd.read_csv(p + "sales.csv"), pd.read_csv(p + "stock.csv"), pd.read_csv(p + "debts.csv"),
            pd.read_csv(p + "obligations.csv"), pd.read_csv(p + "bank.csv"),
            json.load(open(p + "meta.json", encoding="utf-8")))


sales, stock, debts, obl, bank, meta = load(choice)
today = pd.to_datetime(sales["date"]).max()
s = metrics.summary(sales, stock)
cf = cashflow.cash_forecast(sales, obl, debts, meta["cash_balance"])
eff = effect_mod.effect(sales, s, cf)
m = metrics.abc_analysis(metrics.product_margin(sales))

st.title(f"ИИ-финдиректор: {meta['business_name']}")
t1, t2, t3, t4, t5 = st.tabs(["Главное", "Товары", "Закупки", "Деньги", "Должники"])

with t1:
    st.subheader("Что вы получаете")
    a, b, c = st.columns(3)
    a.metric("Можно высвободить из остатков", f"{fmt(eff['freed_working_capital'])} ₸")
    b.metric("Потери от убыточных позиций в месяц", f"{fmt(eff['loss_avoided_per_month'])} ₸")
    c.metric("Кассовый разрыв", eff["cash_gap"]["date"] if eff["cash_gap"] else "не ожидается")
    if eff["cash_gap"]:
        st.error(f"Не хватит {fmt(eff['cash_gap']['shortfall'])} ₸ — есть время подготовиться.")
    st.caption("Допущения: " + " ".join(eff["assumptions"]))
    c1, c2 = st.columns(2)
    c1.metric("Выручка за период", f"{fmt(s['revenue'])} ₸")
    c2.metric("Прибыль за период", f"{fmt(s['profit'])} ₸")

with t2:
    st.subheader("Убыточные позиции")
    lm = metrics.loss_makers(m)[["name", "qty", "revenue", "profit", "margin_pct"]]
    st.dataframe(lm.rename(columns={"name": "Товар", "qty": "Продано", "revenue": "Выручка",
                                    "profit": "Прибыль", "margin_pct": "Маржа, %"}), hide_index=True)
    st.subheader("ABC-анализ: доля товаров в выручке")
    abc = m.groupby("abc").agg(Товаров=("sku", "count"), Выручка=("revenue", "sum"))
    st.bar_chart(abc["Выручка"])
    st.subheader("Замороженные остатки")
    dead = metrics.dead_stock(sales, stock, sales.groupby("sku")["cost"].mean().to_dict())
    st.dataframe(dead[["sku", "qty", "frozen_tenge"]].head(10), hide_index=True)

with t3:
    st.subheader("Что закупить на неделю")
    o = forecast.weekly_order(sales, stock).head(15).reset_index()
    st.dataframe(o.rename(columns={"sku": "Код", "name": "Товар", "forecast": "Спрос на неделю",
                                   "order_qty": "Заказать"}), hide_index=True)

with t4:
    st.subheader("Прогноз остатка денег (грубая оценка)")
    st.line_chart(pd.DataFrame(cf["timeline"]).set_index("date"))
    if cf["first_gap"]:
        st.error(f"Кассовый разрыв {cf['first_gap']['date']}: не хватает {fmt(cf['first_gap']['shortfall'])} ₸")
    st.subheader("Куда уходят деньги (банковская выписка)")
    bs = bank_mod.bank_summary(bank)
    st.bar_chart(pd.Series(bs["by_category"]))
    st.caption(f"Поступило {fmt(bs['income'])} ₸, потрачено {fmt(bs['expenses'])} ₸.")

with t5:
    st.subheader("Должники")
    dr = debts_mod.debt_ranking(debts, today=today)
    st.dataframe(dr[["client", "amount", "due_date", "overdue_days", "risk"]], hide_index=True)
    overdue = dr[dr["overdue_days"] > 0]
    if len(overdue):
        who = st.selectbox("Кому напомнить", overdue["client"].tolist())
        lang = st.radio("Язык", ["ru", "kk"], horizontal=True)
        r = overdue[overdue["client"] == who].iloc[0]
        deadline = (today + pd.Timedelta(days=3)).strftime("%d.%m.%Y")
        if st.button("Сформировать напоминание"):
            st.code(qa.reminder(who, float(r["amount"]), int(r["overdue_days"]), deadline, lang), language=None)
