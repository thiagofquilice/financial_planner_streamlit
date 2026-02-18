import math
from copy import deepcopy
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st


STEP_TITLES = [
    "Configuração mínima",
    "Economia unitária, variáveis e prazos",
    "Fixos e prazos de pagamento",
    "Projeção de volume e ponto de equilíbrio",
    "Investimentos",
    "Fluxo de caixa mensal e necessidade de caixa",
    "Viabilidade: VPL, TIR, TIRM, Payback",
    "Demonstrativos (Competência e Caixa)",
    "Análise de sensibilidade",
]


def default_item(item_id: str, name: str = "Novo item", unit: str = "unidade") -> Dict[str, Any]:
    return {"id": item_id, "name": name, "unit": unit}


def default_unit_econ(item_id: str) -> Dict[str, Any]:
    return {
        "price": 0.0,
        "tax_rate": 0.06,
        "receive_days": 0,
        "pay_days": 0,
        "variable_costs": [{"name": "", "qty": 1.0, "unit_value": 0.0}],
        "variable_expenses": [
            {"name": "", "classification": "Operacional", "qty": 1.0, "unit_value": 0.0}
        ],
    }


def default_scenario(name: str, item_ids: List[str]) -> Dict[str, Any]:
    return {
        "name": name,
        "horizon_months": 12,
        "projection_mode": "base_growth",
        "quantities": {iid: [0.0] * 12 for iid in item_ids},
        "base_growth": {iid: {"base": 0.0, "growth": 0.0} for iid in item_ids},
        "overrides": {
            "price": {},
            "receive_days": {},
            "pay_days": {},
            "tax_rate": {},
        },
    }


def init_state() -> None:
    if "step" not in st.session_state:
        st.session_state["step"] = 1

    st.session_state.setdefault("business", {"name": "", "start_period": pd.Timestamp.today().replace(day=1)})
    st.session_state.setdefault("items", [])
    st.session_state.setdefault("unit_economics", {})
    st.session_state.setdefault("fixed_costs", [{"item": "", "monthly_value": 0.0, "pay_days": 0, "obs": ""}])
    st.session_state.setdefault(
        "fixed_expenses",
        [{"item": "", "classification": "Operacional", "monthly_value": 0.0, "pay_days": 0, "obs": ""}],
    )
    st.session_state.setdefault("investments", [{"item": "", "category": "Investimento", "month": 0, "value": 0.0, "payment": "À vista", "installments": 1}])

    if "scenarios" not in st.session_state:
        st.session_state["scenarios"] = {"base": default_scenario("Cenário 1 — Base", [])}
    if "current_scenario_id" not in st.session_state:
        st.session_state["current_scenario_id"] = "base"

    st.session_state.setdefault("cashflow", {})
    st.session_state.setdefault("viability", {})
    st.session_state.setdefault("statements", {})
    st.session_state.setdefault("sensitivity_scenarios", [])


def ensure_item_consistency() -> None:
    item_ids = [i["id"] for i in st.session_state["items"]]

    for iid in item_ids:
        if iid not in st.session_state["unit_economics"]:
            st.session_state["unit_economics"][iid] = default_unit_econ(iid)

    for scenario in st.session_state["scenarios"].values():
        horizon = int(scenario.get("horizon_months", 12) or 12)
        for iid in item_ids:
            scenario.setdefault("quantities", {}).setdefault(iid, [0.0] * horizon)
            if len(scenario["quantities"][iid]) != horizon:
                scenario["quantities"][iid] = resize_series(scenario["quantities"][iid], horizon)
            scenario.setdefault("base_growth", {}).setdefault(iid, {"base": 0.0, "growth": 0.0})


def resize_series(series: List[float], size: int) -> List[float]:
    series = [float(x or 0.0) for x in series] if isinstance(series, list) else []
    if len(series) >= size:
        return series[:size]
    return series + [series[-1] if series else 0.0] * (size - len(series))


def payment_shift_month(days: int) -> int:
    return max(0, int(math.floor((days or 0) / 30)))


def annual_rate_percent_to_monthly_decimal(annual_percent: float) -> float:
    annual_decimal = max(-0.9999, float(annual_percent or 0.0) / 100)
    return (1 + annual_decimal) ** (1 / 12) - 1


def compute_irr(flows: np.ndarray, max_iter: int = 200, tol: float = 1e-7) -> float:
    flows = np.asarray(flows, dtype=float)
    if flows.size < 2 or not np.any(flows > 0) or not np.any(flows < 0):
        return np.nan

    def npv(rate: float) -> float:
        periods = np.arange(flows.size)
        return float(np.sum(flows / ((1 + rate) ** periods)))

    low = -0.9999
    high = 10.0
    npv_low = npv(low)
    npv_high = npv(high)
    expand_count = 0
    while npv_low * npv_high > 0 and expand_count < 12:
        high *= 2
        npv_high = npv(high)
        expand_count += 1

    if npv_low * npv_high > 0:
        return np.nan

    for _ in range(max_iter):
        mid = (low + high) / 2
        npv_mid = npv(mid)
        if abs(npv_mid) < tol:
            return mid
        if npv_low * npv_mid <= 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid
    return (low + high) / 2


def unit_metrics(item: Dict[str, Any], scenario: Dict[str, Any]) -> Dict[str, float]:
    iid = item["id"]
    econ = st.session_state["unit_economics"].get(iid, default_unit_econ(iid))
    price = float(scenario["overrides"]["price"].get(iid, econ.get("price", 0.0)) or 0.0)
    tax_rate = float(scenario["overrides"]["tax_rate"].get(iid, econ.get("tax_rate", 0.0)) or 0.0)

    cdf = pd.DataFrame(econ.get("variable_costs", []))
    edf = pd.DataFrame(econ.get("variable_expenses", []))

    var_cost = float((cdf.get("qty", pd.Series(dtype=float)).fillna(0) * cdf.get("unit_value", pd.Series(dtype=float)).fillna(0)).sum()) if not cdf.empty else 0.0
    var_exp = float((edf.get("qty", pd.Series(dtype=float)).fillna(0) * edf.get("unit_value", pd.Series(dtype=float)).fillna(0)).sum()) if not edf.empty else 0.0

    taxes = price * tax_rate
    net = price - taxes
    total_var = var_cost + var_exp
    mc_u = net - total_var
    mc_pct = mc_u / net if net > 0 else 0.0
    return {
        "price": price,
        "tax_rate": tax_rate,
        "taxes": taxes,
        "net_revenue": net,
        "var_cost": var_cost,
        "var_exp": var_exp,
        "total_var": total_var,
        "mc_u": mc_u,
        "mc_pct": mc_pct,
    }


def calculate_scenario(scenario_id: str) -> Dict[str, Any]:
    scenario = st.session_state["scenarios"][scenario_id]
    horizon = int(scenario.get("horizon_months", 12) or 12)
    months = np.arange(1, horizon + 1)
    cash_months = np.arange(0, horizon + 1)
    items = st.session_state["items"]

    fixed_cost_df = pd.DataFrame(st.session_state.get("fixed_costs", []))
    fixed_exp_df = pd.DataFrame(st.session_state.get("fixed_expenses", []))
    fixed_total = float(fixed_cost_df.get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()) + float(
        fixed_exp_df.get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()
    )

    operational_cash = np.zeros(horizon + 1)
    investment_cash = np.zeros(horizon + 1)

    dre_rows = []
    monthly_rows = []

    for m_idx, month in enumerate(months):
        gross = 0.0
        taxes = 0.0
        net = 0.0
        var_cost_tot = 0.0
        var_exp_tot = 0.0
        received = 0.0
        paid_var = 0.0

        for item in items:
            iid = item["id"]
            metrics = unit_metrics(item, scenario)
            qty = float(scenario.get("quantities", {}).get(iid, [0.0] * horizon)[m_idx] or 0.0)

            gross_i = metrics["price"] * qty
            taxes_i = metrics["taxes"] * qty
            net_i = metrics["net_revenue"] * qty
            var_cost_i = metrics["var_cost"] * qty
            var_exp_i = metrics["var_exp"] * qty

            gross += gross_i
            taxes += taxes_i
            net += net_i
            var_cost_tot += var_cost_i
            var_exp_tot += var_exp_i

            recv_days = int(scenario["overrides"]["receive_days"].get(iid, st.session_state["unit_economics"][iid].get("receive_days", 0)) or 0)
            pay_days = int(scenario["overrides"]["pay_days"].get(iid, st.session_state["unit_economics"][iid].get("pay_days", 0)) or 0)
            recv_month = int(month) + payment_shift_month(recv_days)
            pay_month = int(month) + payment_shift_month(pay_days)
            if recv_month <= horizon:
                received += gross_i
                operational_cash[recv_month] += gross_i
            if pay_month <= horizon:
                paid_var += (var_cost_i + var_exp_i)
                operational_cash[pay_month] -= var_cost_i + var_exp_i

        # tributo pago no mesmo mês da competência
        operational_cash[int(month)] -= taxes

        # fixos com prazo
        for _, row in fixed_cost_df.iterrows():
            pm = int(month) + payment_shift_month(int(row.get("pay_days", 0) or 0))
            if pm <= horizon:
                operational_cash[pm] -= float(row.get("monthly_value", 0.0) or 0.0)
        for _, row in fixed_exp_df.iterrows():
            pm = int(month) + payment_shift_month(int(row.get("pay_days", 0) or 0))
            if pm <= horizon:
                operational_cash[pm] -= float(row.get("monthly_value", 0.0) or 0.0)

        mc = net - var_cost_tot - var_exp_tot
        ebit = mc - fixed_total
        dre_rows.append(
            {
                "Mês": int(month),
                "Receita bruta": gross,
                "Tributos sobre receita": taxes,
                "Receita líquida": net,
                "Custos variáveis": var_cost_tot,
                "Despesas variáveis": var_exp_tot,
                "Margem de contribuição": mc,
                "Custos fixos": float(fixed_cost_df.get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()),
                "Despesas fixas": float(fixed_exp_df.get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()),
                "EBIT": ebit,
            }
        )

        monthly_rows.append(
            {
                "Mês": int(month),
                "Receita competência": gross,
                "Recebimentos (caixa)": received,
                "Pagamentos variáveis (caixa)": paid_var,
            }
        )

    # investimentos
    for _, row in pd.DataFrame(st.session_state.get("investments", [])).iterrows():
        month = int(row.get("month", 0) or 0)
        value = float(row.get("value", 0.0) or 0.0)
        if month < 0 or month > horizon or value <= 0:
            continue
        if str(row.get("payment", "À vista")) == "Parcelado":
            inst = max(1, int(row.get("installments", 1) or 1))
            parcel = value / inst
            for k in range(inst):
                pm = month + k
                if pm <= horizon:
                    investment_cash[pm] -= parcel
        else:
            investment_cash[month] -= value

    net_monthly_cash = operational_cash + investment_cash
    accumulated = np.cumsum(net_monthly_cash)
    valley_idx = int(np.argmin(accumulated)) if len(accumulated) else 0

    dre_monthly = pd.DataFrame(dre_rows)
    dre_monthly["Ano"] = ((dre_monthly["Mês"] - 1) // 12) + 1
    dre_annual = dre_monthly.groupby("Ano", as_index=False).sum(numeric_only=True)

    fc_monthly = pd.DataFrame(
        {
            "Mês": cash_months,
            "Caixa Operacional": operational_cash,
            "Caixa de Investimento": investment_cash,
            "Caixa Líquido do Mês": net_monthly_cash,
            "Caixa Acumulado": accumulated,
        }
    )
    fc_monthly["Ano"] = ((fc_monthly["Mês"] - 1) // 12) + 1
    fc_annual = fc_monthly.groupby("Ano", as_index=False).sum(numeric_only=True)

    # ponto de equilíbrio
    mc_consolid_pct = 0.0
    net_total = float(dre_monthly["Receita líquida"].sum())
    mc_total = float(dre_monthly["Margem de contribuição"].sum())
    if net_total > 0:
        mc_consolid_pct = mc_total / net_total
    pe_revenue = (fixed_total / mc_consolid_pct) if mc_consolid_pct > 0 else np.nan

    res = {
        "dre_monthly": dre_monthly,
        "dre_annual": dre_annual,
        "fc_monthly": fc_monthly,
        "fc_annual": fc_annual,
        "mc_consolid_pct": mc_consolid_pct,
        "break_even_revenue": pe_revenue,
        "valley": float(accumulated[valley_idx]) if len(accumulated) else 0.0,
        "valley_month": int(cash_months[valley_idx]) if len(cash_months) else 0,
    }

    st.session_state["cashflow"][scenario_id] = {
        "monthly": fc_monthly,
        "valley": res["valley"],
        "valley_month": res["valley_month"],
    }
    st.session_state["statements"][scenario_id] = {
        "dre_monthly": dre_monthly,
        "dre_annual": dre_annual,
        "fc_annual": fc_annual,
    }
    return res


def calc_viability(scenario_id: str, discount_m: float, reinvest_m: float) -> Dict[str, float]:
    result = calculate_scenario(scenario_id)
    flows = result["fc_monthly"]["Caixa Líquido do Mês"].to_numpy(dtype=float)
    periods = np.arange(len(flows))

    vpl = float(np.sum(flows / ((1 + discount_m) ** periods)))

    tir = compute_irr(flows)

    pos_mask = flows > 0
    neg_mask = flows < 0
    if np.any(neg_mask) and np.any(pos_mask):
        # TIRM (MIRR): desconta fluxos negativos para o período zero e capitaliza
        # fluxos positivos até o último período, preservando o mês de cada fluxo.
        n_periods = len(flows) - 1
        pv_neg = np.sum(flows[neg_mask] / ((1 + discount_m) ** periods[neg_mask]))
        fv_pos = np.sum(flows[pos_mask] * ((1 + reinvest_m) ** (n_periods - periods[pos_mask])))
        tirm = ((-fv_pos / pv_neg) ** (1 / n_periods)) - 1 if pv_neg < 0 and n_periods > 0 else np.nan
    else:
        tirm = np.nan

    cum = np.cumsum(flows)
    payback = next((i for i, v in enumerate(cum) if v >= 0), np.nan)

    disc_cum = np.cumsum(flows / ((1 + discount_m) ** periods))
    payback_disc = next((i for i, v in enumerate(disc_cum) if v >= 0), np.nan)

    viab = {
        "vpl": vpl,
        "tir": tir,
        "tirm": float(tirm) if pd.notna(tirm) else np.nan,
        "payback": payback,
        "payback_discounted": payback_disc,
        "discount_rate": discount_m,
        "reinvest_rate": reinvest_m,
    }
    st.session_state["viability"][scenario_id] = viab
    return viab


def render_nav() -> None:
    with st.sidebar:
        st.title("Planejamento Financeiro")
        st.progress(st.session_state["step"] / len(STEP_TITLES))
        st.caption(f"Etapa {st.session_state['step']} de {len(STEP_TITLES)}")
        for idx, title in enumerate(STEP_TITLES, start=1):
            mark = "➡️" if idx == st.session_state["step"] else "•"
            if st.button(f"{mark} {idx}. {title}", key=f"nav_{idx}", use_container_width=True):
                st.session_state["step"] = idx


def header(step: int, text: str) -> None:
    st.subheader(f"Etapa {step} — {STEP_TITLES[step-1]}")
    st.caption(text)


def render_next(step: int, enabled: bool = True, disabled_help: str = "") -> None:
    st.markdown("---")
    if not enabled and disabled_help:
        st.info(disabled_help)
    if st.button("Próxima etapa →", key=f"next_step_{step}", disabled=not enabled):
        st.session_state["step"] = min(step + 1, len(STEP_TITLES))
        st.rerun()


def step1() -> None:
    header(
        1,
        "Tome esta etapa como o ‘cadastro básico’ do seu negócio. Você só vai definir seus produtos/serviços e como eles são vendidos. Tributos e detalhes financeiros entram nas próximas etapas.",
    )

    b = st.session_state["business"]
    b["name"] = st.text_input("Nome do negócio (opcional)", value=b.get("name", ""), key="business_name")
    b["start_period"] = st.date_input(
        "Data inicial do planejamento",
        value=b.get("start_period"),
        key="business_start",
        format="DD/MM/YYYY",
    )

    with st.expander("Instruções"):
        st.write(
            "- Cadastre pelo menos um produto/serviço. Se você tem apenas um serviço (ex.: consultoria), crie um único item.\n\n"
            "- A ‘unidade de venda’ é como você cobra: unidade, hora, mensalidade, diária etc.\n\n"
            "- Nas próximas etapas você vai montar a margem por unidade, depois somar custos fixos, projetar vendas e chegar ao fluxo de caixa."
        )

    st.markdown("#### Produtos/serviços")
    if st.button("Adicionar produto/serviço", key="add_item"):
        item_id = f"item_{len(st.session_state['items'])+1}_{np.random.randint(1000,9999)}"
        st.session_state["items"].append(default_item(item_id))

    to_remove = None
    for i, item in enumerate(st.session_state["items"]):
        c1, c2, c3 = st.columns([4, 2, 1])
        item["name"] = c1.text_input("Nome", value=item.get("name", ""), key=f"item_name_{item['id']}")
        item["unit"] = c2.text_input("Unidade de venda", value=item.get("unit", "unidade"), key=f"item_unit_{item['id']}")
        if c3.button("Remover", key=f"rm_item_{item['id']}"):
            to_remove = i
    if to_remove is not None:
        iid = st.session_state["items"][to_remove]["id"]
        st.session_state["items"].pop(to_remove)
        st.session_state["unit_economics"].pop(iid, None)

    if not st.session_state["items"]:
        st.info("Cadastre ao menos 1 item para seguir para as próximas etapas.")

    render_next(1, enabled=bool(st.session_state["items"]), disabled_help="Cadastre ao menos 1 produto/serviço para habilitar a próxima etapa.")


def _editable_variable_table(df: pd.DataFrame, key: str, expense: bool = False) -> pd.DataFrame:
    normalized = df.copy()
    expected_cols = ["name", "qty", "unit_value"] + (["classification"] if expense else [])
    for col in expected_cols:
        if col not in normalized.columns:
            normalized[col] = "" if col in {"name", "classification"} else 0.0
    normalized = normalized[expected_cols]

    base_cols = {
        "name": st.column_config.TextColumn("Item"),
        "qty": st.column_config.NumberColumn("Quantidade unitária", min_value=0.0, step=0.1),
        "unit_value": st.column_config.NumberColumn("Valor unitário", min_value=0.0, step=0.01, format="R$ %.2f"),
    }
    if expense:
        base_cols["classification"] = st.column_config.SelectboxColumn("Classificação", options=["Operacional", "Vendas"])

    edited = st.data_editor(
        normalized,
        key=key,
        num_rows="dynamic",
        use_container_width=True,
        column_config=base_cols,
        hide_index=True,
    )
    if "qty" not in edited.columns:
        edited["qty"] = 0.0
    if "unit_value" not in edited.columns:
        edited["unit_value"] = 0.0
    edited["qty"] = pd.to_numeric(edited["qty"], errors="coerce").fillna(0.0)
    edited["unit_value"] = pd.to_numeric(edited["unit_value"], errors="coerce").fillna(0.0)
    edited["total"] = edited["qty"].fillna(0) * edited["unit_value"].fillna(0)
    return edited


def step2() -> None:
    header(
        2,
        "Aqui você monta a ‘economia unitária’ (unit economics) de cada produto/serviço: quanto sobra, por unidade vendida, para pagar os custos e despesas fixos e gerar lucro. Também vamos registrar prazos médios de recebimento e pagamento, que afetam o caixa.",
    )
    with st.expander("Instruções"):
        st.write(
            "- Nesta etapa, você calcula quanto realmente sobra por unidade vendida depois de tributos, custos variáveis e despesas variáveis.\n\n"
            "- Comece preenchendo preço e tributos. Em seguida, detalhe custos/despesas que variam com cada venda para chegar à margem de contribuição unitária.\n\n"
            "- Os prazos de recebimento e pagamento não mudam o lucro, mas mudam o momento em que o dinheiro entra e sai do caixa."
        )

    with st.expander("Mais informações: como o Simples Nacional funciona"):
        st.write(
            "- O Simples Nacional organiza atividades em Anexos (I a V). Cada Anexo tem faixas de receita bruta acumulada em 12 meses (RBT12) e uma alíquota nominal para cada faixa.\n\n"
            "- Na prática, muitas empresas usam a ‘alíquota efetiva’, calculada pela fórmula: Alíquota efetiva = ((RBT12 × Alíquota nominal) − Parcela a deduzir) ÷ RBT12.\n\n"
            "- Por isso, duas empresas no mesmo Anexo podem pagar percentuais diferentes dependendo do faturamento.\n\n"
            "- Em alguns serviços (Anexos III e V), existe o Fator R (relação entre folha de pagamento e receita), que pode alterar o Anexo aplicável. Este app vai tratar isso como uma evolução futura/avançada (ou como ajuste manual, se você preferir)."
        )

    with st.expander("Mais informações: custos e despesas variáveis (comércio, indústria e serviços)"):
        st.write(
            "Este app separa gastos variáveis em três grupos para facilitar a análise e a aprendizagem:\n\n"
            "- Custos variáveis: gastos diretamente ligados à produção/entrega do que você vende (o “custo do produto/serviço” por unidade).\n\n"
            "- Despesas variáveis de vendas: gastos que variam porque você está vendendo e adquirindo clientes (custo para realizar a venda).\n\n"
            "- Despesas variáveis operacionais: gastos que variam porque você precisa processar, atender e entregar a venda (custo para operar/entregar em escala).\n\n"
            "Importante: essa separação é uma ferramenta gerencial (para tomada de decisão). Na contabilidade, algumas empresas agrupam esses itens de outra forma. Aqui, o objetivo é entender onde a margem está sendo consumida e quais alavancas você pode ajustar.\n\n"
            "Como decidir se algo é variável?\n\n"
            "- Se o gasto existe mesmo vendendo zero, ele tende a ser fixo.\n\n"
            "- Se o gasto aumenta quando você vende mais (por pedido, por transação, por unidade, por uso), ele tende a ser variável.\n\n"
            "- Se o gasto é necessário para ‘produzir/entregar’ o produto/serviço, ele tende a ser custo variável.\n\n"
            "- Se o gasto é necessário para ‘vender’ (captar pedido/cliente), ele tende a ser despesa variável de vendas.\n\n"
            "- Se o gasto é necessário para ‘processar/atender/entregar’ a venda, ele tende a ser despesa variável operacional.\n\n"
            "Exemplos por tipo de negócio\n\n"
            "1) Comércio\n"
            "- Custos variáveis (por unidade/pedido):\n"
            "  - Custo da mercadoria vendida (CMV).\n"
            "  - Embalagem por pedido.\n"
            "  - Frete por pedido, quando a empresa paga e trata como custo do pedido.\n\n"
            "- Despesas variáveis de vendas:\n"
            "  - Comissão de vendedores.\n"
            "  - Comissão/fee de marketplace quando funciona como comissão por venda.\n"
            "  - Anúncios medidos por conversão (quando você consegue estimar custo por venda).\n\n"
            "- Despesas variáveis operacionais:\n"
            "  - Taxas de cartão/gateway por transação.\n"
            "  - Antifraude por transação.\n"
            "  - Atendimento terceirizado por ticket (quando cobrado por volume).\n"
            "  - Custos de logística por entrega, quando tratados como despesa operacional.\n\n"
            "2) Indústria\n"
            "- Custos variáveis:\n"
            "  - Matéria-prima por unidade.\n"
            "  - Insumos diretos (componentes, embalagem técnica).\n"
            "  - Energia diretamente associada ao volume produzido (quando mensurável).\n"
            "  - Mão de obra diretamente proporcional à produção (quando aplicável).\n\n"
            "- Despesas variáveis de vendas:\n"
            "  - Comissão comercial por venda.\n"
            "  - Frete de venda por pedido (se tratado como despesa de venda).\n\n"
            "- Despesas variáveis operacionais:\n"
            "  - Custos variáveis de armazenagem por volume movimentado.\n"
            "  - Taxas de processamento por pedido/nota.\n"
            "  - Custos de assistência técnica por chamado (quando cobrado por atendimento).\n\n"
            "3) Serviços (inclui SaaS)\n"
            "- Custos variáveis:\n"
            "  - Horas de profissionais alocadas diretamente por projeto/cliente (quando pagas por entrega).\n"
            "  - Terceirização por projeto (freelancers por demanda).\n"
            "  - Ferramentas cobradas por uso diretamente atribuível a cada entrega.\n\n"
            "- Despesas variáveis de vendas:\n"
            "  - Comissão por contrato fechado.\n"
            "  - Afiliados/parcerias com comissão por venda.\n"
            "  - Anúncios com custo por aquisição (CPA) quando o custo é por conversão/contrato.\n\n"
            "- Despesas variáveis operacionais:\n"
            "  - Infraestrutura em nuvem (cloud) por uso (ex.: por usuários ativos, por armazenamento, por requisições).\n"
            "  - SMS/WhatsApp/e-mail transacional por mensagem.\n"
            "  - Taxas de plataforma e processamento por transação.\n"
            "  - Suporte por ticket (quando cresce com a base e é cobrado por volume).\n\n"
            "Por que separar ‘despesa variável operacional’ de ‘despesa variável de vendas’?\n\n"
            "- Porque isso muda suas decisões. Se o problema está em vendas, você ajusta canal, comissão, CAC (custo de aquisição de clientes). Se o problema está na operação, você ajusta entrega, automação, infraestrutura, logística e suporte.\n\n"
            "- Em startups, é comum que parte relevante do custo variável esteja na operação (por exemplo, cloud por uso, suporte por ticket e taxas por transação). Por isso faz sentido reconhecer ‘despesas operacionais variáveis’ como categoria gerencial.\n\n"
            "Uma dica prática final:\n"
            "- Se você tem dúvida, pergunte: ‘Este gasto cresce com o número de vendas/pedidos/usuários?’ Se sim, ele é variável.\n\n"
            "- Em seguida, pergunte: ‘Ele existe para vender ou para operar/entregar?’ Isso te ajuda a classificar em Vendas ou Operacional."
        )

    if not st.session_state["items"]:
        st.warning("Cadastre ao menos 1 item na Etapa 1.")
        render_next(2)
        return

    ensure_item_consistency()
    anexo_min_rate = {
        "Anexo I (Comércio)": 0.04,
        "Anexo II (Indústria)": 0.045,
        "Anexo III (Serviços)": 0.06,
        "Anexo IV (Serviços — construção/limpeza/vigilância, etc.)": 0.045,
        "Anexo V (Serviços — técnicos/intelectuais, etc.)": 0.155,
    }
    legacy_anexo_aliases = {
        "I": "Anexo I (Comércio)",
        "II": "Anexo II (Indústria)",
        "III": "Anexo III (Serviços)",
        "IV": "Anexo IV (Serviços — construção/limpeza/vigilância, etc.)",
        "V": "Anexo V (Serviços — técnicos/intelectuais, etc.)",
    }

    summary = []
    for item in st.session_state["items"]:
        iid = item["id"]
        econ = st.session_state["unit_economics"][iid]
        raw_anexo = str(econ.get("simples_anexo", "")).strip()
        econ["simples_anexo"] = legacy_anexo_aliases.get(raw_anexo, raw_anexo)
        if econ["simples_anexo"] not in anexo_min_rate:
            econ["simples_anexo"] = "Anexo III (Serviços)"

        m = unit_metrics(item, st.session_state["scenarios"][st.session_state["current_scenario_id"]])
        summary.append(
            {
                "Item": item["name"],
                "Preço": m["price"],
                "Tributos unitários": m["taxes"],
                "Receita líquida": m["net_revenue"],
                "Variáveis unitários": m["total_var"],
                "MC unitária": m["mc_u"],
                "MC %": m["mc_pct"],
            }
        )

    st.markdown("### Análise por Item")
    st.info("Preencha os campos de cada item abaixo para atualizar a análise automaticamente.")
    st.dataframe(pd.DataFrame(summary), use_container_width=True)
    st.info("MC consolidada depende do mix de vendas; será calculada na Etapa 4 com base nas quantidades projetadas.")

    for item in st.session_state["items"]:
        iid = item["id"]
        econ = st.session_state["unit_economics"][iid]
        raw_anexo = str(econ.get("simples_anexo", "")).strip()
        econ["simples_anexo"] = legacy_anexo_aliases.get(raw_anexo, raw_anexo)
        if econ["simples_anexo"] not in anexo_min_rate:
            econ["simples_anexo"] = "Anexo III (Serviços)"
        with st.expander(f"{item['name']} ({item['unit']})", expanded=False):
            c1, c2 = st.columns(2)
            econ["price"] = c1.number_input("Preço de venda por unidade", min_value=0.0, step=0.01, value=float(econ.get("price", 0.0)), key=f"price_{iid}")

            previous_anexo = econ.get("simples_anexo")
            anexo = c2.selectbox(
                "Anexo do Simples Nacional",
                options=list(anexo_min_rate.keys()),
                index=list(anexo_min_rate.keys()).index(previous_anexo) if previous_anexo in anexo_min_rate else 2,
                key=f"anexo_{iid}",
            )
            econ["simples_anexo"] = anexo
            if previous_anexo != anexo:
                econ["tax_rate"] = anexo_min_rate[anexo]
                st.session_state.pop(f"tax_{iid}", None)

            st.info(
                "No Simples Nacional, a alíquota efetiva tende a aumentar conforme sua receita bruta acumulada (RBT12). "
                "Neste app, por enquanto usamos a alíquota mínima do Anexo como ponto de partida. "
                "O ajuste da alíquota ao longo do tempo será feito na Etapa 4, com base na projeção de volume/receita."
            )

            econ["tax_rate"] = st.number_input(
                "Tributos sobre receita (% do Simples Nacional)",
                min_value=0.0,
                max_value=1.0,
                step=0.005,
                value=float(econ.get("tax_rate", anexo_min_rate[econ["simples_anexo"]])),
                format="%.4f",
                key=f"tax_{iid}",
            )

            st.markdown("**Custos Variáveis**")
            st.caption("Use Tab ou Enter para ir para a próxima célula. Ao concluir, clique em 'Salvar'.")
            with st.form(key=f"form_vcost_{iid}", enter_to_submit=False, clear_on_submit=False):
                cdf = _editable_variable_table(pd.DataFrame(econ.get("variable_costs", [])), key=f"vcost_{iid}")
                save_costs = st.form_submit_button("Salvar custos variáveis")
            if save_costs:
                econ["variable_costs"] = cdf.drop(columns=["total"]).to_dict("records")
                st.success("Custos variáveis salvos.")
            st.caption(f"Total de custos variáveis unitários: R$ {cdf['total'].sum():,.2f}")

            st.markdown("**Despesas Variáveis**")
            st.caption("Use Tab ou Enter para ir para a próxima célula. Ao concluir, clique em 'Salvar'.")
            with st.form(key=f"form_vexp_{iid}", enter_to_submit=False, clear_on_submit=False):
                edf = _editable_variable_table(pd.DataFrame(econ.get("variable_expenses", [])), key=f"vexp_{iid}", expense=True)
                save_expenses = st.form_submit_button("Salvar despesas variáveis")
            if save_expenses:
                econ["variable_expenses"] = edf.drop(columns=["total"]).to_dict("records")
                st.success("Despesas variáveis salvas.")
            st.caption(f"Total de despesas variáveis unitárias: R$ {edf['total'].sum():,.2f}")

            p1, p2 = st.columns(2)
            econ["receive_days"] = p1.number_input("Prazo médio de recebimento (dias)", min_value=0, step=1, value=int(econ.get("receive_days", 0)), key=f"recv_{iid}")
            econ["pay_days"] = p2.number_input("Prazo médio de pagamento a fornecedores (dias)", min_value=0, step=1, value=int(econ.get("pay_days", 0)), key=f"pay_{iid}")

    render_next(2)


def _fixed_table(df: pd.DataFrame, key: str, with_class: bool = False) -> pd.DataFrame:
    col_cfg = {
        "item": st.column_config.TextColumn("Item"),
        "monthly_value": st.column_config.NumberColumn("Valor mensal", min_value=0.0, step=0.01, format="R$ %.2f"),
        "pay_days": st.column_config.NumberColumn("Prazo de pagamento (dias)", min_value=0, step=1),
        "obs": st.column_config.TextColumn("Observação (opcional)"),
    }
    if with_class:
        col_cfg["classification"] = st.column_config.SelectboxColumn("Classificação", options=["Operacional", "Vendas"])

    return st.data_editor(df, num_rows="dynamic", use_container_width=True, hide_index=True, column_config=col_cfg, key=key)


def step3() -> None:
    header(3, "Agora vamos registrar os gastos fixos: aqueles que existem mesmo se você vender pouco (ou nada). Isso é a ‘estrutura fixa’ do negócio e é fundamental para calcular ponto de equilíbrio.")
    with st.expander("Instruções"):
        st.write(
            "- Fixos são gastos que existem mesmo com poucas vendas (aluguel, salários, ferramentas, contratos recorrentes).\n\n"
            "- Custos fixos se relacionam à entrega/produção; despesas fixas à operação e vendas.\n\n"
            "- O prazo de pagamento muda o caixa: se você paga depois, o caixa ‘respira’ mais no começo."
        )

    st.markdown("### Custos Fixos")
    cdf = _fixed_table(pd.DataFrame(st.session_state["fixed_costs"]), key="fixed_costs_table")
    st.session_state["fixed_costs"] = cdf.to_dict("records")
    st.caption(f"Total de custos fixos mensais: R$ {cdf.get('monthly_value', pd.Series(dtype=float)).fillna(0).sum():,.2f}")

    st.markdown("### Despesas Fixas")
    edf = _fixed_table(pd.DataFrame(st.session_state["fixed_expenses"]), key="fixed_expenses_table", with_class=True)
    st.session_state["fixed_expenses"] = edf.to_dict("records")
    st.caption(f"Total de despesas fixas mensais: R$ {edf.get('monthly_value', pd.Series(dtype=float)).fillna(0).sum():,.2f}")
    render_next(3)


def regenerate_quantities(scenario: Dict[str, Any], item_id: str) -> None:
    horizon = int(scenario.get("horizon_months", 12) or 12)
    base = float(scenario["base_growth"][item_id].get("base", 0.0) or 0.0)
    growth = float(scenario["base_growth"][item_id].get("growth", 0.0) or 0.0)
    q = []
    curr = base
    for _ in range(horizon):
        qty_ceiled = math.ceil(max(0.0, curr))
        q.append(float(qty_ceiled))
        curr = curr * (1 + growth)
    scenario["quantities"][item_id] = q


def _scenario_header_and_selection(step_number: int) -> Tuple[str, Dict[str, Any]]:
    scenarios = st.session_state["scenarios"]
    sids = list(scenarios.keys())
    labels = [f"{sid} - {scenarios[sid]['name']}" for sid in sids]
    selected_label = st.selectbox(
        "Cenário ativo",
        labels,
        index=sids.index(st.session_state["current_scenario_id"]) if st.session_state["current_scenario_id"] in sids else 0,
        key=f"scenario_active_step_{step_number}",
    )
    st.session_state["current_scenario_id"] = selected_label.split(" - ")[0]
    sid = st.session_state["current_scenario_id"]
    return sid, scenarios[sid]


def _render_break_even_summary(sid: str, scenario: Dict[str, Any]) -> None:
    st.markdown("### Resumo do cenário")
    result = calculate_scenario(sid)
    st.metric("MC consolidada (%)", f"{result['mc_consolid_pct']:.2%}")
    if pd.notna(result["break_even_revenue"]):
        st.metric("Ponto de Equilíbrio em Receita (mensal)", f"R$ {result['break_even_revenue']:,.2f}")
    else:
        st.info("Ponto de equilíbrio em receita indisponível enquanto a margem de contribuição consolidada for zero ou negativa.")

    items = st.session_state["items"]
    if items:
        mix_rows: List[Dict[str, Any]] = []
        total_revenue = 0.0
        for item in items:
            iid = item["id"]
            econ = st.session_state["unit_economics"][iid]
            price_eff = float(scenario["overrides"]["price"].get(iid, econ.get("price", 0.0)) or 0.0)
            qty_total = float(np.sum(scenario.get("quantities", {}).get(iid, [])))
            revenue_total = qty_total * price_eff
            total_revenue += revenue_total
            mix_rows.append(
                {
                    "Produto/Serviço": item["name"],
                    "Unidade": item["unit"],
                    "Preço unitário": price_eff,
                    "Receita projetada": revenue_total,
                    "Quantidade projetada": qty_total,
                }
            )

        if total_revenue > 0:
            be_revenue_total = float(result["break_even_revenue"]) if pd.notna(result["break_even_revenue"]) else np.nan
            for row in mix_rows:
                share = row["Receita projetada"] / total_revenue
                row["Proporção da receita"] = share
                row["PE Receita (mensal)"] = be_revenue_total * share if pd.notna(be_revenue_total) else np.nan
                row["PE Quantidade (mensal)"] = (
                    row["PE Receita (mensal)"] / row["Preço unitário"] if row["Preço unitário"] > 0 and pd.notna(row["PE Receita (mensal)"]) else np.nan
                )
        else:
            for row in mix_rows:
                row["Proporção da receita"] = np.nan
                row["PE Receita (mensal)"] = np.nan
                row["PE Quantidade (mensal)"] = np.nan

        mix_df = pd.DataFrame(mix_rows)
        st.markdown("#### Quadro de mix de receita e ponto de equilíbrio por produto/serviço")
        st.dataframe(
            mix_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Preço unitário": st.column_config.NumberColumn(format="R$ %.2f"),
                "Receita projetada": st.column_config.NumberColumn(format="R$ %.2f"),
                "Quantidade projetada": st.column_config.NumberColumn(format="%.2f"),
                "Proporção da receita": st.column_config.ProgressColumn(format="%.2f%%", min_value=0.0, max_value=1.0),
                "PE Receita (mensal)": st.column_config.NumberColumn(format="R$ %.2f"),
                "PE Quantidade (mensal)": st.column_config.NumberColumn(format="%.2f"),
            },
        )
        st.caption("A proporção usa a receita total projetada no horizonte selecionado. O PE por item distribui o ponto de equilíbrio mensal conforme esse mix.")

    if len(st.session_state["items"]) == 1:
        item = st.session_state["items"][0]
        mc_u = unit_metrics(item, scenario)["mc_u"]
        fixed_total = pd.DataFrame(st.session_state["fixed_costs"]).get("monthly_value", pd.Series(dtype=float)).fillna(0).sum() + pd.DataFrame(st.session_state["fixed_expenses"]).get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()
        if mc_u > 0:
            st.metric("Ponto de Equilíbrio em Unidades", f"{fixed_total / mc_u:,.2f} {item['unit']}")


def step4() -> None:
    header(4, "Aqui você projeta quantas unidades vai vender e visualiza a receita mensal por item. Ao final, o app calcula o ponto de equilíbrio para o cenário ativo.")
    with st.expander("Instruções"):
        st.write(
            "1) Escolha o cenário ativo.\n\n"
            "2) Defina o tempo e o modo de projeção.\n\n"
            "3) Preencha as quantidades por item e a taxa de crescimento em porcentagem; a receita será calculada automaticamente.\n\n"
            "4) Veja o ponto de equilíbrio ao final."
        )

    ensure_item_consistency()
    if not st.session_state["items"]:
        st.warning("Cadastre ao menos 1 item na Etapa 1.")
        render_next(4)
        return

    st.markdown("### 1) Cenário ativo")
    sid, scenario = _scenario_header_and_selection(step_number=4)

    st.markdown("### 2) Configurações de projeção")
    horizon = st.selectbox("Tempo de projeção (meses)", [12, 24, 36, 60], index=[12, 24, 36, 60].index(int(scenario.get("horizon_months", 12))), key=f"horizon_{sid}")
    scenario["horizon_months"] = horizon
    for iid in scenario["quantities"]:
        scenario["quantities"][iid] = resize_series(scenario["quantities"][iid], horizon)

    scenario["projection_mode"] = st.radio("Modo para quantidades", ["manual", "base_growth"], format_func=lambda x: "Inserir manualmente mês a mês" if x == "manual" else "Definir quantidade base e taxa de crescimento mensal", horizontal=True, key=f"mode_{sid}")
    st.caption("Você pode começar com base + crescimento e depois ajustar manualmente.")

    st.markdown("### 3) Projeção por produto/serviço")

    for item in st.session_state["items"]:
        iid = item["id"]
        st.markdown(f"#### {item['name']}")
        if scenario["projection_mode"] == "base_growth":
            b1, b2, b3 = st.columns([2, 2, 1])
            scenario["base_growth"][iid]["base"] = b1.number_input("Quantidade mês 1", min_value=0.0, step=1.0, value=float(scenario["base_growth"][iid].get("base", 0.0)), key=f"base_{sid}_{iid}")
            growth_percent = b2.number_input(
                "Taxa de crescimento mensal (%)",
                min_value=-99.0,
                step=1.0,
                value=float(scenario["base_growth"][iid].get("growth", 0.0) or 0.0) * 100,
                format="%.2f",
                key=f"growth_{sid}_{iid}",
            )
            scenario["base_growth"][iid]["growth"] = float(growth_percent) / 100
            if b3.button("Gerar série", key=f"gen_{sid}_{iid}"):
                regenerate_quantities(scenario, iid)

        econ = st.session_state["unit_economics"][iid]
        price_eff = float(scenario["overrides"]["price"].get(iid, econ.get("price", 0.0)) or 0.0)
        qdf = pd.DataFrame({"Mês": range(1, horizon + 1), "Quantidade": scenario["quantities"][iid]})
        qdf["Quantidade"] = np.ceil(pd.to_numeric(qdf["Quantidade"], errors="coerce").fillna(0.0)).astype(float)
        qdf["Receita"] = qdf["Quantidade"] * price_eff
        st.caption("Receita = quantidade × preço (do cenário).")
        qedit = st.data_editor(qdf, hide_index=True, key=f"qtable_{sid}_{iid}", use_container_width=True, num_rows="fixed")
        qedit["Quantidade"] = np.ceil(pd.to_numeric(qedit["Quantidade"], errors="coerce").fillna(0.0)).astype(float)
        qedit["Receita"] = qedit["Quantidade"] * price_eff
        scenario["quantities"][iid] = qedit["Quantidade"].tolist()
        st.caption("Quantidades arredondadas para cima automaticamente.")

    _render_break_even_summary(sid, scenario)
    render_next(4)



def step5() -> None:
    header(5, "Agora registre os investimentos necessários para colocar a operação de pé (equipamentos, desenvolvimento, implantação). Eles entram no fluxo de caixa como saídas de investimento.")

    df = pd.DataFrame(st.session_state["investments"])
    if df.empty:
        df = pd.DataFrame([{"item": "", "category": "Investimento", "month": 0, "value": 0.0, "payment": "À vista"}])

    for col, default in {
        "item": "",
        "category": "Investimento",
        "month": 0,
        "value": 0.0,
        "payment": "À vista",
    }.items():
        if col not in df.columns:
            df[col] = default

    df = df[["item", "category", "month", "value", "payment"]]
    cfg = {
        "item": st.column_config.TextColumn("Item"),
        "category": st.column_config.SelectboxColumn("Categoria", options=["Investimento", "Implementação", "Outros"]),
        "month": st.column_config.NumberColumn("Período de realização", min_value=0, step=1),
        "value": st.column_config.NumberColumn("Valor", min_value=0.0, step=0.01, format="R$ %.2f"),
        "payment": st.column_config.SelectboxColumn("Forma de pagamento", options=["À vista", "Parcelado"]),
    }
    edited = st.data_editor(df, key="investments_table", num_rows="dynamic", use_container_width=True, hide_index=True, column_config=cfg)

    edited["month"] = pd.to_numeric(edited.get("month", 0), errors="coerce").fillna(0).clip(lower=0).astype(int)
    edited["value"] = pd.to_numeric(edited.get("value", 0.0), errors="coerce").fillna(0.0)
    edited["item"] = edited.get("item", "").fillna("")
    edited["category"] = edited.get("category", "Investimento").fillna("Investimento")
    edited["payment"] = edited.get("payment", "À vista").fillna("À vista")
    edited["installments"] = 1

    st.session_state["investments"] = edited.to_dict("records")
    render_next(5)


def step6() -> None:
    header(6, "O fluxo de caixa mostra quando o dinheiro entra e sai de verdade. O app destaca o pior momento do caixa acumulado, que costuma indicar a necessidade de caixa para sustentar a operação até ela se pagar.")

    sid = st.session_state["current_scenario_id"]
    res = calculate_scenario(sid)
    fc = res["fc_monthly"].copy()
    st.dataframe(fc[["Mês", "Caixa Operacional", "Caixa de Investimento", "Caixa Líquido do Mês", "Caixa Acumulado"]], use_container_width=True, hide_index=True)

    acum_operacional = fc["Caixa Operacional"].cumsum()
    valley_oper = float(acum_operacional.min()) if not acum_operacional.empty else 0.0
    valley_oper_month = int(fc.loc[acum_operacional.idxmin(), "Mês"]) if not acum_operacional.empty else 1
    valley_total = float(fc["Caixa Acumulado"].min()) if not fc.empty else 0.0
    valley_total_month = int(fc.loc[fc["Caixa Acumulado"].idxmin(), "Mês"]) if not fc.empty else 1

    c1, c2 = st.columns(2)
    c1.error(
        f"Necessidade de caixa sem Caixa de Investimento: R$ {abs(min(0, valley_oper)):,.2f} no mês {valley_oper_month}."
    )
    c2.error(
        f"Necessidade de caixa com Caixa de Investimento: R$ {abs(min(0, valley_total)):,.2f} no mês {valley_total_month}."
    )
    st.caption("Definição: menor valor do caixa acumulado. O primeiro considera somente a operação; o segundo inclui também desembolsos de investimento.")
    render_next(6)


def step7() -> None:
    header(7, "Com o fluxo de caixa pronto, o app calcula indicadores clássicos para avaliar se o projeto compensa. Se você for iniciante, foque primeiro em VPL (Valor Presente Líquido) e Payback.")
    with st.expander("Instruções"):
        st.write(
            "- Taxa mínima desejada é o retorno que você exige para considerar o projeto atrativo.\n\n"
            "- VPL (Valor Presente Líquido) compara o projeto com essa taxa: VPL > 0 indica que o projeto supera a taxa mínima.\n\n"
            "- Payback mostra quando o caixa acumulado deixa de ser negativo.\n\n"
            "- TIR (Taxa Interna de Retorno) e TIRM (Taxa Interna de Retorno Modificada) são úteis, mas podem confundir no início — use como complemento."
        )

    sid = st.session_state["current_scenario_id"]
    c1, c2 = st.columns(2)
    discount_annual_pct = c1.number_input(
        "Taxa mínima desejada (TMA) ao ano (%)",
        min_value=0.0,
        step=0.1,
        value=float(st.session_state.get("discount_rate_annual_pct", 12.0)),
        format="%.2f",
        key="discount_rate_annual_pct",
    )
    repeat_tma = c2.checkbox(
        "Na TIRM, deseja repetir a TMA como taxa de reinvestimento?",
        value=bool(st.session_state.get("reinvest_repeat_tma", True)),
        key="reinvest_repeat_tma",
    )

    if repeat_tma:
        reinvest_annual_pct = float(discount_annual_pct)
        st.session_state["reinvest_rate_annual_pct"] = reinvest_annual_pct
        c2.number_input(
            "Taxa de reinvestimento para TIRM ao ano (%)",
            min_value=0.0,
            step=0.1,
            value=float(reinvest_annual_pct),
            format="%.2f",
            key="reinvest_rate_annual_pct_view",
            disabled=True,
        )
    else:
        reinvest_annual_pct = c2.number_input(
            "Taxa de reinvestimento para TIRM ao ano (%)",
            min_value=0.0,
            step=0.1,
            value=float(st.session_state.get("reinvest_rate_annual_pct", float(discount_annual_pct))),
            format="%.2f",
            key="reinvest_rate_annual_pct",
        )

    discount = annual_rate_percent_to_monthly_decimal(discount_annual_pct)
    reinvest = annual_rate_percent_to_monthly_decimal(reinvest_annual_pct)
    st.session_state["discount_rate"] = discount
    st.session_state["reinvest_rate"] = reinvest
    st.caption(f"Taxa mensal equivalente (TMA): {discount:.4%} | Taxa mensal equivalente (reinvestimento TIRM): {reinvest:.4%}")

    res = calculate_scenario(sid)
    v = calc_viability(sid, discount, reinvest)

    st.markdown("### Resumo simples")
    c1, c2 = st.columns(2)
    c1.metric("VPL (Valor Presente Líquido)", f"R$ {v['vpl']:,.2f}")
    c2.metric("Payback simples", "Não recupera" if pd.isna(v["payback"]) else f"{int(v['payback'])} meses")
    st.metric("Payback descontado", "Não recupera" if pd.isna(v["payback_discounted"]) else f"{int(v['payback_discounted'])} meses")

    with st.expander("Avançado"):
        st.metric("TIR (Taxa Interna de Retorno)", "N/A" if pd.isna(v["tir"]) else f"{v['tir']:.2%}")
        st.metric("TIRM (Taxa Interna de Retorno Modificada)", "N/A" if pd.isna(v["tirm"]) else f"{v['tirm']:.2%}")

    st.markdown("### Margem de contribuição e ponto de equilíbrio")
    dre = res["dre_monthly"]
    mc_total = float(dre["Margem de contribuição"].sum()) if not dre.empty else 0.0
    fixed_total = float(
        pd.DataFrame(st.session_state.get("fixed_costs", [])).get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()
    ) + float(
        pd.DataFrame(st.session_state.get("fixed_expenses", [])).get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()
    )

    m1, m2 = st.columns(2)
    m1.metric("MC total", f"R$ {mc_total:,.2f}")
    m2.metric("Ponto de equilíbrio (receita)", "N/A" if pd.isna(res["break_even_revenue"]) else f"R$ {res['break_even_revenue']:,.2f}")

    mix_rows = []
    qty_total = 0.0
    weighted_mc_unit = 0.0
    scenario = st.session_state["scenarios"][sid]
    for item in st.session_state["items"]:
        iid = item["id"]
        mc_unit = unit_metrics(item, scenario)["mc_u"]
        qty_item = float(np.sum(scenario.get("quantities", {}).get(iid, [])))
        qty_total += qty_item
        mix_rows.append(
            {
                "Produto/Serviço": item["name"],
                "Unidade": item["unit"],
                "MC unitária": mc_unit,
                "Quantidade total projetada": qty_item,
            }
        )

    for row in mix_rows:
        mix_qty = (row["Quantidade total projetada"] / qty_total) if qty_total > 0 else np.nan
        row["Proporção do mix (quantidade)"] = mix_qty
        weighted_mc_unit += row["MC unitária"] * (mix_qty if pd.notna(mix_qty) else 0.0)

    be_total_qty = (fixed_total / weighted_mc_unit) if weighted_mc_unit > 0 else np.nan
    for row in mix_rows:
        if pd.notna(be_total_qty) and pd.notna(row["Proporção do mix (quantidade)"]):
            row["PE quantidade (mensal)"] = be_total_qty * row["Proporção do mix (quantidade)"]
            row["Proporção no PE (quantidade)"] = row["PE quantidade (mensal)"] / be_total_qty if be_total_qty > 0 else np.nan
        else:
            row["PE quantidade (mensal)"] = np.nan
            row["Proporção no PE (quantidade)"] = np.nan

    if mix_rows:
        st.dataframe(
            pd.DataFrame(mix_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "MC unitária": st.column_config.NumberColumn(format="R$ %.2f"),
                "Quantidade total projetada": st.column_config.NumberColumn(format="%.2f"),
                "Proporção do mix (quantidade)": st.column_config.ProgressColumn(format="%.2f%%", min_value=0.0, max_value=1.0),
                "PE quantidade (mensal)": st.column_config.NumberColumn(format="%.2f"),
                "Proporção no PE (quantidade)": st.column_config.ProgressColumn(format="%.2f%%", min_value=0.0, max_value=1.0),
            },
        )
        st.caption(
            "O ponto de equilíbrio em quantidade foi distribuído conforme o mix projetado de quantidades. "
            "Assim, a proporção no PE mostra quanto cada produto representa do total necessário para cobrir os fixos."
        )

    st.markdown("### Quadros de apoio às análises")
    if st.checkbox("Exibir quadro base de VPL/TIR/TIRM/Payback", key="show_viability_base_table"):
        base_viab = res["fc_monthly"][["Mês", "Caixa Líquido do Mês"]].copy()
        base_viab["Fluxo descontado (TMA)"] = base_viab["Caixa Líquido do Mês"] / ((1 + discount) ** base_viab["Mês"])
        base_viab["Acumulado simples"] = base_viab["Caixa Líquido do Mês"].cumsum()
        base_viab["Acumulado descontado"] = base_viab["Fluxo descontado (TMA)"].cumsum()
        st.dataframe(base_viab, use_container_width=True, hide_index=True)

    if st.checkbox("Exibir quadro base de MC e Ponto de Equilíbrio", key="show_mc_pe_base_table"):
        base_mc = dre[["Mês", "Receita líquida", "Custos variáveis", "Despesas variáveis", "Margem de contribuição"]].copy()
        st.dataframe(base_mc, use_container_width=True, hide_index=True)

    if st.checkbox("Exibir quadro detalhado de fluxo de caixa mensal", key="show_cashflow_detail_table"):
        st.dataframe(res["fc_monthly"], use_container_width=True, hide_index=True)
    render_next(7)


def step8() -> None:
    header(8, "Por fim, veja como o seu modelo aparece em demonstrativos. A DRE (Demonstração do Resultado do Exercício) é por competência (o que foi vendido/consumido no mês). O Fluxo de Caixa é por caixa (o que entrou/saiu de dinheiro no mês).")
    sid = st.session_state["current_scenario_id"]
    res = calculate_scenario(sid)

    st.markdown("### Fluxo de Caixa Anual (regime de caixa)")
    st.dataframe(res["fc_annual"], use_container_width=True, hide_index=True)

    st.markdown("### DRE (Demonstração do Resultado do Exercício) — Mensal")
    st.dataframe(res["dre_monthly"], use_container_width=True, hide_index=True)

    st.markdown("### DRE (Demonstração do Resultado do Exercício) — Anual")
    st.dataframe(res["dre_annual"], use_container_width=True, hide_index=True)

    if st.button("Voltar para a Etapa 1", key="back_to_step_1"):
        st.session_state["step"] = 1
        st.rerun()



def step9() -> None:
    header(9, "Nesta etapa, você cria cenários alternativos para analisar a sensibilidade dos resultados em relação a mudanças nas premissas.")

    ensure_item_consistency()
    if not st.session_state["items"]:
        st.warning("Cadastre ao menos 1 item na Etapa 1.")
        return

    sid = st.session_state["current_scenario_id"]
    base_scenario = st.session_state["scenarios"][sid]

    st.markdown("### Cenários Alternativos")
    alt_scenarios = st.session_state.setdefault("sensitivity_scenarios", [])

    if st.button("Adicionar Cenário Alternativo", key="add_sensitivity_scenario"):
        alt_scenarios.append({
            "name": f"Cenário Alternativo {len(alt_scenarios)+1}",
            "selected_changes": [],
            "qty_delta_pct": 0.0,
            "mix_changes": {item["id"]: 0.0 for item in st.session_state["items"]},
            "price_pct": {item["id"]: 0.0 for item in st.session_state["items"]},
            "var_pct": {item["id"]: 0.0 for item in st.session_state["items"]},
            "results": None,
        })
        st.rerun()

    options = [
        "Variação na quantidade vendida",
        "Alteração na proporção de vendas entre os produtos",
        "Variação percentual no preço dos produtos",
        "Variação percentual nos custos e despesas variáveis",
    ]

    for idx, alt in enumerate(alt_scenarios):
        with st.container(border=True):
            st.markdown(f"#### {alt['name']}")
            alt["name"] = st.text_input("Nome do cenário", value=alt.get("name", f"Cenário Alternativo {idx+1}"), key=f"sens_name_{idx}")
            selected = st.multiselect(
                "Você deseja elaborar um cenário com base em:",
                options=options,
                default=alt.get("selected_changes", []),
                key=f"sens_opts_{idx}",
            )
            alt["selected_changes"] = selected

            if options[0] in selected:
                st.caption("Informe uma única variação: positiva (para mais) ou negativa (para menos).")
                alt["qty_delta_pct"] = st.number_input(
                    "Variação na quantidade vendida (%)",
                    value=float(alt.get("qty_delta_pct", 0.0)),
                    step=1.0,
                    key=f"sens_qty_delta_{idx}",
                )

            if options[1] in selected and len(st.session_state["items"]) > 1:
                st.caption("Informe o ajuste percentual da participação de cada item no mix de vendas.")
                for item in st.session_state["items"]:
                    iid = item["id"]
                    alt.setdefault("mix_changes", {}).setdefault(iid, 0.0)
                    alt["mix_changes"][iid] = st.number_input(
                        f"{item['name']} - alteração na proporção (%)",
                        value=float(alt["mix_changes"].get(iid, 0.0)),
                        step=1.0,
                        key=f"sens_mix_{idx}_{iid}",
                    )
            elif options[1] in selected:
                st.info("A alteração de proporção entre produtos exige ao menos 2 itens cadastrados.")

            if options[2] in selected:
                for item in st.session_state["items"]:
                    iid = item["id"]
                    alt.setdefault("price_pct", {}).setdefault(iid, 0.0)
                    alt["price_pct"][iid] = st.number_input(
                        f"{item['name']} - variação no preço (%)",
                        value=float(alt["price_pct"].get(iid, 0.0)),
                        step=1.0,
                        key=f"sens_price_{idx}_{iid}",
                    )

            if options[3] in selected:
                for item in st.session_state["items"]:
                    iid = item["id"]
                    alt.setdefault("var_pct", {}).setdefault(iid, 0.0)
                    alt["var_pct"][iid] = st.number_input(
                        f"{item['name']} - variação em custos/despesas variáveis (%)",
                        value=float(alt["var_pct"].get(iid, 0.0)),
                        step=1.0,
                        key=f"sens_var_{idx}_{iid}",
                    )

            if st.button("Gerar resultados do cenário", key=f"gen_sensitivity_{idx}"):
                temp_scenario = deepcopy(base_scenario)
                horizon = int(temp_scenario.get("horizon_months", 12) or 12)

                for item in st.session_state["items"]:
                    iid = item["id"]
                    base_qty = np.array(temp_scenario.get("quantities", {}).get(iid, [0.0] * horizon), dtype=float)
                    if options[0] in selected:
                        delta = float(alt.get("qty_delta_pct", 0.0)) / 100
                        base_qty = base_qty * max(0.0, (1 + delta))

                    if options[1] in selected and len(st.session_state["items"]) > 1:
                        mix = float(alt.get("mix_changes", {}).get(iid, 0.0)) / 100
                        base_qty = base_qty * max(0.0, (1 + mix))

                    temp_scenario["quantities"][iid] = base_qty.tolist()

                    if options[2] in selected:
                        base_price = float(temp_scenario["overrides"]["price"].get(iid, st.session_state["unit_economics"][iid].get("price", 0.0)) or 0.0)
                        temp_scenario["overrides"]["price"][iid] = base_price * (1 + float(alt.get("price_pct", {}).get(iid, 0.0)) / 100)

                modified_unit_econ = deepcopy(st.session_state["unit_economics"])
                if options[3] in selected:
                    for item in st.session_state["items"]:
                        iid = item["id"]
                        factor = 1 + float(alt.get("var_pct", {}).get(iid, 0.0)) / 100
                        for row in modified_unit_econ[iid].get("variable_costs", []):
                            row["unit_value"] = float(row.get("unit_value", 0.0) or 0.0) * factor
                        for row in modified_unit_econ[iid].get("variable_expenses", []):
                            row["unit_value"] = float(row.get("unit_value", 0.0) or 0.0) * factor

                temp_id = f"_sensitivity_{idx}"
                original_scenario = st.session_state["scenarios"].get(temp_id)
                original_econ = st.session_state["unit_economics"]
                st.session_state["scenarios"][temp_id] = temp_scenario
                st.session_state["unit_economics"] = modified_unit_econ
                try:
                    result = calculate_scenario(temp_id)
                    viab = calc_viability(temp_id, float(st.session_state.get("discount_rate", 0.01)), float(st.session_state.get("reinvest_rate", st.session_state.get("discount_rate", 0.01))))
                finally:
                    if original_scenario is None:
                        st.session_state["scenarios"].pop(temp_id, None)
                    else:
                        st.session_state["scenarios"][temp_id] = original_scenario
                    st.session_state["unit_economics"] = original_econ

                mix_rows = []
                for item in st.session_state["items"]:
                    iid = item["id"]
                    metrics = unit_metrics(item, temp_scenario)
                    qty_total = float(np.sum(temp_scenario.get("quantities", {}).get(iid, [])))
                    mix_rows.append(
                        {
                            "Produto/Serviço": item["name"],
                            "MC por produto": metrics["mc_u"],
                            "PE em quantidade": (result["break_even_revenue"] / metrics["price"]) if metrics["price"] > 0 and pd.notna(result["break_even_revenue"]) else np.nan,
                            "PE em receita": result["break_even_revenue"],
                            "Quantidade projetada": qty_total,
                        }
                    )

                alt["results"] = {
                    "mix_df": pd.DataFrame(mix_rows),
                    "vpl": viab["vpl"],
                    "tir": viab["tir"],
                    "tirm": viab["tirm"],
                    "payback": viab["payback"],
                    "payback_discounted": viab["payback_discounted"],
                }

            if alt.get("results") is not None:
                st.markdown("**Resultados do cenário**")
                st.dataframe(alt["results"]["mix_df"], use_container_width=True, hide_index=True)
                c1, c2, c3 = st.columns(3)
                c1.metric("VPL", f"R$ {alt['results']['vpl']:,.2f}")
                c2.metric("TIR", "N/A" if pd.isna(alt["results"]["tir"]) else f"{alt['results']['tir']:.2%}")
                c3.metric("TIRM", "N/A" if pd.isna(alt["results"]["tirm"]) else f"{alt['results']['tirm']:.2%}")
                c4, c5 = st.columns(2)
                c4.metric("Payback", "Não recupera" if pd.isna(alt["results"]["payback"]) else f"{int(alt['results']['payback'])} meses")
                c5.metric("Payback descontado", "Não recupera" if pd.isna(alt["results"]["payback_discounted"]) else f"{int(alt['results']['payback_discounted'])} meses")

            if st.button("Remover cenário", key=f"remove_sensitivity_{idx}"):
                alt_scenarios.pop(idx)
                st.rerun()

def main() -> None:
    st.set_page_config(page_title="Financial Planner", layout="wide")
    st.title("Financial Planner para startups")
    init_state()
    ensure_item_consistency()
    render_nav()

    step_fn = {
        1: step1,
        2: step2,
        3: step3,
        4: step4,
        5: step5,
        6: step6,
        7: step7,
        8: step8,
        9: step9,
    }
    step_fn.get(st.session_state["step"], step1)()


if __name__ == "__main__":
    main()
