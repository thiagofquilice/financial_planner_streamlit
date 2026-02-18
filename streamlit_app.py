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
    "Projeção de volume, cenários, equilíbrio e alavancagem",
    "Investimentos (CAPEX)",
    "Fluxo de caixa mensal e necessidade de caixa",
    "Viabilidade: VPL, TIR, TIRM, Payback",
    "Demonstrativos (Competência e Caixa)",
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
    st.session_state.setdefault("investments", [{"item": "", "category": "CAPEX", "month": 1, "value": 0.0, "payment": "À vista", "installments": 1}])

    if "scenarios" not in st.session_state:
        st.session_state["scenarios"] = {"base": default_scenario("Cenário 1 — Base", [])}
    if "current_scenario_id" not in st.session_state:
        st.session_state["current_scenario_id"] = "base"

    st.session_state.setdefault("cashflow", {})
    st.session_state.setdefault("viability", {})
    st.session_state.setdefault("statements", {})


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
    items = st.session_state["items"]

    fixed_cost_df = pd.DataFrame(st.session_state.get("fixed_costs", []))
    fixed_exp_df = pd.DataFrame(st.session_state.get("fixed_expenses", []))
    fixed_total = float(fixed_cost_df.get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()) + float(
        fixed_exp_df.get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()
    )

    operational_cash = np.zeros(horizon)
    investment_cash = np.zeros(horizon)

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
            recv_month = m_idx + payment_shift_month(recv_days)
            pay_month = m_idx + payment_shift_month(pay_days)
            if recv_month < horizon:
                received += gross_i
                operational_cash[recv_month] += gross_i
            if pay_month < horizon:
                paid_var += (var_cost_i + var_exp_i)
                operational_cash[pay_month] -= var_cost_i + var_exp_i

        # tributo pago no mesmo mês da competência
        operational_cash[m_idx] -= taxes

        # fixos com prazo
        for _, row in fixed_cost_df.iterrows():
            pm = m_idx + payment_shift_month(int(row.get("pay_days", 0) or 0))
            if pm < horizon:
                operational_cash[pm] -= float(row.get("monthly_value", 0.0) or 0.0)
        for _, row in fixed_exp_df.iterrows():
            pm = m_idx + payment_shift_month(int(row.get("pay_days", 0) or 0))
            if pm < horizon:
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
        month = int(row.get("month", 1) or 1) - 1
        value = float(row.get("value", 0.0) or 0.0)
        if month < 0 or month >= horizon or value <= 0:
            continue
        if str(row.get("payment", "À vista")) == "Parcelado":
            inst = max(1, int(row.get("installments", 1) or 1))
            parcel = value / inst
            for k in range(inst):
                pm = month + k
                if pm < horizon:
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
            "Mês": months,
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

    # GAO
    gao_series = []
    for _, row in dre_monthly.iterrows():
        ebit = float(row["EBIT"])
        mc = float(row["Margem de contribuição"])
        if ebit > 1e-6:
            gao_series.append(mc / ebit)
        else:
            gao_series.append(np.nan)
    dre_monthly["GAO"] = gao_series

    res = {
        "dre_monthly": dre_monthly,
        "dre_annual": dre_annual,
        "fc_monthly": fc_monthly,
        "fc_annual": fc_annual,
        "mc_consolid_pct": mc_consolid_pct,
        "break_even_revenue": pe_revenue,
        "valley": float(accumulated[valley_idx]) if len(accumulated) else 0.0,
        "valley_month": int(months[valley_idx]) if len(months) else 1,
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
    months = np.arange(1, len(flows) + 1)

    vpl = float(np.sum(flows / ((1 + discount_m) ** months)))

    try:
        tir = float(np.irr(flows))
    except Exception:
        tir = np.nan

    pos = flows[flows > 0]
    neg = flows[flows < 0]
    if len(neg) > 0 and len(pos) > 0:
        pv_neg = np.sum(neg / ((1 + discount_m) ** np.arange(1, len(neg) + 1)))
        fv_pos = np.sum(pos * ((1 + reinvest_m) ** np.arange(len(pos), 0, -1)))
        tirm = ((-fv_pos / pv_neg) ** (1 / len(flows))) - 1 if pv_neg < 0 else np.nan
    else:
        tirm = np.nan

    cum = np.cumsum(flows)
    payback = next((i + 1 for i, v in enumerate(cum) if v >= 0), np.nan)

    disc_cum = np.cumsum(flows / ((1 + discount_m) ** months))
    payback_disc = next((i + 1 for i, v in enumerate(disc_cum) if v >= 0), np.nan)

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

    st.write("**Itens cadastrados:**")
    if st.session_state["items"]:
        st.table(pd.DataFrame(st.session_state["items"])[["name", "unit"]].rename(columns={"name": "Produto/serviço", "unit": "Unidade"}))

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
        q.append(curr)
        curr = curr * (1 + growth)
    scenario["quantities"][item_id] = q


def step4() -> None:
    header(4, "Aqui você projeta quantas unidades vai vender ao longo do tempo. Com isso, o app calcula o ponto de equilíbrio e mostra o efeito da alavancagem operacional: como a estrutura fixa pode amplificar ganhos (ou perdas) conforme o volume muda.")
    with st.expander("Instruções"):
        st.write(
            "- Projeção de volume é quantas unidades você espera vender por mês.\n\n"
            "- Cenários servem para comparar hipóteses: base, otimista, conservador.\n\n"
            "- Ponto de equilíbrio é o nível de vendas em que o resultado operacional fica zero.\n\n"
            "- A alavancagem operacional aumenta quando seus fixos são altos: o resultado melhora (ou piora) mais rápido com o volume."
        )

    ensure_item_consistency()
    if not st.session_state["items"]:
        st.warning("Cadastre ao menos 1 item na Etapa 1.")
        render_next(4)
        return

    scenarios = st.session_state["scenarios"]
    sids = list(scenarios.keys())
    labels = [f"{sid} - {scenarios[sid]['name']}" for sid in sids]
    selected_label = st.selectbox("Cenário ativo", labels, index=sids.index(st.session_state["current_scenario_id"]) if st.session_state["current_scenario_id"] in sids else 0)
    st.session_state["current_scenario_id"] = selected_label.split(" - ")[0]
    sid = st.session_state["current_scenario_id"]
    scenario = scenarios[sid]

    c1, c2 = st.columns(2)
    if c1.button("Criar cenário do zero"):
        new_id = f"scenario_{len(scenarios)+1}"
        scenarios[new_id] = default_scenario(f"Cenário {len(scenarios)+1}", [i["id"] for i in st.session_state["items"]])
        st.session_state["current_scenario_id"] = new_id
        st.rerun()
    if c2.button("Clonar cenário atual"):
        new_id = f"scenario_{len(scenarios)+1}"
        scenarios[new_id] = deepcopy(scenario)
        scenarios[new_id]["name"] = f"Cenário {len(scenarios)+1} (clone)"
        st.session_state["current_scenario_id"] = new_id
        st.rerun()

    scenario["name"] = st.text_input("Nome do cenário", value=scenario.get("name", sid), key=f"scenario_name_{sid}")
    horizon = st.selectbox("Tempo de projeção (meses)", [12, 24, 36, 60], index=[12, 24, 36, 60].index(int(scenario.get("horizon_months", 12))), key=f"horizon_{sid}")
    scenario["horizon_months"] = horizon
    for iid in scenario["quantities"]:
        scenario["quantities"][iid] = resize_series(scenario["quantities"][iid], horizon)

    scenario["projection_mode"] = st.radio("Modo para quantidades", ["manual", "base_growth"], format_func=lambda x: "Inserir manualmente mês a mês" if x == "manual" else "Definir quantidade base e taxa de crescimento mensal", horizontal=True, key=f"mode_{sid}")

    for item in st.session_state["items"]:
        iid = item["id"]
        st.markdown(f"#### {item['name']}")
        if scenario["projection_mode"] == "base_growth":
            b1, b2, b3 = st.columns([2, 2, 1])
            scenario["base_growth"][iid]["base"] = b1.number_input("Quantidade mês 1", min_value=0.0, step=1.0, value=float(scenario["base_growth"][iid].get("base", 0.0)), key=f"base_{sid}_{iid}")
            scenario["base_growth"][iid]["growth"] = b2.number_input("Taxa de crescimento mensal", min_value=-0.99, step=0.01, value=float(scenario["base_growth"][iid].get("growth", 0.0)), format="%.4f", key=f"growth_{sid}_{iid}")
            if b3.button("Gerar série", key=f"gen_{sid}_{iid}"):
                regenerate_quantities(scenario, iid)

        qdf = pd.DataFrame({"Mês": range(1, horizon + 1), "Quantidade": scenario["quantities"][iid]})
        qedit = st.data_editor(qdf, hide_index=True, key=f"qtable_{sid}_{iid}", use_container_width=True, num_rows="fixed")
        scenario["quantities"][iid] = qedit["Quantidade"].fillna(0).astype(float).tolist()

        with st.expander(f"Overrides do cenário para {item['name']} (opcional)"):
            ov = scenario["overrides"]
            ov["price"][iid] = st.number_input("Preço override", min_value=0.0, step=0.01, value=float(ov["price"].get(iid, st.session_state["unit_economics"][iid].get("price", 0.0))), key=f"ov_price_{sid}_{iid}")
            ov["tax_rate"][iid] = st.number_input("Alíquota override", min_value=0.0, max_value=1.0, step=0.005, value=float(ov["tax_rate"].get(iid, st.session_state["unit_economics"][iid].get("tax_rate", 0.0))), format="%.4f", key=f"ov_tax_{sid}_{iid}")
            ov["receive_days"][iid] = st.number_input("Prazo recebimento override (dias)", min_value=0, step=1, value=int(ov["receive_days"].get(iid, st.session_state["unit_economics"][iid].get("receive_days", 0))), key=f"ov_recv_{sid}_{iid}")
            ov["pay_days"][iid] = st.number_input("Prazo pagamento override (dias)", min_value=0, step=1, value=int(ov["pay_days"].get(iid, st.session_state["unit_economics"][iid].get("pay_days", 0))), key=f"ov_pay_{sid}_{iid}")

    result = calculate_scenario(sid)
    st.metric("MC consolidada (%)", f"{result['mc_consolid_pct']:.2%}")
    if pd.notna(result["break_even_revenue"]):
        st.metric("Ponto de Equilíbrio em Receita (mensal)", f"R$ {result['break_even_revenue']:,.2f}")
    else:
        st.info("Ponto de equilíbrio em receita indisponível enquanto a margem de contribuição consolidada for zero ou negativa.")

    if len(st.session_state["items"]) == 1:
        item = st.session_state["items"][0]
        mc_u = unit_metrics(item, scenario)["mc_u"]
        fixed_total = pd.DataFrame(st.session_state["fixed_costs"]).get("monthly_value", pd.Series(dtype=float)).fillna(0).sum() + pd.DataFrame(st.session_state["fixed_expenses"]).get("monthly_value", pd.Series(dtype=float)).fillna(0).sum()
        if mc_u > 0:
            st.metric("Ponto de Equilíbrio em Unidades", f"{fixed_total / mc_u:,.2f} {item['unit']}")

    st.markdown("### Grau de Alavancagem Operacional (GAO)")
    gao_df = result["dre_monthly"][["Mês", "EBIT", "GAO"]].copy()
    if gao_df["GAO"].notna().any():
        st.dataframe(gao_df, use_container_width=True)
    else:
        st.info("GAO não é informativa quando o resultado operacional (EBIT) está próximo de zero.")
    render_next(4)


def step5() -> None:
    header(5, "Agora registre os investimentos necessários para colocar a operação de pé (equipamentos, desenvolvimento, implantação). Eles entram no fluxo de caixa como saídas de investimento.")

    df = pd.DataFrame(st.session_state["investments"])
    cfg = {
        "item": st.column_config.TextColumn("Item"),
        "category": st.column_config.SelectboxColumn("Categoria", options=["CAPEX", "Implementação", "Outros"]),
        "month": st.column_config.NumberColumn("Mês de realização", min_value=1, step=1),
        "value": st.column_config.NumberColumn("Valor", min_value=0.0, step=0.01, format="R$ %.2f"),
        "payment": st.column_config.SelectboxColumn("Forma de pagamento", options=["À vista", "Parcelado"]),
        "installments": st.column_config.NumberColumn("Número de parcelas", min_value=1, step=1),
    }
    edited = st.data_editor(df, key="investments_table", num_rows="dynamic", use_container_width=True, hide_index=True, column_config=cfg)
    st.session_state["investments"] = edited.to_dict("records")
    render_next(5)


def step6() -> None:
    header(6, "O fluxo de caixa mostra quando o dinheiro entra e sai de verdade. O app destaca o pior momento do caixa acumulado, que costuma indicar a necessidade de caixa para sustentar a operação até ela se pagar.")

    sid = st.session_state["current_scenario_id"]
    res = calculate_scenario(sid)
    fc = res["fc_monthly"].copy()
    st.dataframe(fc[["Mês", "Caixa Operacional", "Caixa de Investimento", "Caixa Líquido do Mês", "Caixa Acumulado"]], use_container_width=True)
    st.error(
        f"Necessidade de caixa (pico de déficit operacional): R$ {abs(min(0, res['valley'])):,.2f} no mês {res['valley_month']}."
    )
    st.caption("Definição: o menor valor do caixa acumulado ao longo do período; indica quanto seria necessário financiar para atravessar o período mais negativo.")
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
    discount = c1.number_input("Taxa mínima desejada (mensal)", min_value=0.0, step=0.001, value=0.01, format="%.4f", key="discount_rate")
    reinvest = c2.number_input("Taxa de reinvestimento para TIRM (Taxa Interna de Retorno Modificada)", min_value=0.0, step=0.001, value=float(discount), format="%.4f", key="reinvest_rate")

    v = calc_viability(sid, discount, reinvest)

    st.markdown("### Resumo simples")
    c1, c2 = st.columns(2)
    c1.metric("VPL (Valor Presente Líquido)", f"R$ {v['vpl']:,.2f}")
    c2.metric("Payback simples", "Não recupera" if pd.isna(v["payback"]) else f"{int(v['payback'])} meses")
    st.metric("Payback descontado", "Não recupera" if pd.isna(v["payback_discounted"]) else f"{int(v['payback_discounted'])} meses")

    with st.expander("Avançado"):
        st.metric("TIR (Taxa Interna de Retorno)", "N/A" if pd.isna(v["tir"]) else f"{v['tir']:.2%}")
        st.metric("TIRM (Taxa Interna de Retorno Modificada)", "N/A" if pd.isna(v["tirm"]) else f"{v['tirm']:.2%}")
    render_next(7)


def step8() -> None:
    header(8, "Por fim, veja como o seu modelo aparece em demonstrativos. A DRE (Demonstração do Resultado do Exercício) é por competência (o que foi vendido/consumido no mês). O Fluxo de Caixa é por caixa (o que entrou/saiu de dinheiro no mês).")
    sid = st.session_state["current_scenario_id"]
    res = calculate_scenario(sid)

    st.markdown("### Fluxo de Caixa Anual (regime de caixa)")
    st.dataframe(res["fc_annual"], use_container_width=True)

    st.markdown("### DRE (Demonstração do Resultado do Exercício) — Mensal")
    st.dataframe(res["dre_monthly"], use_container_width=True)

    st.markdown("### DRE (Demonstração do Resultado do Exercício) — Anual")
    st.dataframe(res["dre_annual"], use_container_width=True)

    if st.button("Voltar para a Etapa 1", key="back_to_step_1"):
        st.session_state["step"] = 1
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
    }
    step_fn.get(st.session_state["step"], step1)()


if __name__ == "__main__":
    main()
