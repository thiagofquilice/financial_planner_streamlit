"""
Streamlit Financial Planning Wizard

This script implements a simplified version of the multi‑step wizard found in
the original Node/Express application using Python and Streamlit. The goal
is to provide an easy‑to‑run interface that guides the user through
collecting project details, revenue structure, direct costs, operating
expenses and investments, and then summarizes the results.  A simple PDF
and Excel report can be generated from the collected data.  It is not a
drop‑in replacement for the original app but demonstrates how the same
workflow could be accomplished with the Python ecosystem.

Dependencies:

    pip install streamlit pandas numpy reportlab xlsxwriter

To run locally:

    streamlit run streamlit_app.py

"""

import io
import json
from typing import List, Dict, Tuple, Optional, Any

import numpy as np
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

GOVERNANCE_QUESTIONS = [
    {
        "title": "Pergunta 1 – Alinhamento de expectativas entre os fundadores",
        "question": "Em relação às expectativas de cada sócio sobre o futuro da startup (propósito, tamanho desejado, estilo de gestão, possibilidade de venda/IPO etc.), qual alternativa descreve melhor a sua situação?",
        "options": {
            "a": "Nunca conversamos seriamente sobre isso; cada um tem sua visão e seguimos “tocando”.",
            "b": "Já conversamos de forma informal, mas não temos nada estruturado ou registrado.",
            "c": "Fizemos uma conversa estruturada, alinhamos expectativas e registramos os principais pontos em algum documento (ex.: ata, e-mail, anotação compartilhada).",
            "d": "Além de alinharmos expectativas e registrarmos, revisitamos esse alinhamento periodicamente e o usamos como base para decisões estratégicas.",
        },
        "recommendations": {
            "a": "Vocês ainda não alinharam as expectativas sobre futuro da startup. É importante marcar uma conversa estruturada para discutir propósito, ambição de crescimento, possibilidade de venda/IPO, nível de risco aceitável e estilo de gestão. Sem esse alinhamento, aumenta muito o risco de conflitos entre sócios no curto e médio prazo.",
            "b": "Vocês já deram um primeiro passo ao falar do assunto de forma informal, mas o próximo movimento é formalizar essa conversa. Registrem os principais pontos em um documento simples (ata, e-mail compartilhado ou nota em drive) para que todos tenham clareza e possam revisitar esses combinados no futuro.",
            "c": "Vocês já têm um bom nível de alinhamento, com conversas estruturadas e registro das expectativas. O passo seguinte é definir momentos periódicos (por exemplo, a cada 6 ou 12 meses) para revisar esses combinados, garantindo que as expectativas continuem convergentes conforme o negócio evolui.",
            "d": "Vocês estão em um nível avançado de alinhamento para a fase de ideação, revisitando as expectativas e usando-as como base para decisões estratégicas. Mantenham esse hábito e considerem incorporar parte desse alinhamento em documentos societários formais quando a empresa for constituída.",
        },
    },
    {
        "title": "Pergunta 2 – Capacidade financeira pessoal e “perda suportável”",
        "question": "Como os fundadores tratam a questão da capacidade financeira pessoal para sustentar-se enquanto a startup não gera renda suficiente?",
        "options": {
            "a": "Nunca falamos sobre isso; cada um “se vira” como pode.",
            "b": "Sabemos, por alto, que alguns têm mais ou menos fôlego financeiro, mas não tratamos disso de forma aberta.",
            "c": "Conversamos abertamente sobre o fôlego financeiro de cada sócio, mas não usamos isso formalmente no planejamento do negócio.",
            "d": "Conversamos abertamente, estimamos por quanto tempo cada um consegue se manter e usamos essa informação para planejar o ritmo da startup e decisões-chave.",
        },
        "recommendations": {
            "a": "A capacidade financeira pessoal dos(as) fundadores(as) não está sendo considerada, o que é um risco importante. Vocês precisam conversar abertamente sobre o fôlego financeiro de cada pessoa, estimar quanto tempo cada um consegue se manter e ajustar o plano da startup (ritmo, dedicação, prazos) a essa realidade.",
            "b": "Vocês têm alguma noção do fôlego financeiro de cada sócio, mas o tema ainda não é tratado de forma estruturada. Vale organizar uma conversa específica para levantar números mais concretos, estimar o “runway pessoal” e usar isso como insumo para o planejamento de metas, captação e mudanças de fase do negócio.",
            "c": "A abertura para falar de fôlego financeiro já existe, o que é ótimo. O próximo passo é incorporar esses dados de forma explícita no planejamento da startup – por exemplo, definindo prazos para validar hipóteses, pontos de decisão (pivotar/encerrar/capitalizar) e eventuais necessidades de complementação de renda.",
            "d": "Vocês utilizam a capacidade financeira pessoal como um insumo real de planejamento, o que é uma boa prática de governança. Continuem revisando esses números periodicamente, especialmente em momentos de mudança de estratégia ou de aumento de dedicação, para evitar surpresas e desgastes entre os(as) fundadores(as).",
        },
    },
    {
        "title": "Pergunta 3 – Formas de contribuição de cada sócio (capital, tempo e conhecimento)",
        "question": "Como está definida hoje a forma de contribuição de cada sócio (capital financeiro, tempo, conhecimentos, rede de contatos etc.)?",
        "options": {
            "a": "Não temos definição; cada um contribui como consegue, sem combinação específica.",
            "b": "Já conversamos, mas de maneira genérica, sem clareza de quanto tempo ou dinheiro cada um colocará.",
            "c": "Definimos e registramos quanto cada sócio contribuirá (tempo, capital, conhecimento), mas ainda não revisamos essas definições à medida que o projeto avança.",
            "d": "Definimos, registramos e revisamos periodicamente a contribuição de cada sócio, ajustando quando alguém não consegue cumprir o combinado.",
        },
        "recommendations": {
            "a": "Hoje não há clareza sobre quem contribui com o quê, o que pode gerar sensação de injustiça e conflitos. É importante definir explicitamente as contribuições esperadas de cada sócio (tempo semanal, capital financeiro, conhecimento, rede de contatos) e registrar esse combinado, mesmo em um documento simples.",
            "b": "Vocês já conversaram sobre contribuições, mas ainda de forma genérica. O próximo passo é transformar essa conversa em compromissos mais objetivos: horas semanais dedicadas, valores de aportes, responsabilidades-chave. Colocar isso por escrito ajuda a alinhar expectativas e a cobrar de forma mais transparente.",
            "c": "Vocês definiram e registraram contribuições, o que é um bom nível de organização. Para evoluir, criem o hábito de revisar essas definições periodicamente (por exemplo, a cada trimestre), ajustando o acordo quando alguém passa a contribuir mais ou menos do que o inicialmente combinado.",
            "d": "A governança sobre contribuições está bem estruturada: definição, registro e revisão periódica. O próximo passo pode ser conectar essas contribuições a instrumentos mais formais (como acordo de sócios e mecanismos de vesting) conforme a empresa avança para fases posteriores.",
        },
    },
    {
        "title": "Pergunta 4 – Participação societária e critérios de divisão do “bolo”",
        "question": "Como vocês definiram (ou pretendem definir) a participação societária entre os fundadores?",
        "options": {
            "a": "A ideia é dividir igualmente entre todos, independentemente de quem executa mais ou aporta recursos.",
            "b": "A divisão considerou quem teve a ideia inicial, mas pouco considerou tempo de dedicação e execução.",
            "c": "A divisão considerou principalmente dedicação, execução e aportes (tempo e dinheiro), e não apenas quem teve a ideia, ainda que o acordo seja mais informal.",
            "d": "A divisão considera dedicação, execução e aportes, está registrada e ligada a condições objetivas (ex.: tempo mínimo de permanência – revesting – e metas).",
        },
        "recommendations": {
            "a": "Dividir a sociedade igualmente por padrão pode parecer justo no início, mas costuma ignorar diferenças de dedicação, responsabilidade e risco assumido. Vale discutir critérios mais objetivos para a divisão societária (tempo de dedicação, execução, aportes de capital) e considerar um modelo que reflita melhor a contribuição de cada pessoa.",
            "b": "Valorizar a ideia inicial é legítimo, mas, na prática, é a execução que cria valor. Seria importante reavaliar a divisão societária para dar mais peso à dedicação, ao trabalho contínuo e aos aportes, reduzindo a concentração de participação apenas em quem “teve a ideia”.",
            "c": "Vocês já basearam a divisão em dedicação e aportes, o que é positivo. O próximo passo é formalizar esse arranjo em documento (e, depois, em contrato social ou acordo de sócios) e avaliar mecanismos de vesting, para que a participação esteja condicionada à permanência e à contribuição ao longo do tempo.",
            "d": "A estrutura societária de vocês está bem alinhada com boas práticas: baseada em contribuição, registrada e atrelada a condições objetivas (como tempo mínimo e metas). Mantenham a disciplina de revisar essas condições quando houver mudanças relevantes na equipe ou na estratégia.",
        },
    },
    {
        "title": "Pergunta 5 – Regras de saída de sócios e entrada de novos",
        "question": "Quais são as regras para saída de um sócio ou entrada de novos sócios?",
        "options": {
            "a": "Não temos nenhuma regra; se alguém quiser sair ou entrar, veremos o que fazer na hora.",
            "b": "Já conversamos sobre possíveis saídas e entradas, mas sem definir valores, prazos ou procedimentos.",
            "c": "Temos regras combinadas (ainda que simples) sobre saída e entrada de sócios, mas não estão documentadas.",
            "d": "Temos regras claras e registradas sobre saída (inclusive cálculo de haveres, prazos e não concorrência) e entrada de novos sócios.",
        },
        "recommendations": {
            "a": "Não ter regras de saída e entrada é um dos maiores riscos de conflito societário. É importante discutir desde já cenários de saída (voluntária, por desempenho, por necessidade pessoal) e de entrada de novos sócios, definindo pelo menos critérios de preço, prazos de pagamento e permanência.",
            "b": "Vocês já perceberam a importância do tema e discutiram possibilidades, mas ainda sem concretizar. O próximo passo é transformar essas conversas em regras mínimas: como será calculado o valor de saída, em quantas parcelas, se haverá carência, se existe cláusula de não concorrência etc., mesmo que de forma simplificada.",
            "c": "As regras de saída e entrada existem na prática, ainda que só na palavra. Para reduzir riscos, vale muito a pena colocá-las por escrito (em e-mail formal ou documento de founders agreement) e, se possível, consultar um(a) advogado(a) para ajustar pontos mais sensíveis.",
            "d": "Ter regras claras e registradas sobre saída e entrada é um grande diferencial em governança, especialmente em startups. Mantenham esse documento vivo, revisando quando houver mudanças relevantes e garantindo que todas as partes compreendem bem os impactos de cada cláusula.",
        },
    },
    {
        "title": "Pergunta 6 – Existência de um acordo de fundadores (founders agreement)",
        "question": "Sobre a formalização das principais combinações entre os fundadores (papéis, participações, regras de saída, sigilo etc.), qual situação melhor descreve vocês?",
        "options": {
            "a": "Não temos nenhum documento entre os fundadores.",
            "b": "Temos apenas mensagens soltas (WhatsApp, e-mails) com algumas decisões, mas nada organizado em documento único.",
            "c": "Temos um documento simples (ex.: 2–5 páginas) que registra papéis, contribuições, participação societária e pontos básicos de saída/entrada.",
            "d": "Temos um founders agreement que, além dos pontos básicos, trata de exclusividade, sigilo, não concorrência e propriedade intelectual.",
        },
        "recommendations": {
            "a": "A ausência total de documento entre fundadores deixa a startup muito exposta a conflitos futuros. Vale criar ao menos um founders agreement simples, registrando papéis, contribuições, participação societária, regras de saída/entrada e princípios de tomada de decisão.",
            "b": "As decisões dispersas em mensagens e e-mails são vulneráveis a interpretações diferentes no futuro. Um passo importante é consolidar esses combinados em um documento único, organizado, que todos leiam, revisem e assinem (mesmo que digitalmente), facilitando a governança do grupo.",
            "c": "Ter um documento simples já é uma boa base de governança. Para avançar, vocês podem incluir temas como propriedade intelectual, confidencialidade, não concorrência e critérios para conflitos, além de revisar o acordo à medida que novas fases do negócio surgirem.",
            "d": "Vocês já possuem um founders agreement bastante completo para a fase de ideação. A recomendação é revisar esse documento periodicamente (ou em eventos de mudança relevante, como entrada de investidor(a) ou de novos sócios) e garantir que ele esteja alinhado ao contrato social e a instrumentos futuros.",
        },
    },
    {
        "title": "Pergunta 7 – Propriedade intelectual e confidencialidade",
        "question": "Como vocês tratam a propriedade intelectual (código, marca, metodologia, design, domínio) e o sigilo sobre o negócio?",
        "options": {
            "a": "Nada foi combinado; cada sócio desenvolve materiais e não está claro de quem é o quê.",
            "b": "Temos um entendimento verbal de que “tudo é da startup”, mas sem nada escrito.",
            "c": "Temos combinado escrito (mesmo que simples) de que toda a propriedade intelectual produzida para o projeto pertence à futura empresa.",
            "d": "Além desse combinado, temos cláusulas de confidencialidade e não concorrência previstas entre os envolvidos.",
        },
        "recommendations": {
            "a": "A falta de clareza sobre quem detém a propriedade intelectual pode gerar disputas sérias mais à frente. É essencial definir, por escrito, que todo código, marca, metodologia, design e domínio ligados ao projeto pertencem à startup (ou à futura pessoa jurídica) e não a um indivíduo isolado.",
            "b": "O entendimento verbal de que “tudo é da startup” é um bom começo, mas frágil juridicamente. Vale redigir um documento simples atribuindo a propriedade intelectual à startup, acompanhado de cláusulas de confidencialidade básicas, evitando problemas quando alguém sair ou quando entrarem investidores.",
            "c": "Vocês já têm um combinado escrito sobre propriedade intelectual, o que é um passo importante. Para fortalecer essa governança, considerem: incluir cláusulas de sigilo e não concorrência, registrar marca e domínio em nome da empresa (ou dos sócios em condomínio até a constituição) e organizar o controle de acesso a repositórios e documentos.",
            "d": "A governança de propriedade intelectual e confidencialidade está bem madura para a fase em que vocês estão. O próximo passo é garantir que essas mesmas práticas se estendam a colaboradores(as), prestadores(as) de serviço e parceiros, usando contratos e políticas consistentes com o que já foi estabelecido entre os fundadores.",
        },
    },
    {
        "title": "Pergunta 8 – Controles mínimos de uso de recursos (caixa e gastos)",
        "question": "Como são controlados hoje os recursos financeiros utilizados na fase de ideação (gastos com domínio, protótipo, viagens, ferramentas etc.)?",
        "options": {
            "a": "Não fazemos nenhum controle; cada um paga um pouco e confiamos na memória.",
            "b": "Temos um controle esporádico (planilha ou anotações), mas sem revisão periódica pelos sócios.",
            "c": "Mantemos um controle simples de entradas e saídas (ex.: planilha de caixa) revisado pelos sócios de tempos em tempos.",
            "d": "Mantemos controle de caixa organizado, revisado periodicamente, com projeções de curto prazo (ex.: próximos 3–6 meses).",
        },
        "recommendations": {
            "a": "Ausência de controle financeiro, mesmo em pequenas quantias, dificulta decisões e gera desconfiança. Um próximo passo simples é criar uma planilha de caixa compartilhada, registrar todas as entradas e saídas e definir uma pessoa responsável por atualizar esses dados regularmente.",
            "b": "Vocês já tentam controlar os gastos, mas de forma irregular. Vale padronizar o uso de uma única planilha ou ferramenta, centralizando as informações e combinando uma revisão periódica (por exemplo, quinzenal ou mensal) em reunião de sócios para analisar o que está sendo gasto.",
            "c": "O controle simples de caixa e a revisão periódica já colocam vocês em um bom patamar de governança financeira para a ideação. Para avançar, adicionem projeções de curto prazo (próximos 3 a 6 meses), estimando custos recorrentes e possíveis investimentos, para evitar surpresas.",
            "d": "Vocês já têm um controle de caixa organizado, com revisões e projeções, o que é excelente para a fase de ideação. Mantenham essa disciplina e, à medida que a complexidade aumentar, considerem evoluir para ferramentas mais robustas ou integrar esse controle a um planejamento financeiro mais amplo.",
        },
    },
]


def normalize_monthly_series(
    state: st.session_state, product_index: int, horizon_years: int
) -> List[Dict[str, float]]:
    """Return a monthly price/quantity series aligned with the planning horizon.

    The wizard allows users to configure per-product monthly overrides. When
    the configured list is shorter than the planning horizon (or absent),
    downstream projections previously encountered division-by-zero errors when
    computing ``months_per_year``.  This helper centralises the normalisation
    logic by padding the series up to ``horizon_years * 12`` months while
    carrying forward the latest known price/quantity.

    Args:
        state: Streamlit ``session_state`` containing all inputs.
        product_index: Index of the product within ``state["revenue"]``.
        horizon_years: Planning horizon in years (minimum of 1).

    Returns:
        A list of dictionaries with keys ``price`` and ``qty`` covering exactly
        ``horizon_years * 12`` months.
    """

    horizon = max(int(horizon_years or 0), 1)
    target_months = horizon * 12
    revenue_items = state.get("revenue", [])
    product = revenue_items[product_index] if product_index < len(revenue_items) else {}
    monthly_cfg = state.get("revenue_monthly", {}).get(product_index, {}) or {}
    monthly_list = monthly_cfg.get("monthly") or []
    if not isinstance(monthly_list, list):
        monthly_list = []

    # Base price/quantity fallback from product definition
    base_price = float(product.get("price", 0.0) or 0.0)
    base_qty = float(product.get("qty", 0.0) or 0.0)
    normalized: List[Dict[str, float]] = []
    last_price = base_price
    last_qty = base_qty
    for idx in range(target_months):
        if idx < len(monthly_list):
            entry = monthly_list[idx] or {}
            price = float(entry.get("price", last_price) or 0.0)
            qty = float(entry.get("qty", last_qty) or 0.0)
        else:
            price = last_price
            qty = last_qty
        last_price = price
        last_qty = qty
        normalized.append({"price": price, "qty": qty})
    return normalized


def compute_summary(state: st.session_state) -> Dict[str, float]:
    """Compute simple aggregated totals based on session state.

    This helper remains for backward compatibility with the existing summary
    section but now simply delegates to compute_projections() with no
    scenario variation. The returned dictionary collects high‑level
    aggregates for the first forecast year.

    Args:
        state: Streamlit session_state object with collected data.

    Returns:
        A dictionary summarising revenue, costs, fixed expenses, investments and approximate
        profit based on the current inputs.
    """
    # Use the projection engine with no variation to compute base year values
    projections, cashflows, investments_total = compute_projections(state, variation=1.0)
    # The first element (year 1) holds the first full year of operations
    if len(projections) > 1:
        year1 = projections[1]
    else:
        year1 = {"Receita": 0.0, "Custos": 0.0, "Custos Fixos": 0.0, "Lucro": 0.0}
    receita = year1.get("Receita", 0.0)
    custos_variaveis = year1.get("Custos", 0.0)
    tributos = year1.get("Tributos", 0.0)
    margem_contribuicao = receita - custos_variaveis - tributos
    summary = {
        "Receita Total": receita,
        "Custos Variáveis Totais": custos_variaveis,
        "Tributos Variáveis (Simples)": tributos,
        "Margem de Contribuição": margem_contribuicao,
        "Custos Fixos": year1.get("Custos Fixos", 0.0),
        "Investimentos Totais": investments_total,
        "Resultado Operacional": year1.get("Lucro", 0.0),
    }
    return summary


def compute_projections(state: st.session_state, variation: float = 1.0) -> Tuple[List[Dict[str, float]], List[float], float]:
    """Compute multi‑year projections and cashflows.

    This function generates annual projections of revenue, costs, fixed expenses,
    financing payments and profit, along with the corresponding cash flow
    series used in viability analysis. The "variation" parameter scales
    sales quantities to facilitate scenario analysis.

    Args:
        state: Streamlit session_state object with collected data.
        variation: Multiplier applied to sales quantities (1.0 = base case).

    Returns:
        projections: A list of dicts per year (year 0 through horizon) with
            keys ``Ano``, ``Receita``, ``Custos``, ``Custos Fixos``, ``Pagamento Empréstimo`` and ``Lucro``.
        cashflows: A list of cash flows corresponding to each year.
        investments_total: Total investments (used outside for summary).
    """
    # Number of years in the projection (horizon)
    n_years = max(int(state.get("horizon", 1) or 0), 1)
    # Lists to accumulate revenue and quantities per year across all products
    rev_per_year = [0.0 for _ in range(n_years)]
    # For each product, we store the aggregated quantity per year to compute costs later
    qty_per_product_per_year: List[List[float]] = []  # shape: [product][year]
    cost_per_unit_list: List[float] = []
    variable_cost_per_unit_list: List[float] = []
    # Iterate products to build aggregates
    for i, item in enumerate(state.get("revenue", [])):
        monthly_data = normalize_monthly_series(state, i, n_years)
        months_total = len(monthly_data)
        months_per_year = months_total // n_years if n_years > 0 else months_total
        if months_per_year == 0:
            months_per_year = 12
        # Aggregate revenue and quantity per year for this product
        qty_year = [0.0 for _ in range(n_years)]
        rev_year = [0.0 for _ in range(n_years)]
        for m_idx, m_data in enumerate(monthly_data):
            year_idx = min(m_idx // months_per_year, n_years - 1)
            p_val = float(m_data.get("price", 0) or 0)
            q_val = float(m_data.get("qty", 0) or 0)
            qty_year[year_idx] += q_val
            rev_year[year_idx] += p_val * q_val
        # Add to global revenue per year
        for y in range(n_years):
            rev_per_year[y] += rev_year[y]
        qty_per_product_per_year.append(qty_year)
        # Compute direct cost per unit for this product. Each cost item already
        # represents the per-unit quantity multiplied by its unit price, so we
        # avoid dividing by the projected quantity (which previously diluted the
        # cost and yielded underestimated totals).
        product_costs = 0.0
        for cost_item in state.get("costs", {}).get(i, []):
            c_qty = float(cost_item.get("qty", 0) or 0)
            c_unit = float(cost_item.get("unit", 0) or 0)
            product_costs += c_qty * c_unit
        cost_per_unit_list.append(product_costs)
        # Sum variable expenses per unit for this product
        var_expenses = state.get("variable_expenses", {}).get(i, [])
        var_cost_per_unit = 0.0
        for v_item in var_expenses:
            # Each variable expense item follows the same structure as cost items:
            # quantity times unit cost yields per-unit variable expense.
            try:
                v_qty = float(v_item.get("qty", 0) or 0)
                v_unit = float(v_item.get("unit", 0) or 0)
                var_cost_per_unit += v_qty * v_unit
            except Exception:
                var_cost_per_unit += 0.0
        variable_cost_per_unit_list.append(var_cost_per_unit)
    # Compute monthly fixed spending across all categories (costs + expenses)
    fixed_expenses_month = 0.0
    for cat in ["op", "adm", "sales"]:
        for item in state.get("fixed_costs", {}).get(cat, []):
            fixed_expenses_month += float(item.get("value", 0) or 0)
        for item in state.get("fixed_expenses", {}).get(cat, []):
            fixed_expenses_month += float(item.get("value", 0) or 0)
    fixed_expenses_annual = fixed_expenses_month * 12
    # Compute total investments
    investments_total = 0.0
    for asset in state.get("investments", []):
        val = float(asset.get("value", 0) or 0)
        investments_total += val
    # Compute financing
    financing = state.get("financing", {}) or {}
    loan_amount = float(financing.get("amount", 0.0) or 0.0)
    rate = float(financing.get("rate", 0.0) or 0.0) / 100.0
    years = int(financing.get("years", 0) or 0)
    # Annual loan payment using annuity formula (if applicable)
    payment = 0.0
    if loan_amount > 0 and years > 0:
        if rate == 0:
            payment = loan_amount / years
        else:
            payment = loan_amount * rate / (1 - (1 + rate) ** (-years))
    projections: List[Dict[str, float]] = []
    cashflows: List[float] = []
    # Iterate over year 0 (initial) and subsequent years
    for t in range(n_years + 1):
        if t == 0:
            revenue = 0.0
            cost = 0.0
            fixed_expenses = 0.0
            loan_payment_year = 0.0
            tax_amount = 0.0
            profit = 0.0
            investments_outflow = investments_total if investments_total else 0.0
            loan_inflow = loan_amount
            # Cash flow at year 0: loan inflow minus investments outflow
            cash_flow = loan_inflow - investments_outflow
        else:
            y = t - 1  # zero‑based year index
            # Revenue and cost adjusted by variation factor
            revenue_base = rev_per_year[y]
            revenue = revenue_base * variation
            # Compute cost as sum of cost_per_unit_i * (quantity_i_year_y * variation)
            cost_total = 0.0
            for idx, qty_year in enumerate(qty_per_product_per_year):
                qty_y = qty_year[y]
                # Direct cost per unit
                direct_cost = cost_per_unit_list[idx] * (qty_y * variation)
                # Variable cost per unit (per unit cost * quantity)
                var_cost = variable_cost_per_unit_list[idx] * (qty_y * variation)
                cost_total += direct_cost + var_cost
            cost = cost_total
            fixed_expenses = fixed_expenses_annual
            # Loan payment occurs up to "years" periods (starting in year 1)
            loan_payment_year = payment if (t <= years) else 0.0
            # Compute tax amount if enabled
            tax_amount = 0.0
            if state.get("calculate_tax"):
                annex = state.get("tax_annex", "I")
                # Use annual revenue as RBT12
                _, tax_amount = compute_simples_tax(revenue, str(annex))
            # Under variável costing, financing amortisation is not part of
            # operating result (DRE). It remains in cash flow only.
            profit = revenue - cost - fixed_expenses - tax_amount
            cash_flow = profit - loan_payment_year
        projections.append(
            {
                "Ano": t,
                "Receita": revenue,
                "Custos": cost,
                "Custos Fixos": fixed_expenses,
                "Pagamento Empréstimo": loan_payment_year,
                "Tributos": tax_amount,
                "Lucro": profit,
            }
        )
        cashflows.append(cash_flow)
    return projections, cashflows, investments_total


def compute_npv(cashflows: List[float], discount_rate: float) -> float:
    """Compute Net Present Value (NPV) for a cash flow series.

    Args:
        cashflows: List of cash flows (year 0 through n).
        discount_rate: Annual discount rate in decimal (e.g. 0.1 for 10%).

    Returns:
        The Net Present Value.
    """
    r = discount_rate
    npv = 0.0
    for t, cf in enumerate(cashflows):
        npv += cf / ((1 + r) ** t)
    return npv


def compute_irr(cashflows: List[float], guess: float = 0.1) -> Optional[float]:
    """Compute Internal Rate of Return (IRR) via Newton–Raphson.

    Args:
        cashflows: List of cash flows (year 0 through n).
        guess: Initial guess for the IRR.

    Returns:
        The IRR as a decimal, or None if it fails to converge.
    """
    rate = guess
    for _ in range(100):
        # Evaluate NPV and its derivative at current rate
        f = 0.0
        df = 0.0
        for t, cf in enumerate(cashflows):
            denom = (1 + rate) ** t
            f += cf / denom
            if denom != 0:
                df += -t * cf / (denom * (1 + rate))
        # Newton–Raphson update
        if df == 0:
            return None
        new_rate = rate - f / df
        if abs(new_rate - rate) < 1e-7:
            return new_rate
        rate = new_rate
    return None


def compute_mirr(cashflows: List[float], finance_rate: float, reinvest_rate: float) -> Optional[float]:
    """Compute Modified Internal Rate of Return (MIRR).

    Args:
        cashflows: List of cash flows (year 0 through n).
        finance_rate: Rate used to discount negative cash flows.
        reinvest_rate: Rate used to compound positive cash flows.

    Returns:
        The MIRR as a decimal, or None if negative cash flows are zero.
    """
    n = len(cashflows) - 1
    if n <= 0:
        return None
    # Present value of negative cash flows discounted at finance_rate
    pv_neg = 0.0
    for t, cf in enumerate(cashflows):
        if cf < 0:
            pv_neg += cf / ((1 + finance_rate) ** t)
    # Future value of positive cash flows compounded at reinvest_rate
    fv_pos = 0.0
    for t, cf in enumerate(cashflows):
        if cf > 0:
            fv_pos += cf * ((1 + reinvest_rate) ** (n - t))
    if pv_neg == 0:
        return None
    try:
        mirr = (fv_pos / (-pv_neg)) ** (1 / n) - 1
        return mirr
    except Exception:
        return None


def compute_payback(cashflows: List[float], discount_rate: float) -> Tuple[Optional[int], Optional[int]]:
    """Compute Payback and Discounted Payback periods.

    Args:
        cashflows: List of cash flows (year 0 through n).
        discount_rate: Annual discount rate in decimal.

    Returns:
        A tuple (payback_period, discounted_payback_period). Each value is
        the year in which cumulative cash flow becomes non‑negative, or None
        if it does not recover within the horizon.
    """
    cumulative = 0.0
    payback = None
    for i, cf in enumerate(cashflows):
        cumulative += cf
        if cumulative >= 0 and payback is None:
            payback = i
            break
    cumulative_d = 0.0
    discounted_payback = None
    for i, cf in enumerate(cashflows):
        cumulative_d += cf / ((1 + discount_rate) ** i)
        if cumulative_d >= 0 and discounted_payback is None:
            discounted_payback = i
            break
    return payback, discounted_payback

# -----------------------------------------------------------------------------
# Break‑even analysis and monthly details
#
# The original Excel model computes margin of contribution (MC), break‑even
# revenue and quantities by product, and detailed cash flow projections.  The
# functions below replicate that behaviour in Python.  They operate off the
# existing session state (which holds revenue, costs, fixed expenses, investments and financing)
# and the variation factor chosen by the user.  These helpers are called
# inside wizard_step7 to display results.

def compute_break_even(state: st.session_state, variation: float = 1.0) -> Optional[Dict[str, Any]]:
    """Compute break‑even metrics and contribution margin.

    The break‑even point is the level of revenue at which profit equals zero.
    We compute the margin of contribution (MC), its percentage, the total
    fixed costs and then derive the revenue needed to cover those
    fixed costs.  Results are based on year 1 of the projection and honour
    the chosen variation factor.

    Args:
        state: Streamlit session_state containing inputs.
        variation: Multiplier applied to sales quantities (1.0 = base).

    Returns:
        A dictionary with keys:
            mc: total margin of contribution (revenue minus variable costs and taxes).
            mc_percent: MC divided by revenue (0–1).
            fixed_costs: annual fixed costs.
            revenue_be: break‑even revenue (or None if mc_percent <= 0).
            product_breakdown: list of dicts with per‑product share and break‑even values.
    """
    # Use projections to extract revenue, cost, fixed expenses and tax for year 1
    projections, _cash, _investments = compute_projections(state, variation)
    if len(projections) < 2:
        return None
    year1 = projections[1]
    revenue = year1.get("Receita", 0.0)
    variable_cost = year1.get("Custos", 0.0)
    fixed_costs = year1.get("Custos Fixos", 0.0)
    tax_amount = year1.get("Tributos", 0.0)
    # Margin of contribution includes taxes as variable because under Simples
    # Nacional the effective tax depends on revenue and therefore scales with
    # sales.  Subtract variable cost and taxes from revenue.
    mc = revenue - variable_cost - tax_amount
    mc_percent = mc / revenue if revenue > 0 else 0.0
    # Break‑even revenue: fixed costs divided by MC% (if positive)
    revenue_be = (fixed_costs / mc_percent) if mc_percent > 0 else None
    # Build per‑product breakdown using revenue and quantities of year 1
    product_breakdown: List[Dict[str, Any]] = []
    # Determine months and months per year for splitting monthly data
    horizon = int(state.get("horizon", 1) or 1)
    months = horizon * 12
    months_per_year = months // horizon if horizon else 12
    # Compute per‑product revenue and quantity in year 1
    total_revenue_y1 = 0.0
    per_prod_rev: List[float] = []
    per_prod_qty: List[float] = []
    # Precompute cost per unit and variable cost per unit for margin per product
    cost_per_unit_list: List[float] = []
    var_cost_per_unit_list: List[float] = []
    for idx, item in enumerate(state.get("revenue", [])):
        monthly = normalize_monthly_series(state, idx, horizon)
        # Aggregate revenue and quantity for year 1 (first months_per_year months)
        rev = 0.0
        qty_sum = 0.0
        for m in range(min(months_per_year, len(monthly))):
            m_price = float(monthly[m].get("price", 0.0))
            m_qty = float(monthly[m].get("qty", 0.0)) * variation
            rev += m_price * m_qty
            qty_sum += m_qty
        per_prod_rev.append(rev)
        per_prod_qty.append(qty_sum)
        total_revenue_y1 += rev
        # Compute cost per unit and variable cost per unit for this product (aggregated over all months)
        # Sum all cost items (qty * unit). These entries already reflect per-unit costs,
        # so avoid dividing by the sold quantity.
        total_direct = 0.0
        for c in state.get("costs", {}).get(idx, []):
            total_direct += float(c.get("qty", 0.0)) * float(c.get("unit", 0.0))
        cost_per_unit_list.append(total_direct)
        # Sum variable expenses per unit (quantity * unit)
        var_exp = 0.0
        for v in state.get("variable_expenses", {}).get(idx, []):
            try:
                v_qty = float(v.get("qty", 0.0))
                v_unit = float(v.get("unit", 0.0))
                var_exp += v_qty * v_unit
            except Exception:
                var_exp += 0.0
        var_cost_per_unit_list.append(var_exp)
    # Build breakdown entries
    for idx, rev_i in enumerate(per_prod_rev):
        share = (rev_i / total_revenue_y1) if total_revenue_y1 > 0 else 0.0
        # Break‑even revenue for this product
        rev_be_i = share * revenue_be if revenue_be is not None else 0.0
        # Average price per unit (avoid divide by zero)
        avg_price = rev_i / per_prod_qty[idx] if per_prod_qty[idx] > 0 else 0.0
        qty_be = (rev_be_i / avg_price) if avg_price > 0 else 0.0
        # Compute margin of contribution per unit and total for this product (excluding taxes).
        # Margem de contribuição unitária = P - CVu - DVu, where P is average price,
        # CVu is direct cost per unit and DVu is variable expense per unit.
        mc_unit = avg_price - (cost_per_unit_list[idx] + var_cost_per_unit_list[idx])
        mc_total = mc_unit * per_prod_qty[idx]
        product_breakdown.append(
            {
                "name": state.get("revenue", [])[idx].get("name", f"Produto {idx + 1}"),
                "share": share,
                "revenue_be": rev_be_i,
                "quantity_be": qty_be,
                "price": avg_price,
                "cost_unit": cost_per_unit_list[idx],
                "var_unit": var_cost_per_unit_list[idx],
                "mc_unit": mc_unit,
                "mc_total": mc_total,
            }
        )
    return {
        "mc": mc,
        "mc_percent": mc_percent,
        "fixed_costs": fixed_costs,
        "revenue_be": revenue_be,
        "product_breakdown": product_breakdown,
    }


def compute_monthly_details(state: st.session_state, variation: float = 1.0) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Compute monthly and annual cash flow and result projections.

    This function mirrors the Excel model's monthly tables.  For each
    month, we calculate revenue, variable costs, fixed costs, taxes,
    profit, and cash flows broken into operational, financial and
    investment activities.  Results are aggregated by year for the
    annual view.

    Args:
        state: Streamlit session_state containing inputs.
        variation: Multiplier applied to sales quantities (1.0 = base).

    Returns:
        A tuple (df_month, df_annual) where each is a pandas DataFrame.  The
        monthly DataFrame has one row per month (including month index) and
        columns: Receita, Custo Variável, Custo Fixo, Tributos, Lucro,
        CF Operacional, CF Financeiro, CF Investimento, CF Total.  The
        annual DataFrame aggregates these values by year and includes
        identical columns plus the year number.
    """
    horizon = max(int(state.get("horizon", 1) or 0), 1)
    months_total = horizon * 12
    normalized_monthlies: List[List[Dict[str, float]]] = [
        normalize_monthly_series(state, idx, horizon)
        for idx, _ in enumerate(state.get("revenue", []))
    ]
    # Precompute cost per unit and variable cost per unit per product
    cost_per_unit_list: List[float] = []
    var_cost_per_unit_list: List[float] = []
    for idx, prod in enumerate(state.get("revenue", [])):
        monthly_data = normalized_monthlies[idx]
        # Sum direct costs (quantity * unit) from costs list
        total_direct = 0.0
        for c in state.get("costs", {}).get(idx, []):
            total_direct += float(c.get("qty", 0.0)) * float(c.get("unit", 0.0))
        cost_per_unit_list.append(total_direct)
        # Sum variable expenses per unit (quantity * unit cost for each item)
        var_cost_unit = 0.0
        for v in state.get("variable_expenses", {}).get(idx, []):
            try:
                v_qty = float(v.get("qty", 0.0))
                v_unit = float(v.get("unit", 0.0))
                var_cost_unit += v_qty * v_unit
            except Exception:
                var_cost_unit += 0.0
        var_cost_per_unit_list.append(var_cost_unit)
    # Fixed spending per month from categories (costs + expenses)
    fixed_expenses_total_monthly = 0.0
    for cat in ["op", "adm", "sales"]:
        for item in state.get("fixed_costs", {}).get(cat, []):
            fixed_expenses_total_monthly += float(item.get("value", 0.0))
        for item in state.get("fixed_expenses", {}).get(cat, []):
            fixed_expenses_total_monthly += float(item.get("value", 0.0))
    # Financing: compute annual payment and convert to monthly
    fin = state.get("financing", {}) or {}
    loan_amount = float(fin.get("amount", 0.0))
    rate = float(fin.get("rate", 0.0)) / 100.0
    years = int(fin.get("years", 0.0) or 0)
    loan_payment_ann = 0.0
    if loan_amount > 0 and years > 0:
        if rate == 0:
            loan_payment_ann = loan_amount / years
        else:
            loan_payment_ann = loan_amount * rate / (1 - (1 + rate) ** (-years))
    loan_payment_month = loan_payment_ann / 12.0 if years > 0 else 0.0
    # Build per‑month details
    rows_month: List[Dict[str, float]] = []
    # Precompute effective tax rates per year if tax is enabled
    tax_annex = state.get("tax_annex", "I")
    tax_enabled = bool(state.get("calculate_tax"))
    # For each year compute annual revenue and effective rate
    eff_rates: List[float] = [0.0 for _ in range(horizon)]
    if tax_enabled:
        # Compute revenue per year for current variation
        revenue_years = [0.0 for _ in range(horizon)]
        for idx, prod in enumerate(state.get("revenue", [])):
            monthly_data = normalized_monthlies[idx]
            for m_idx, m_data in enumerate(monthly_data):
                yr = min(m_idx // 12, horizon - 1)
                revenue_years[yr] += float(m_data.get("price", 0.0)) * float(m_data.get("qty", 0.0)) * variation
        # Derive effective rates per year
        for yr in range(horizon):
            _eff, _tax_amt = compute_simples_tax(revenue_years[yr], tax_annex)
            eff_rates[yr] = _eff
    # Investment outflows per month: negative value at the specified month index (0‑based)
    investments_monthly = [0.0 for _ in range(months_total)]
    for asset in state.get("investments", []):
        m_idx = int(asset.get("month", 0) or 0)
        val = float(asset.get("value", 0.0))
        if 0 <= m_idx < months_total:
            investments_monthly[m_idx] -= val
    # Loan inflow occurs at month 0
    loan_inflow_monthly = [0.0 for _ in range(months_total)]
    if loan_amount > 0:
        loan_inflow_monthly[0] += loan_amount
    # Schedules (queues) to distribute term payments and receipts across installments
    revenue_receivable_schedule: List[List[float]] = [[0.0] for _ in state.get("revenue", [])]
    variable_payable_schedule: List[float] = [0.0]
    fixed_payable_schedule: List[float] = [0.0]
    # Iterate months to compute metrics
    for m in range(months_total):
        # Determine year index for tax and loan payment cut‑off
        year_idx = min(m // 12, horizon - 1)
        # Revenue (competência), variable cost and cash receipts for this month
        revenue_m = 0.0
        var_cost_m = 0.0
        cash_receipt_m = 0.0
        var_cost_cash_m = pop_scheduled_amount(variable_payable_schedule)
        fixed_cost_cash_m = pop_scheduled_amount(fixed_payable_schedule)
        for idx, prod in enumerate(state.get("revenue", [])):
            monthly_data = normalized_monthlies[idx]
            m_data = monthly_data[m]
            qty_m = float(m_data.get("qty", 0.0)) * variation
            price_m = float(m_data.get("price", 0.0))
            rev_i_m = price_m * qty_m
            revenue_m += rev_i_m
            # Variable accrual by product (direct costs + variable expenses)
            var_cost_item_m = (cost_per_unit_list[idx] + var_cost_per_unit_list[idx]) * qty_m
            var_cost_m += var_cost_item_m
            # Revenue cash: prior installments + immediate + newly scheduled installments
            cash_receipt_m += pop_scheduled_amount(revenue_receivable_schedule[idx])
            cash_receipt_m += schedule_installment_flow(
                revenue_receivable_schedule[idx],
                rev_i_m,
                float(prod.get("prazo", 0.0) or 0.0),
                int(prod.get("prazo_parcelas", 1) or 1),
            )
            # Variable cash payment schedule combines costs and variable expenses payment terms
            product_costs = state.get("costs", {}).get(idx, [])
            product_vars = state.get("variable_expenses", {}).get(idx, [])
            for cost_item in product_costs:
                item_amount = float(cost_item.get("qty", 0.0)) * float(cost_item.get("unit", 0.0)) * qty_m
                var_cost_cash_m += schedule_installment_flow(
                    variable_payable_schedule,
                    item_amount,
                    float(cost_item.get("prazo_pct", cost_item.get("term", 0.0)) or 0.0),
                    int(cost_item.get("prazo_parcelas", 1) or 1),
                )
            for var_item in product_vars:
                item_amount = float(var_item.get("qty", 0.0)) * float(var_item.get("unit", 0.0)) * qty_m
                var_cost_cash_m += schedule_installment_flow(
                    variable_payable_schedule,
                    item_amount,
                    float(var_item.get("prazo_pct", var_item.get("term", 0.0)) or 0.0),
                    int(var_item.get("prazo_parcelas", 1) or 1),
                )
        # Fixed cost for this month (competência)
        fixed_cost_m = fixed_expenses_total_monthly
        # Schedule fixed costs cash according to payment terms
        for cat in ["op", "adm", "sales"]:
            for item in state.get("fixed_costs", {}).get(cat, []):
                fixed_cost_cash_m += schedule_installment_flow(
                    fixed_payable_schedule,
                    float(item.get("value", 0.0) or 0.0),
                    float(item.get("prazo_pct", 0.0) or 0.0),
                    int(item.get("prazo_parcelas", 1) or 1),
                )
            for item in state.get("fixed_expenses", {}).get(cat, []):
                fixed_cost_cash_m += schedule_installment_flow(
                    fixed_payable_schedule,
                    float(item.get("value", 0.0) or 0.0),
                    float(item.get("prazo_pct", 0.0) or 0.0),
                    int(item.get("prazo_parcelas", 1) or 1),
                )
        # Tax for this month (accrual basis)
        tax_m = 0.0
        if tax_enabled:
            eff = eff_rates[year_idx]
            tax_m = revenue_m * eff
        # Loan payment (outflow) for this month; only apply within loan term
        fin_cf_m = loan_inflow_monthly[m]
        if (m // 12) < years:
            # Spread annual payment evenly across 12 months
            fin_cf_m -= loan_payment_ann / 12.0 if years > 0 else 0.0
        # Investment cash flow for this month
        invest_cf_m = investments_monthly[m]
        # Operational cash flow: cash receipts minus variable and fixed costs minus taxes
        oper_cf_m = cash_receipt_m - var_cost_cash_m - fixed_cost_cash_m - tax_m
        # Profit in competência follows custeio variável, excluding financing flows.
        profit_m = revenue_m - var_cost_m - fixed_cost_m - tax_m
        # Total cash flow
        total_cf_m = oper_cf_m + fin_cf_m + invest_cf_m
        rows_month.append(
            {
                "Mês": m + 1,
                "Receita": revenue_m,
                "Receita Caixa": cash_receipt_m,
                "Custo Variável": var_cost_m,
                "Custo Fixo": fixed_cost_m,
                "Tributos": tax_m,
                "Lucro": profit_m,
                "CF Operacional": oper_cf_m,
                "CF Financeiro": fin_cf_m,
                "CF Investimento": invest_cf_m,
                "CF Total": total_cf_m,
            }
        )
    df_month = pd.DataFrame(rows_month)
    # Aggregate to annual results
    annual_rows: List[Dict[str, float]] = []
    for yr in range(horizon):
        start = yr * 12
        end = start + 12
        slice_df = df_month.iloc[start:end]
        annual_rows.append(
            {
                "Ano": yr + 1,
                "Receita": slice_df["Receita"].sum(),
                "Receita Caixa": slice_df["Receita Caixa"].sum(),
                "Custo Variável": slice_df["Custo Variável"].sum(),
                "Custo Fixo": slice_df["Custo Fixo"].sum(),
                "Tributos": slice_df["Tributos"].sum(),
                "Lucro": slice_df["Lucro"].sum(),
                "CF Operacional": slice_df["CF Operacional"].sum(),
                "CF Financeiro": slice_df["CF Financeiro"].sum(),
                "CF Investimento": slice_df["CF Investimento"].sum(),
                "CF Total": slice_df["CF Total"].sum(),
            }
        )
    df_ann = pd.DataFrame(annual_rows)
    return df_month, df_ann


def generate_pdf(summary: Dict[str, float]) -> bytes:
    """Generate a simple PDF report from the summary dict.

    Args:
        summary: Summary dictionary with financial metrics.

    Returns:
        PDF data as bytes.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "Relatório Financeiro")
    y -= 30
    c.setFont("Helvetica", 12)
    for key, value in summary.items():
        c.drawString(50, y, f"{key}: {format_currency_br(value)}")
        y -= 20
    c.showPage()
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_excel(summary: Dict[str, float]) -> bytes:
    """Generate an Excel file from the summary dict.

    Args:
        summary: Summary dictionary with financial metrics.

    Returns:
        Excel file as bytes.
    """
    buffer = io.BytesIO()
    df = pd.DataFrame(list(summary.items()), columns=["Categoria", "Valor"])
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Resumo")
    return buffer.getvalue()


def generate_full_pdf(
    project_name: str,
    horizon: int,
    variation_pct: float,
    discount_rate: float,
    dre_df: pd.DataFrame,
    fc_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    break_even_summary: Dict[str, Any],
    break_even_df: pd.DataFrame,
    ann_df: pd.DataFrame,
) -> bytes:
    """Generate a comprehensive PDF report with all analyses.

    The report includes DRE projections under variable costing, cash-flow
    projections, viability metrics, break-even analysis and annual summaries.

    Args:
        project_name: Name of the project.
        horizon: Number of projection years.
        variation_pct: Percentage variation applied to quantity.
        discount_rate: Discount rate used in analyses.
        dre_df: DataFrame for the DRE (accrual results).
        fc_df: DataFrame for the cash flow (annual).
        metrics_df: DataFrame of viability metrics.
        break_even_summary: Dict with overall MC, fixed costs, etc.
        break_even_df: DataFrame of break‑even per product.
        ann_df: DataFrame of annual projections including revenue, costs, cash and profit.

    Returns:
        PDF data as bytes.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 40
    line_height = 14
    # Helper to write a list of lines, creating new pages as needed
    def write_lines(lines, y_start):
        y = y_start
        for line in lines:
            if y < margin:
                c.showPage()
                y = height - margin
            c.drawString(margin, y, line)
            y -= line_height
        return y
    # Title and scenario info
    y = height - margin
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, f"Relatório Completo – {project_name}")
    y -= line_height * 2
    c.setFont("Helvetica", 10)
    c.drawString(margin, y, f"Horizonte: {horizon} ano(s)")
    y -= line_height
    c.drawString(margin, y, f"Variação de quantidade: {variation_pct:+.1f}%")
    y -= line_height
    c.drawString(margin, y, f"Taxa de desconto: {discount_rate * 100:.2f}%")
    y -= line_height * 2
    # Section: DRE
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Demonstração do Resultado (Competência)")
    y -= line_height * 2
    c.setFont("Helvetica", 8)
    # Convert dre_df to lines
    header = [f"{col}" for col in dre_df.columns]
    rows = dre_df.values.tolist()
    # Format numbers
    formatted_rows = []
    for r in rows:
        fr = []
        for val in r:
            if isinstance(val, (float, int)):
                fr.append(format_currency_br(val))
            else:
                fr.append(str(val))
        formatted_rows.append(fr)
    # Compose lines with tab separation
    lines = ["\t".join(header)] + ["\t".join(row) for row in formatted_rows]
    y = write_lines(lines, y)
    y -= line_height
    # Section: Cash Flow
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Fluxo de Caixa (Caixa)")
    y -= line_height * 2
    c.setFont("Helvetica", 8)
    cf_header = ["Ano", "Fluxo de Caixa"]
    cf_lines = ["\t".join(cf_header)] + [f"{int(row['Ano'])}\t{format_currency_br(row['Fluxo de Caixa'])}" for _, row in fc_df.iterrows()]
    y = write_lines(cf_lines, y)
    y -= line_height
    # Section: Viabilidade
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Análise de Viabilidade")
    y -= line_height * 2
    c.setFont("Helvetica", 8)
    for _, row in metrics_df.iterrows():
        line = f"{row['Indicador']}: {row['Valor']}"
        if y < margin:
            c.showPage()
            y = height - margin
        c.drawString(margin, y, line)
        y -= line_height
    y -= line_height
    # Section: Break-even
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Ponto de Equilíbrio e Margem de Contribuição")
    y -= line_height * 2
    c.setFont("Helvetica", 8)
    # Overall summary
    be_lines = []
    be_lines.append(f"MC total: {format_currency_br(break_even_summary['mc'])}")
    be_lines.append(f"MC%: {format_percent_br(break_even_summary['mc_percent'] * 100)}")
    be_lines.append(f"Gastos Fixos (Ano 1): {format_currency_br(break_even_summary['fixed_costs'])}")
    if break_even_summary['revenue_be'] is not None:
        be_lines.append(f"Receita de PE: {format_currency_br(break_even_summary['revenue_be'])}")
    y = write_lines(be_lines, y)
    y -= line_height
    # Per product breakdown
    # Adapt header and formatting to match the break-even DataFrame structure.
    # Expected columns: Produto/Serviço, Preço (P), CVu, DVu, MCu, MCt, Participação (%), Rec. PE (R$), Quantidade de PE
    be_header = [
        "Produto",
        "Preço (P)",
        "CVu",
        "DVu",
        "MCu",
        "MCt",
        "Part. %",
        "Rec. PE",
        "Qtd PE",
    ]
    be_rows = break_even_df.values.tolist()
    formatted_be_rows = []
    for r in be_rows:
        # r indices correspond to the DataFrame columns:
        # 0=name, 1=price, 2=cost unit, 3=var unit, 4=MCu, 5=MCt, 6=share, 7=rec PE, 8=qty PE
        formatted_be_rows.append(
            [
                str(r[0]),
                f"{format_currency_br(r[1])}",
                f"{format_currency_br(r[2])}",
                f"{format_currency_br(r[3])}",
                f"{format_currency_br(r[4])}",
                f"{format_currency_br(r[5])}",
                f"{format_percent_br(r[6])}",
                f"{format_currency_br(r[7])}",
                f"{r[8]:.2f}".replace(".", ","),
            ]
        )
    be_lines_full = ["\t".join(be_header)] + ["\t".join(row) for row in formatted_be_rows]
    y = write_lines(be_lines_full, y)
    y -= line_height
    # Section: Annual Summary
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Projeção Anual (Competência e Caixa)")
    y -= line_height * 2
    c.setFont("Helvetica", 8)
    ann_header = list(ann_df.columns)
    ann_rows = ann_df.values.tolist()
    # Format ann rows
    formatted_ann_rows = []
    for r in ann_rows:
        row_fmt = []
        for i, val in enumerate(r):
            if i == 0:  # Year
                row_fmt.append(str(val))
            else:
                row_fmt.append(format_currency_br(val))
        formatted_ann_rows.append(row_fmt)
    ann_lines = ["\t".join(ann_header)] + ["\t".join(row) for row in formatted_ann_rows]
    y = write_lines(ann_lines, y)
    c.showPage()
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

# -----------------------------------------------------------------------------
# Tax tables for Simples Nacional
#
# Each annex (I through V) defines six revenue brackets with a corresponding
# nominal rate (alíquota) and deduction (parcela a deduzir). The effective tax
# rate is computed as: (RBT12 * nominal_rate - deduction) / RBT12. The
# thresholds (in Brazilian reais) are the same for all annexes: up to
# 180k, 360k, 720k, 1.8m, 3.6m and 4.8m. These values are derived from the
# official Simples Nacional tables and mirror those used in the original Excel
# model.
SIMPLIES_THRESHOLDS = [180000, 360000, 720000, 1800000, 3600000, 4800000]
SIMPLIES_TABLES = {
    "I": {
        "rates": [0.04, 0.073, 0.095, 0.107, 0.143, 0.19],
        "deductions": [0, 5940, 13860, 22500, 87300, 378000],
    },
    "II": {
        "rates": [0.045, 0.078, 0.10, 0.112, 0.147, 0.30],
        "deductions": [0, 5940, 13860, 22500, 85500, 720000],
    },
    "III": {
        "rates": [0.06, 0.112, 0.135, 0.16, 0.21, 0.33],
        "deductions": [0, 9360, 17640, 35640, 125640, 648000],
    },
    "IV": {
        "rates": [0.045, 0.09, 0.102, 0.14, 0.22, 0.33],
        "deductions": [0, 8100, 12420, 39780, 183780, 828000],
    },
    "V": {
        "rates": [0.155, 0.18, 0.195, 0.205, 0.23, 0.305],
        "deductions": [0, 4500, 9900, 17100, 62100, 540000],
    },
}

# Helper to compute effective tax and tax amount for Simples Nacional given an
# annual revenue (RBT12) and an annex. Returns the effective rate and tax
# payable. If revenue exceeds the highest bracket, uses the last bracket's
# parameters. If revenue is zero or negative, returns zero tax.
def compute_simples_tax(revenue: float, annex: str) -> Tuple[float, float]:
    """Calculate the effective tax rate and tax amount under Simples Nacional.

    Args:
        revenue: Annual gross revenue (RBT12) in BRL.
        annex: Annex classification ("I", "II", "III", "IV" or "V").

    Returns:
        A tuple (effective_rate, tax_amount). Rate is a fraction (e.g., 0.05
        means 5%). Tax amount is revenue * effective_rate. If revenue <= 0
        or annex not defined, returns (0.0, 0.0).
    """
    if revenue <= 0:
        return 0.0, 0.0
    table = SIMPLIES_TABLES.get(annex)
    if not table:
        return 0.0, 0.0
    rates = table["rates"]
    deductions = table["deductions"]
    # Determine the bracket index
    idx = 0
    for j, limit in enumerate(SIMPLIES_THRESHOLDS):
        if revenue <= limit:
            idx = j
            break
        idx = j  # if revenue is greater than all thresholds, idx ends at last
    nominal_rate = rates[idx]
    deduction = deductions[idx]
    # Effective rate formula: (RBT12 * nominal_rate - deduction) / RBT12
    effective_rate = (revenue * nominal_rate - deduction) / revenue
    # Avoid negative effective rates
    effective_rate = max(effective_rate, 0.0)
    tax_amount = revenue * effective_rate
    return effective_rate, tax_amount


def init_state():
    """Initialize session state variables if they do not exist."""
    defaults = {
        "view": "home",
        "module": "Planejamento financeiro",
        "step": 1,
        "project_name": "",
        "currency": "BRL",
        "horizon": 3,
        "revenue": [],
        # 'costs' will be a dictionary mapping each product index to a list of
        # cost items for that product. Each cost item has fields: name, qty, unit, term.
        "costs": {},
        # revenue_monthly: maps product index to a list of monthly dicts ({'price': p, 'qty': q})
        "revenue_monthly": {},
        "fixed_expenses": {"op": [], "adm": [], "sales": []},
        "fixed_costs": {"op": [], "adm": [], "sales": []},
        "investments": [],
        "financing": {},
        # variable_expenses will map each product index to a list of variable expenses.
        # Each expense has fields: desc (description) and value (per unit cost).
        "variable_expenses": {},
        # Tax configuration: whether to compute taxes and which annex of the
        # Simples Nacional applies. The annex determines nominal rates and
        # deductions used in the effective tax calculation. Default: no tax.
        "calculate_tax": False,
        "tax_annex": "I",
        "governance_report": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def go_to_home() -> None:
    """Return to the flow selection screen."""

    st.session_state.view = "home"
    safe_rerun()


def open_module(module_name: str) -> None:
    """Select module and open the corresponding flow."""

    st.session_state.module = module_name
    st.session_state.view = "module"
    safe_rerun()


def render_home_screen() -> None:
    """Render initial screen explaining each available flow."""

    st.title("Assistente Financeiro para Startups")
    st.markdown(
        """
        Escolha abaixo qual jornada você deseja iniciar. Você pode voltar para esta tela a qualquer momento
        usando o botão **“Trocar fluxo”**.
        """
    )

    planning_col, governance_col = st.columns(2)

    with planning_col:
        st.markdown("### 📈 Planejamento financeiro")
        st.markdown(
            """
            Fluxo para estruturar projeções de receita, custos, investimentos e viabilidade.

            **Você vai encontrar:**
            - etapas guiadas de cadastro do negócio;
            - DRE/DFC e indicadores (VPL, TIR e payback);
            - exportação em PDF e Excel.
            """
        )
        if st.button("Iniciar Planejamento Financeiro", use_container_width=True):
            open_module("Planejamento financeiro")

    with governance_col:
        st.markdown("### 🧭 Avaliação de governança")
        st.markdown(
            """
            Fluxo para avaliar a maturidade dos acordos entre sócios na fase inicial da startup.

            **Você vai encontrar:**
            - perguntas objetivas sobre alinhamento e regras societárias;
            - recomendações práticas por tema;
            - resumo do estágio atual de governança.
            """
        )
        if st.button("Iniciar Avaliação de Governança", use_container_width=True):
            open_module("Avaliação de governança corporativa (startups)")


# Utility to rerun Streamlit script in a version‑agnostic way.
def safe_rerun() -> None:
    """
    Attempt to trigger a rerun of the Streamlit app. Streamlit changed
    the API for reruns across versions; this helper checks for
    `st.experimental_rerun` (older versions) and `st.rerun` (newer
    versions), falling back to toggling a dummy session_state key and
    stopping execution when neither is present.
    """
    # Newer versions expose st.rerun
    if hasattr(st, "experimental_rerun"):
        try:
            st.experimental_rerun()
            return
        except Exception:
            pass
    if hasattr(st, "rerun"):
        try:
            st.rerun()
            return
        except Exception:
            pass
    # Last resort: toggle a flag and stop; on the next interaction the script
    # will re-execute.
    st.session_state["__safe_rerun"] = st.session_state.get("__safe_rerun", 0) + 1
    st.stop()


def format_currency_br(value: float) -> str:
    """Format currency using Brazilian separators with two decimals."""

    text = f"{float(value):,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return f"R$ {text}"


def format_percent_br(value: float) -> str:
    """Format percentage with two decimals and comma as decimal separator."""

    text = f"{float(value):.2f}".replace(".", ",")
    return f"{text}%"


def pop_scheduled_amount(schedule: List[float]) -> float:
    """Pop the scheduled amount for the current month and advance the queue."""

    if not schedule:
        schedule.append(0.0)
    amount = float(schedule.pop(0))
    schedule.append(0.0)
    return amount


def schedule_installment_flow(
    schedule: List[float], amount: float, pct_prazo: float, installments: int
) -> float:
    """Schedule an accrual amount into immediate + installments cash flow."""

    amt = float(amount or 0.0)
    pct = min(max(float(pct_prazo or 0.0), 0.0), 100.0) / 100.0
    n_inst = max(int(installments or 1), 1)
    immediate = amt * (1.0 - pct)
    term_total = amt * pct
    if term_total > 0:
        each = term_total / n_inst
        for month_offset in range(1, n_inst + 1):
            if month_offset >= len(schedule):
                schedule.extend([0.0] * (month_offset - len(schedule) + 1))
            schedule[month_offset] += each
    return immediate


def render_step_index() -> None:
    """Render a navigation index across all steps at the top of each page.

    This function displays a horizontal row of buttons (1–7), each representing
    a step of the wizard. Clicking a button updates the current step in
    ``st.session_state`` and triggers a rerun to navigate accordingly.
    """
    st.markdown(
        """
        <style>
        div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button {
            white-space: nowrap;
            word-break: keep-all;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    step_labels = [
        "Etapa 1 · Identificação do Projeto",
        "Etapa 2 · Estrutura de Receitas",
        "Etapa 3 · Gastos Variáveis",
        "Etapa 4 · Gastos Fixos",
        "Etapa 5 · Investimentos",
        "Etapa 6 · Resultados e Análises",
    ]
    cols = st.columns(len(step_labels))
    for idx, label in enumerate(step_labels):
        if cols[idx].button(label, key=f"nav_step_{idx+1}"):
            st.session_state.step = idx + 1
            safe_rerun()


def render_planning_sidebar() -> None:
    """Render sidebar navigation with completion status per step."""

    step_labels = [
        "Projeto",
        "Receitas",
        "Gastos Variáveis",
        "Gastos Fixos",
        "Investimentos",
        "Resultados",
    ]
    current_step = int(st.session_state.get("step", 1) or 1)
    progress = min(max(current_step / len(step_labels), 0.0), 1.0)

    with st.sidebar:
        if st.button("← Trocar fluxo", key="planning_back_home", use_container_width=True):
            go_to_home()

        st.subheader("Progresso do planejamento")
        st.progress(progress)
        st.caption(f"Etapa {current_step} de {len(step_labels)}")

        st.markdown("### Navegação por etapas")
        checks = [
            bool(st.session_state.get("project_name")),
            len(st.session_state.get("revenue", [])) > 0,
            sum(len(v) for v in st.session_state.get("costs", {}).values()) > 0,
            (
                sum(len(v) for v in st.session_state.get("fixed_costs", {}).values()) > 0
                or sum(len(v) for v in st.session_state.get("fixed_expenses", {}).values()) > 0
            ),
            len(st.session_state.get("investments", [])) > 0,
            True,
        ]
        check_labels = [
            "Etapa 1 · Projeto",
            "Etapa 2 · Receitas",
            "Etapa 3 · Gastos Variáveis",
            "Etapa 4 · Gastos Fixos",
            "Etapa 5 · Investimentos",
            "Etapa 6 · Resultados",
        ]
        for idx, (label, ok) in enumerate(zip(check_labels, checks), start=1):
            icon = "✅" if ok else "⬜"
            suffix = " · atual" if current_step == idx else ""
            if st.button(f"{icon} {label}{suffix}", key=f"sidebar_step_{idx}", use_container_width=True):
                st.session_state.step = idx
                safe_rerun()




def render_step_header(step_number: int, title: str, description: str) -> None:
    """Render a consistent heading block for wizard steps."""
    step_colors = {
        1: "#0EA5E9",
        2: "#10B981",
        3: "#F59E0B",
        4: "#EF4444",
        5: "#8B5CF6",
        6: "#6366F1",
    }
    color = step_colors.get(step_number, "#334155")
    st.markdown(
        (
            f"<div style='padding:10px 14px;border-radius:10px;"
            f"background:{color};color:white;font-weight:700;margin:10px 0 4px 0;'>"
            f"Etapa {step_number} · {title}</div>"
        ),
        unsafe_allow_html=True,
    )
    st.caption(description)


def render_summary_cards(summary: Dict[str, float]) -> None:
    """Render key planning metrics using compact KPI cards."""

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Receita total", format_currency_br(summary.get("revenue", 0.0)))
    with col2:
        st.metric("Custos totais", format_currency_br(summary.get("costs", 0.0)))
    with col3:
        st.metric("Lucro líquido", format_currency_br(summary.get("profit", 0.0)))


def wizard_step1():
    """Step 1: Project identification."""
    render_step_header(1, "Identificação do Projeto", "Defina os parâmetros iniciais do seu planejamento.")
    # Explanation about the identification step
    st.markdown(
        """
        Nesta etapa inicial você define os parâmetros básicos do seu negócio: nome, moeda e horizonte de
        planejamento (número de anos). Essas informações servem de base para todas as projeções. O horizonte
        determina quantos anos (12 meses cada) serão projetados.  

        *Exemplos*: para um **negócio industrial** (fabricação de móveis), você pode planejar 3 anos de atividade
        e optar por projetar em reais (BRL). Para um **comércio** (loja de roupas) ou **serviço** (consultoria de TI),
        o conceito é o mesmo: escolha a moeda, defina o horizonte e dê um nome ao projeto.
        """
    )
    project_name = st.text_input("Nome do Projeto", value=st.session_state.project_name)
    currency = st.selectbox("Moeda", options=["BRL", "USD", "EUR"], index=["BRL", "USD", "EUR"].index(st.session_state.currency))
    horizon = st.number_input("Horizonte (anos)", min_value=1, max_value=120, value=int(st.session_state.horizon))
    # Tax configuration: Optionally compute Simples Nacional taxes. Users can
    # choose to include tax calculations and specify which annex applies to
    # their business. This selection affects the effective tax rate used in
    # projections.
    st.markdown("### Tributação")
    calc_tax = st.checkbox(
        "Calcular tributos (Simples Nacional)",
        value=bool(st.session_state.calculate_tax),
    )
    tax_annex = st.session_state.tax_annex
    if calc_tax:
        annex_options = ["I", "II", "III", "IV", "V"]
        if tax_annex not in annex_options:
            tax_annex = "I"
        tax_annex = st.selectbox(
            "Selecione o Anexo (I a V)",
            options=annex_options,
            index=annex_options.index(tax_annex),
        )
    # Navigation
    col1, col2 = st.columns([1, 1])
    with col2:
        if st.button("Próximo ▸", key="next1"):
            st.session_state.project_name = project_name
            st.session_state.currency = currency
            st.session_state.horizon = horizon
            st.session_state.calculate_tax = calc_tax
            st.session_state.tax_annex = tax_annex
            st.session_state.step = 2
            safe_rerun()

    # Option to save/load the project state to/from a file
    st.markdown("### Salvar/Carregar Projeto")
    with st.expander("Salvar ou carregar dados do projeto"):
        # Download current session state as JSON
        # Only include serialisable keys
        save_data = {
            "project_name": st.session_state.get("project_name", ""),
            "currency": st.session_state.get("currency", "BRL"),
            "horizon": st.session_state.get("horizon", 1),
            "revenue": st.session_state.get("revenue", []),
            "revenue_monthly": st.session_state.get("revenue_monthly", {}),
            "costs": st.session_state.get("costs", {}),
            "variable_expenses": st.session_state.get("variable_expenses", {}),
            "fixed_expenses": st.session_state.get("fixed_expenses", {}),
            "fixed_costs": st.session_state.get("fixed_costs", {}),
            "investments": st.session_state.get("investments", []),
            "calculate_tax": st.session_state.get("calculate_tax", False),
            "tax_annex": st.session_state.get("tax_annex", "I"),
        }
        json_bytes = json.dumps(save_data, indent=2).encode("utf-8")
        st.download_button(
            label="Salvar projeto (JSON)",
            data=json_bytes,
            file_name="assistente_financeiro_projeto.json",
            mime="application/json",
            key="download_project_json",
        )
        # Upload to load a previously saved project
        uploaded = st.file_uploader("Carregar projeto (JSON)", type=["json"], key="upload_project_json")
        if uploaded is not None:
            try:
                loaded = json.loads(uploaded.read().decode("utf-8"))
                # Update session state with loaded values
                for k, v in loaded.items():
                    st.session_state[k] = v
                st.success("Projeto carregado com sucesso!")
                # After loading, rerun to refresh UI
                safe_rerun()
            except Exception:
                st.error("Falha ao carregar o arquivo. Certifique-se de que é um JSON válido.")


def wizard_step2():
    """Step 2: Revenue structure with monthly or base+growth input options.

    This step allows the user to enter revenue data for each product/service
    either by specifying monthly price and quantity for the first year or
    by providing a base value and a growth percentage to auto‑generate
    the monthly series. The monthly data are stored in
    ``st.session_state.revenue_monthly`` under the index of each product
    and later used in the projection calculations.
    """
    render_step_header(2, "Estrutura de Receitas", "Cadastre produtos e configure a evolução mensal de vendas.")
    # Explanation for revenue structure
    st.markdown(
        """
        Nesta etapa você registra cada **produto ou serviço** que gera receita. Para cada item, informe
        o preço de venda, a quantidade estimada e o percentual vendido a prazo.  

        Há duas formas de preencher os valores mensais:  

        * **Mensal (Tabela)** – ideal para quando você possui uma previsão mês a mês. Por exemplo, se
        você fabrica mesas (indústria), pode projetar 50 unidades no mês 1, 55 no mês 2, etc.  

        * **Base + Crescimento** – preencha o valor e quantidade iniciais e um percentual de crescimento
        mensal. O sistema gera automaticamente a série para todo o horizonte. Após gerar, você pode
        ajustar manualmente qualquer mês.  

        **Setores**:  

        * **Indústria** – cadastre cada bem fabricado (ex.: cadeira, mesa) com o preço de venda e
          produção mensal.  

        * **Comércio** – inclua cada mercadoria revendida (ex.: camiseta, tênis) com preço de venda e
          quantidades compradas para revenda.  

        * **Serviços** – registre cada serviço prestado (ex.: consultoria, reparo) com o preço/hora e
          número de horas ou projetos.  

        O percentual “vendido a prazo” serve para calcular o fluxo de caixa, mas nesta versão simplificada
        ainda não há controle de contas a receber.
        """
    )
    # Determine number of months based on the planning horizon. We collect monthly
    # values for the entire horizon (horizon * 12 months). This allows projections
    # across multiple years (e.g., 3 anos = 36 meses).
    months = int(st.session_state.horizon) * 12 if st.session_state.horizon else 12
    month_labels = [f"Mês {m + 1}" for m in range(months)]
    # Iterate through each defined product/service
    for i, item in enumerate(st.session_state.revenue):
        # Fetch existing configuration (if any) for this product
        cfg = st.session_state.revenue_monthly.get(i, {})
        method_default = cfg.get("method", "Mensal (Tabela)")
        # Defaults for base and growth values; if not defined, fall back to item price/qty or zero
        base_price_default = float(cfg.get("base_price", item.get("price", 0.0)))
        base_qty_default = float(cfg.get("base_qty", item.get("qty", 0.0)))
        growth_price_default = float(cfg.get("growth_price", 0.0))
        growth_qty_default = float(cfg.get("growth_qty", 0.0))
        monthly_data_default = cfg.get("monthly", [])
        # Initialize monthly data with default values if length mismatches
        if not isinstance(monthly_data_default, list) or len(monthly_data_default) != months:
            monthly_data_default = []
            for _ in range(months):
                monthly_data_default.append({"price": base_price_default, "qty": base_qty_default})
        with st.expander(f"Produto/Serviço {i + 1}", expanded=True):
            # Name of the product/service
            name = st.text_input("Nome", value=item.get("name", ""), key=f"rev_name_{i}")
            # Percentage of sales on credit
            prazo = st.number_input(
                "% vendido a prazo",
                min_value=0.0,
                max_value=100.0,
                value=float(item.get("prazo", 0.0)),
                key=f"rev_prazo_{i}",
            )
            prazo_parcelas = st.number_input(
                "Parcelamento médio (nº de parcelas)",
                min_value=1,
                max_value=60,
                value=int(item.get("prazo_parcelas", 1) or 1),
                key=f"rev_prazo_parcelas_{i}",
            )
            # Selection of input method
            method = st.selectbox(
                "Modo de inserção",
                options=["Mensal (Tabela)", "Base + Crescimento"],
                index=["Mensal (Tabela)", "Base + Crescimento"].index(method_default),
                key=f"rev_method_{i}",
            )
            # Initialize current base and growth values from defaults. These
            # variables will be overwritten inside the Base + Crescimento
            # branch if the user chooses that method. Otherwise they retain
            # the default values.
            base_price_val = base_price_default
            base_qty_val = base_qty_default
            growth_price_val = growth_price_default
            growth_qty_val = growth_qty_default
            # Base + growth configuration. Assign defaults first; these
            # variables will be overwritten below if the method is selected.
            base_price_val = base_price_default
            base_qty_val = base_qty_default
            growth_price_val = growth_price_default
            growth_qty_val = growth_qty_default
            if method == "Base + Crescimento":
                # Show input fields for base price/qty and growth rates
                st.markdown("### Configuração Base + Crescimento")
                # Only allow growth for quantity; price remains constant across months.
                col_bp, col_bq, col_gq = st.columns(3)
                with col_bp:
                    base_price_val = st.number_input(
                        "Preço base (mês 1)",
                        min_value=0.0,
                        value=base_price_default,
                        format="%.2f",
                        key=f"rev_base_price_{i}",
                    )
                with col_bq:
                    base_qty_val = st.number_input(
                        "Quantidade base (mês 1)",
                        min_value=0.0,
                        value=base_qty_default,
                        step=1.0,
                        key=f"rev_base_qty_{i}",
                    )
                # Growth percentage for quantity. Price growth is not allowed and remains zero.
                with col_gq:
                    growth_qty_val = st.number_input(
                        "Crescimento % quantidade (mês a mês)",
                        min_value=-100.0,
                        max_value=100.0,
                        value=growth_qty_default,
                        step=0.1,
                        key=f"rev_growth_qty_{i}",
                    )
                # Price growth is disabled: always zero
                growth_price_val = 0.0
                # Determine whether to (re)generate the monthly series automatically. We
                # regenerate when:
                #   - There is no existing monthly data or its length doesn't match the horizon;
                #   - The stored method for this product is not "Base + Crescimento";
                #   - The base/growth values have changed relative to the stored config.
                should_generate = False
                prev_cfg = st.session_state.revenue_monthly.get(i, {})
                # If no monthly data exists or length mismatch, regenerate
                prev_monthly = prev_cfg.get("monthly", []) if isinstance(prev_cfg.get("monthly", []), list) else []
                if len(prev_monthly) != months:
                    should_generate = True
                # If method changed, regenerate
                if prev_cfg.get("method") != "Base + Crescimento":
                    should_generate = True
                # Check if base/growth values changed relative to previous config (within small tolerance)
                tol = 1e-9
                if prev_cfg.get("base_price") is not None and abs(float(prev_cfg.get("base_price")) - base_price_val) > tol:
                    should_generate = True
                if prev_cfg.get("base_qty") is not None and abs(float(prev_cfg.get("base_qty")) - base_qty_val) > tol:
                    should_generate = True
                if prev_cfg.get("growth_qty") is not None and abs(float(prev_cfg.get("growth_qty")) - growth_qty_val) > tol:
                    should_generate = True
                # User can also explicitly force regeneration by pressing a button
                if st.button("Gerar valores mensais", key=f"gen_months_{i}"):
                    should_generate = True
                # Generate or update the monthly series if needed
                if should_generate:
                    generated = []
                    for m in range(months):
                        # Keep price constant across months; only quantity grows
                        price_m = base_price_val
                        qty_m = base_qty_val * ((1 + growth_qty_val / 100.0) ** m)
                        generated.append({"price": price_m, "qty": qty_m})
                    # Update monthly data and configuration in session state
                    st.session_state.revenue_monthly[i] = {
                        "method": method,
                        "base_price": base_price_val,
                        "base_qty": base_qty_val,
                        "growth_price": growth_price_val,
                        "growth_qty": growth_qty_val,
                        "monthly": generated,
                    }
                    # Update individual month input state so the new values appear immediately
                    for m, m_data in enumerate(generated):
                        st.session_state[f"rev_month_price_{i}_{m}"] = m_data["price"]
                        st.session_state[f"rev_month_qty_{i}_{m}"] = m_data["qty"]
                    # Set the default monthly data for this run
                    monthly_data_default = generated
                    # Force a rerun to refresh the UI with new defaults
                    safe_rerun()
                else:
                    # Reuse previous monthly values
                    monthly_data_default = prev_monthly
            # Monthly values editing section (only quantity; price remains constant)
            st.markdown("### Valores Mensais (período)")
            updated_monthly = []
            for m in range(months):
                # Let user adjust monthly quantity; price is fixed at base_price_val
                qty_val = st.number_input(
                    f"Quantidade {month_labels[m]}",
                    min_value=0.0,
                    value=float(monthly_data_default[m].get("qty", 0.0)),
                    step=1.0,
                    key=f"rev_month_qty_{i}_{m}",
                )
                updated_monthly.append({"price": base_price_val, "qty": qty_val})
            # Update revenue and monthly configuration in session state. Use
            # the current values (base_price_val, base_qty_val, growth_*_val) so that
            # edits to the configuration persist even if the user does not click
            # the generate button again.
            st.session_state.revenue[i] = {
                "name": name,
                "price": base_price_val,
                "qty": base_qty_val,
                "prazo": prazo,
                "prazo_parcelas": int(prazo_parcelas),
            }
            st.session_state.revenue_monthly[i] = {
                "method": method,
                "base_price": base_price_val,
                "base_qty": base_qty_val,
                # growth_price is fixed at zero (not used)
                "growth_price": 0.0,
                "growth_qty": growth_qty_val,
                "monthly": updated_monthly,
            }
    # Option to add new product/service
    if st.button("+ Adicionar Produto/Serviço", key="add_rev"):
        st.session_state.revenue.append({"name": "", "price": 0.0, "qty": 0.0, "prazo": 0.0, "prazo_parcelas": 1})
        safe_rerun()
    # Navigation
    col1, col2 = st.columns(2)
    with col1:
        if st.button("◂ Voltar", key="back2"):
            st.session_state.step = 1
            safe_rerun()
    with col2:
        if st.button("Próximo ▸", key="next2"):
            st.session_state.step = 3
            safe_rerun()


def wizard_step3():
    """Step 3: Variable spending split into costs and expenses per product."""

    def _coerce_float(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    def _coerce_str(x):
        return "" if x is None else str(x)

    render_step_header(3, "Gastos Variáveis", "Informe os custos variáveis e despesas variáveis por item da etapa 2.")
    # Explanation for direct costs
    st.markdown(
        """
        Nesta etapa você relaciona os **custos diretamente associados** a cada produto ou serviço. Esses
        custos variam proporcionalmente com a quantidade produzida ou vendida.  

        *Para um negócio industrial*, isso inclui matérias‑primas, componentes e mão‑de‑obra direta.
        Por exemplo, para fabricar 1 cadeira você usa madeira e 2 horas de carpinteiro.  

        *Para um comércio*, considere o **custo de aquisição** das mercadorias revendidas (custo de
        reposição). Se você revende camisetas, o custo unitário é o preço pago ao fornecedor.  

        *Para empresas de serviços*, o custo direto geralmente é o valor pago a colaboradores ou
        prestadores que executam o serviço (honorários, comissões).  

        Você também pode adicionar **despesas variáveis** por produto – valores que dependem da
        quantidade vendida, como taxas de cartão, frete por unidade ou comissões de venda.  

        Para cada item da etapa anterior, preencha dois quadros:

        * **Quadro de Custos Variáveis**
        * **Quadro de Despesas Variáveis**

        Cada quadro possui as colunas: **Item**, **Quantidade unitária**, **Valor unitário** e
        **Valor total**. Abaixo de cada quadro, o sistema apresenta o **somatório total**.

        Nas despesas variáveis, informe também a classificação de cada item em
        **Operacional** ou **Vendas**.
        """
    )
    # Loop through each item defined in Step 2
    for prod_index, product in enumerate(st.session_state.revenue):
        product_name = product.get("name") or f"Produto/Serviço {prod_index + 1}"
        st.subheader(f"Seção do Item {prod_index + 1}: {product_name}")

        # Ensure a list of cost items exists for this product index
        if prod_index not in st.session_state.costs:
            st.session_state.costs[prod_index] = []

        # Ensure a list of variable expenses exists for this product index
        if prod_index not in st.session_state.variable_expenses:
            st.session_state.variable_expenses[prod_index] = []

        with st.container(border=True):
            st.markdown(f"### (A) Quadro de Custos Variáveis – do Item {product_name}")

            costs_list = st.session_state.costs.get(prod_index, [])
            df_costs = pd.DataFrame(
                [
                    {
                        "Item": _coerce_str(row.get("name")),
                        "Quantidade unitária": _coerce_float(row.get("qty")),
                        "Valor unitário": _coerce_float(row.get("unit")),
                    }
                    for row in costs_list
                ]
            )
            if df_costs.empty:
                df_costs = pd.DataFrame(columns=["Item", "Quantidade unitária", "Valor unitário"])

            df_costs["Valor total"] = df_costs["Quantidade unitária"] * df_costs["Valor unitário"]

            edited_costs = st.data_editor(
                df_costs,
                use_container_width=True,
                num_rows="dynamic",
                key=f"costs_table_{prod_index}",
                column_config={
                    "Item": st.column_config.TextColumn("Item"),
                    "Quantidade unitária": st.column_config.NumberColumn("Quantidade unitária", min_value=0.0, step=1.0),
                    "Valor unitário": st.column_config.NumberColumn("Valor unitário", min_value=0.0, step=0.01, format="R$ %.2f"),
                    "Valor total": st.column_config.NumberColumn("Valor total", format="R$ %.2f", disabled=True),
                },
                disabled=["Valor total"],
            )

            edited_costs["Quantidade unitária"] = edited_costs["Quantidade unitária"].apply(_coerce_float)
            edited_costs["Valor unitário"] = edited_costs["Valor unitário"].apply(_coerce_float)
            edited_costs["Valor total"] = edited_costs["Quantidade unitária"] * edited_costs["Valor unitário"]

            total_costs = float(edited_costs["Valor total"].sum()) if not edited_costs.empty else 0.0
            st.markdown(f"**Total de Custos Variáveis do Item {product_name}: {format_currency_br(total_costs)}**")

            st.session_state.costs[prod_index] = [
                {
                    "name": _coerce_str(row["Item"]),
                    "qty": _coerce_float(row["Quantidade unitária"]),
                    "unit": _coerce_float(row["Valor unitário"]),
                    "prazo_pct": 0.0,
                    "prazo_parcelas": 1,
                }
                for _, row in edited_costs.iterrows()
                if _coerce_str(row["Item"]).strip() != ""
                or _coerce_float(row["Quantidade unitária"]) != 0.0
                or _coerce_float(row["Valor unitário"]) != 0.0
            ]

        with st.container(border=True):
            st.markdown(f"### (B) Quadro de Despesas Variáveis – do Item {product_name}")

            exp_list = st.session_state.variable_expenses.get(prod_index, [])
            df_exp = pd.DataFrame(
                [
                    {
                        "Item": _coerce_str(row.get("name")),
                        "Quantidade unitária": _coerce_float(row.get("qty")),
                        "Valor unitário": _coerce_float(row.get("unit")),
                        "Classificação": _coerce_str(row.get("classification") or "Operacional"),
                    }
                    for row in exp_list
                ]
            )
            if df_exp.empty:
                df_exp = pd.DataFrame(columns=["Item", "Quantidade unitária", "Valor unitário", "Classificação"])

            if "Classificação" in df_exp.columns:
                df_exp["Classificação"] = df_exp["Classificação"].apply(
                    lambda x: "Vendas" if str(x) == "Vendas" else "Operacional"
                )

            df_exp["Valor total"] = df_exp["Quantidade unitária"] * df_exp["Valor unitário"]

            edited_exp = st.data_editor(
                df_exp,
                use_container_width=True,
                num_rows="dynamic",
                key=f"var_exp_table_{prod_index}",
                column_config={
                    "Item": st.column_config.TextColumn("Item"),
                    "Quantidade unitária": st.column_config.NumberColumn("Quantidade unitária", min_value=0.0, step=1.0),
                    "Valor unitário": st.column_config.NumberColumn("Valor unitário", min_value=0.0, step=0.01, format="R$ %.2f"),
                    "Classificação": st.column_config.SelectboxColumn("Classificação", options=["Operacional", "Vendas"]),
                    "Valor total": st.column_config.NumberColumn("Valor total", format="R$ %.2f", disabled=True),
                },
                disabled=["Valor total"],
            )

            edited_exp["Quantidade unitária"] = edited_exp["Quantidade unitária"].apply(_coerce_float)
            edited_exp["Valor unitário"] = edited_exp["Valor unitário"].apply(_coerce_float)
            edited_exp["Classificação"] = edited_exp["Classificação"].apply(
                lambda x: "Vendas" if str(x) == "Vendas" else "Operacional"
            )
            edited_exp["Valor total"] = edited_exp["Quantidade unitária"] * edited_exp["Valor unitário"]

            total_exp = float(edited_exp["Valor total"].sum()) if not edited_exp.empty else 0.0
            subtotal_oper = (
                float(edited_exp.loc[edited_exp["Classificação"] == "Operacional", "Valor total"].sum())
                if not edited_exp.empty
                else 0.0
            )
            subtotal_vendas = (
                float(edited_exp.loc[edited_exp["Classificação"] == "Vendas", "Valor total"].sum())
                if not edited_exp.empty
                else 0.0
            )

            st.markdown(f"**Total de Despesas Variáveis do Item {product_name}: {format_currency_br(total_exp)}**")
            st.markdown(f"Subtotal Operacional: **{format_currency_br(subtotal_oper)}**")
            st.markdown(f"Subtotal Vendas: **{format_currency_br(subtotal_vendas)}**")

            st.session_state.variable_expenses[prod_index] = [
                {
                    "name": _coerce_str(row["Item"]),
                    "qty": _coerce_float(row["Quantidade unitária"]),
                    "unit": _coerce_float(row["Valor unitário"]),
                    "classification": _coerce_str(row["Classificação"]),
                    "prazo_pct": 0.0,
                    "prazo_parcelas": 1,
                }
                for _, row in edited_exp.iterrows()
                if _coerce_str(row["Item"]).strip() != ""
                or _coerce_float(row["Quantidade unitária"]) != 0.0
                or _coerce_float(row["Valor unitário"]) != 0.0
            ]

        st.divider()
    # Navigation buttons
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("◂ Voltar", key="back3"):
            st.session_state.step = 2
            safe_rerun()
    with col2:
        if st.button("Próximo ▸", key="next3"):
            st.session_state.step = 4
            safe_rerun()


def wizard_step4():
    """Step 4: Fixed spending split into costs and expenses."""
    render_step_header(4, "Gastos Fixos", "Registre custos e despesas fixas recorrentes.")
    st.markdown(
        """
        Nesta etapa você registra os **gastos fixos** do negócio, divididos em duas partes:

        * **Custos Fixos** – gastos recorrentes ligados à operação principal.
        * **Despesas Fixas** – gastos recorrentes administrativos, comerciais e de suporte.

        Use as categorias para organizar melhor os lançamentos mensais.
        """
    )
    categories = [("op", "Operacionais"), ("adm", "Administrativas"), ("sales", "De Vendas")]

    st.markdown("### Custos Fixos")
    for cat_key, cat_name in categories:
        st.subheader(f"Custos Fixos · {cat_name}")
        if cat_key not in st.session_state.fixed_costs:
            st.session_state.fixed_costs[cat_key] = []
        for i, item in enumerate(st.session_state.fixed_costs.get(cat_key, [])):
            col1, col2, col3, col4 = st.columns([3, 1.2, 1.2, 1.2])
            with col1:
                desc = st.text_input("Descrição", value=item.get("desc", ""), key=f"fixed_costs_desc_{cat_key}_{i}")
            with col2:
                val = st.number_input("Valor mensal (R$)", min_value=0.0, value=float(item.get("value", 0.0)), format="%.2f", key=f"fixed_costs_val_{cat_key}_{i}")
            with col3:
                prazo_pct = st.number_input("% a prazo", min_value=0.0, max_value=100.0, value=float(item.get("prazo_pct", 0.0)), key=f"fixed_costs_prazo_pct_{cat_key}_{i}")
            with col4:
                prazo_parcelas = st.number_input("Parcelas", min_value=1, max_value=60, value=int(item.get("prazo_parcelas", 1) or 1), key=f"fixed_costs_prazo_parcelas_{cat_key}_{i}")
            st.session_state.fixed_costs[cat_key][i] = {"desc": desc, "value": val, "prazo_pct": prazo_pct, "prazo_parcelas": int(prazo_parcelas)}
        if st.button(f"+ Adicionar custo fixo {cat_name.lower()}", key=f"add_fixed_costs_{cat_key}"):
            st.session_state.fixed_costs[cat_key].append({"desc": "", "value": 0.0, "prazo_pct": 0.0, "prazo_parcelas": 1})
            safe_rerun()

    st.markdown("### Despesas Fixas")
    for cat_key, cat_name in categories:
        st.subheader(f"Despesas Fixas · {cat_name}")
        if cat_key not in st.session_state.fixed_expenses:
            st.session_state.fixed_expenses[cat_key] = []
        for i, exp in enumerate(st.session_state.fixed_expenses.get(cat_key, [])):
            col1, col2, col3, col4 = st.columns([3, 1.2, 1.2, 1.2])
            with col1:
                desc = st.text_input("Descrição", value=exp.get("desc", ""), key=f"fixed_expenses_desc_{cat_key}_{i}")
            with col2:
                val = st.number_input("Valor mensal (R$)", min_value=0.0, value=float(exp.get("value", 0.0)), format="%.2f", key=f"fixed_expenses_val_{cat_key}_{i}")
            with col3:
                prazo_pct = st.number_input("% a prazo", min_value=0.0, max_value=100.0, value=float(exp.get("prazo_pct", 0.0)), key=f"fixed_expenses_prazo_pct_{cat_key}_{i}")
            with col4:
                prazo_parcelas = st.number_input("Parcelas", min_value=1, max_value=60, value=int(exp.get("prazo_parcelas", 1) or 1), key=f"fixed_expenses_prazo_parcelas_{cat_key}_{i}")
            st.session_state.fixed_expenses[cat_key][i] = {"desc": desc, "value": val, "prazo_pct": prazo_pct, "prazo_parcelas": int(prazo_parcelas)}
        if st.button(f"+ Adicionar despesa fixa {cat_name.lower()}", key=f"add_fixed_expenses_{cat_key}"):
            st.session_state.fixed_expenses[cat_key].append({"desc": "", "value": 0.0, "prazo_pct": 0.0, "prazo_parcelas": 1})
            safe_rerun()

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("◂ Voltar", key="back4"):
            st.session_state.step = 3
            safe_rerun()
    with col2:
        if st.button("Próximo ▸", key="next4"):
            st.session_state.step = 5
            safe_rerun()

def wizard_step5():
    """Step 5: Investments."""
    render_step_header(5, "Investimentos", "Liste os ativos necessários e seus meses de aquisição.")
    # Explanation for investments
    st.markdown(
        """
        Os **investimentos** representam gastos em ativos de longa duração necessários para
        iniciar ou ampliar o negócio. Exemplos:

        * **Indústria** – aquisição de máquinas e equipamentos, instalações, veículos e ferramentas.
        * **Comércio** – compra de mobiliário, estantes, computadores e instalação de pontos de venda.
        * **Serviços** – aquisição de equipamentos específicos (ex.: equipamentos médicos) ou
          infraestrutura de TI.

        Para cada ativo, informe a descrição, o valor e o **mês de aquisição** (0 para investimentos
        iniciais). Esses valores são considerados como saídas de caixa na projeção e são depreciados
        conforme a legislação, embora este modelo simplificado não calcule depreciação.
        """
    )
    for i, asset in enumerate(st.session_state.investments):
        with st.expander(f"Ativo {i + 1}", expanded=True):
            desc = st.text_input("Descrição", value=asset.get("desc", ""), key=f"investments_desc_{i}")
            val = st.number_input("Valor (R$)", min_value=0.0, value=float(asset.get("value", 0.0)), format="%.2f", key=f"investments_val_{i}")
            month = st.number_input("Mês de aquisição", min_value=0, max_value=120, value=int(asset.get("month", 0)), step=1, key=f"investments_month_{i}")
            st.session_state.investments[i] = {"desc": desc, "value": val, "month": month}
    if st.button("+ Adicionar Ativo", key="add_investments"):
        st.session_state.investments.append({"desc": "", "value": 0.0, "month": 0})
        safe_rerun()
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("◂ Voltar", key="back5"):
            st.session_state.step = 4
            safe_rerun()
    with col2:
        if st.button("Próximo ▸", key="next5"):
            st.session_state.step = 6
            safe_rerun()


def wizard_step6():
    """Step 6: Financing (optional)."""
    render_step_header(6, "Estrutura de Capital", "Configure dados de empréstimo e financiamento, se houver.")
    # Explanation for financing
    st.markdown(
        """
        Nesta etapa você define as fontes de **financiamento** do seu projeto. Caso seja necessário
        contratar um empréstimo ou financiamento, informe:

        * **Valor do Empréstimo** – o montante a ser financiado.
        * **Taxa de Juros anual** – a taxa nominal cobrada pelo financiador (ao ano).
        * **Prazo (anos)** – número de anos para amortização da dívida.

        O modelo calcula a parcela anual (ou mensal) do empréstimo usando a fórmula de financiamento
        (sistema de amortização constante/anuidade). Essa despesa é considerada no cálculo do lucro
        e no fluxo de caixa.
        """
    )
    loan_amount = st.number_input("Valor do Empréstimo (R$)", min_value=0.0, value=float(st.session_state.financing.get("amount", 0.0)), format="%.2f")
    rate = st.number_input("Taxa de Juros anual (%)", min_value=0.0, max_value=100.0, value=float(st.session_state.financing.get("rate", 0.0)))
    years = st.number_input("Prazo (anos)", min_value=0.0, value=float(st.session_state.financing.get("years", 0.0)))
    st.session_state.financing = {"amount": loan_amount, "rate": rate, "years": years}
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("◂ Voltar", key="back6"):
            st.session_state.step = 5
            safe_rerun()
    with col2:
        if st.button("Próximo ▸", key="next6"):
            st.session_state.step = 7
            safe_rerun()


def wizard_step7():
    """Step 7: Results and report generation."""
    render_step_header(6, "Resultados e Análises", "Analise os indicadores de viabilidade e os gastos projetados.")
    st.markdown("Acompanhe as análises em uma lista vertical e visualize cada bloco de resultados individualmente.")

    st.subheader("Configurações de Cenário e Taxa de Desconto")
    col_var, col_rate = st.columns([1, 1])
    with col_var:
        variation_pct = st.slider(
            "Variação da quantidade de vendas (%)",
            min_value=-50.0,
            max_value=50.0,
            value=0.0,
            step=5.0,
            format="%.2f",
        )
    with col_rate:
        discount_rate_input = st.number_input(
            "Taxa de desconto anual (%)",
            min_value=0.0,
            max_value=100.0,
            value=10.0,
            step=0.1,
            format="%.2f",
        )

    variation_factor = 1.0 + variation_pct / 100.0
    discount_rate = discount_rate_input / 100.0
    projections, cashflows, _ = compute_projections(st.session_state, variation=variation_factor)

    df_dre = pd.DataFrame([p for p in projections[1:]], columns=["Ano", "Receita", "Custos", "Custos Fixos", "Tributos", "Lucro"]).rename(columns={"Custos": "Gastos Variáveis", "Custos Fixos": "Gastos Fixos"})
    df_fc = pd.DataFrame({"Ano": list(range(len(cashflows))), "Fluxo de Caixa": cashflows})
    npv = compute_npv(cashflows, discount_rate)
    irr = compute_irr(cashflows)
    mirr = compute_mirr(cashflows, finance_rate=discount_rate, reinvest_rate=discount_rate)
    payback, discounted_payback = compute_payback(cashflows, discount_rate)
    summary = compute_summary(st.session_state)
    be = compute_break_even(st.session_state, variation_factor)
    df_month, df_ann = compute_monthly_details(st.session_state, variation_factor)

    metrics_table = pd.DataFrame(
        {
            "Indicador": ["VPL (NPV)", "TIR", "TIRm", "Payback (anos)", "Payback Descontado (anos)"],
            "Valor": [
                format_currency_br(npv),
                format_percent_br(irr * 100) if irr is not None else "N/D",
                format_percent_br(mirr * 100) if mirr is not None else "N/D",
                str(payback) if payback is not None else "> horizonte",
                str(discounted_payback) if discounted_payback is not None else "> horizonte",
            ],
        }
    )

    df_be_prod = pd.DataFrame()
    if be:
        df_be_prod = pd.DataFrame(be["product_breakdown"]).rename(
            columns={
                "name": "Produto/Serviço",
                "share": "Participação (%)",
                "revenue_be": "Receita de PE (R$)",
                "quantity_be": "Quantidade de PE",
                "mc_unit": "Margem de Contribuição unitária (MCu)",
                "mc_total": "Margem de Contribuição total (MCt)",
                "price": "Preço (P)",
                "cost_unit": "Custo variável unitário (CVu)",
                "var_unit": "Despesa variável unitária (DVu)",
            }
        )
        if "Participação (%)" in df_be_prod.columns:
            df_be_prod["Participação (%)"] = df_be_prod["Participação (%)"] * 100.0

    result_options = [
        "DRE",
        "DFC",
        "Resumo Gerencial",
        "Projeção de resultado Mensal",
        "Projeção de resultado Anual",
    ]
    analysis_options = [
        "Viabilidade",
        "Ponto de Equilíbrio",
    ]
    utility_options = ["Exportações"]

    section = st.radio(
        "Selecione a seção",
        ["Resultados", "Análises", "Utilitários"],
        index=0,
        horizontal=True,
        key="step7_section",
    )

    if section == "Resultados":
        selected = st.radio("Selecione o resultado", result_options, index=0, key="step7_result")
    elif section == "Análises":
        selected = st.radio("Selecione a análise", analysis_options, index=0, key="step7_analysis")
    else:
        selected = st.radio("Selecione o utilitário", utility_options, index=0, key="step7_utility")

    currency_fmt = {
        "Receita": lambda x: format_currency_br(x),
        "Gastos Variáveis": lambda x: format_currency_br(x),
        "Gastos Fixos": lambda x: format_currency_br(x),
        "Tributos": lambda x: format_currency_br(x),
        "Lucro": lambda x: format_currency_br(x),
        "Fluxo de Caixa": lambda x: format_currency_br(x),
        "Valor": lambda x: format_currency_br(x),
    }

    if selected == "DRE":
        st.subheader("Demonstração do Resultado (Regime de Competência · Custeio Variável)")
        st.dataframe(df_dre.style.format(currency_fmt), use_container_width=True)
    elif selected == "DFC":
        st.subheader("Demonstração dos Fluxos de Caixa (Regime de Caixa)")
        st.dataframe(df_fc.style.format({"Fluxo de Caixa": lambda x: format_currency_br(x)}), use_container_width=True)
        st.line_chart(df_fc.set_index("Ano"))
    elif selected == "Viabilidade":
        st.subheader("Análise de Viabilidade")
        st.table(metrics_table)
    elif selected == "Resumo Gerencial":
        render_summary_cards(summary)
        st.subheader("Resumo Gerencial (Ano 1 – Custeio Variável)")
        sum_df = pd.DataFrame({"Categoria": list(summary.keys()), "Valor": list(summary.values())})
        st.dataframe(sum_df.style.format({"Valor": lambda x: format_currency_br(x)}), use_container_width=True)
    elif selected == "Ponto de Equilíbrio":
        if be:
            st.subheader("Ponto de Equilíbrio (PE) e Margem de Contribuição")
            st.markdown(f"**Margem de Contribuição (MC):** {format_currency_br(be['mc'])}")
            st.markdown(f"**Margem de Contribuição (%):** {format_percent_br(be['mc_percent'] * 100)}")
            st.markdown(f"**Gastos Fixos (Ano 1):** {format_currency_br(be['fixed_costs'])}")
            if be["revenue_be"] is not None:
                st.markdown(f"**Receita de Ponto de Equilíbrio:** {format_currency_br(be['revenue_be'])}")
            else:
                st.markdown("**Receita de Ponto de Equilíbrio:** N/D")
            st.dataframe(
                df_be_prod.style.format(
                    {
                        "Participação (%)": lambda x: format_percent_br(x),
                        "Receita de PE (R$)": lambda x: format_currency_br(x),
                        "Quantidade de PE": "{:.2f}",
                        "Margem de Contribuição unitária (MCu)": lambda x: format_currency_br(x),
                        "Margem de Contribuição total (MCt)": lambda x: format_currency_br(x),
                        "Preço (P)": lambda x: format_currency_br(x),
                        "Custo variável unitário (CVu)": lambda x: format_currency_br(x),
                        "Despesa variável unitária (DVu)": lambda x: format_currency_br(x),
                    }
                ),
                use_container_width=True,
            )
        else:
            st.info("Sem dados suficientes para calcular o ponto de equilíbrio.")
    elif selected == "Projeção de resultado Mensal":
        st.subheader("Projeção de resultado Mensal")
        df_month_dre = df_month[["Mês", "Receita", "Custo Variável", "Custo Fixo", "Tributos", "Lucro"]].rename(columns={"Custo Variável": "Gastos Variáveis", "Custo Fixo": "Gastos Fixos"})
        st.dataframe(
            df_month_dre.style.format({
                "Receita": lambda x: format_currency_br(x),
                "Gastos Variáveis": lambda x: format_currency_br(x),
                "Gastos Fixos": lambda x: format_currency_br(x),
                "Tributos": lambda x: format_currency_br(x),
                "Lucro": lambda x: format_currency_br(x),
            }),
            use_container_width=True,
        )
        st.subheader("Projeção do fluxo de caixa mensal")
        df_month_dfc = df_month[["Mês", "Receita Caixa", "Custo Variável", "Custo Fixo", "Tributos", "CF Operacional", "CF Financeiro", "CF Investimento", "CF Total"]].rename(columns={"Custo Variável": "Gastos Variáveis", "Custo Fixo": "Gastos Fixos"})
        st.dataframe(
            df_month_dfc.style.format({
                "Receita Caixa": lambda x: format_currency_br(x),
                "Gastos Variáveis": lambda x: format_currency_br(x),
                "Gastos Fixos": lambda x: format_currency_br(x),
                "Tributos": lambda x: format_currency_br(x),
                "CF Operacional": lambda x: format_currency_br(x),
                "CF Financeiro": lambda x: format_currency_br(x),
                "CF Investimento": lambda x: format_currency_br(x),
                "CF Total": lambda x: format_currency_br(x),
            }),
            use_container_width=True,
        )
    elif selected == "Projeção de resultado Anual":
        st.subheader("Projeção de resultado Anual")
        df_ann_dre = df_ann[["Ano", "Receita", "Custo Variável", "Custo Fixo", "Tributos", "Lucro"]].rename(columns={"Custo Variável": "Gastos Variáveis", "Custo Fixo": "Gastos Fixos"})
        st.dataframe(
            df_ann_dre.style.format({
                "Receita": lambda x: format_currency_br(x),
                "Gastos Variáveis": lambda x: format_currency_br(x),
                "Gastos Fixos": lambda x: format_currency_br(x),
                "Tributos": lambda x: format_currency_br(x),
                "Lucro": lambda x: format_currency_br(x),
            }),
            use_container_width=True,
        )
        st.subheader("Projeção do fluxo de caixa anual")
        df_ann_dfc = df_ann[["Ano", "Receita Caixa", "Custo Variável", "Custo Fixo", "Tributos", "CF Operacional", "CF Financeiro", "CF Investimento", "CF Total"]].rename(columns={"Custo Variável": "Gastos Variáveis", "Custo Fixo": "Gastos Fixos"})
        st.dataframe(
            df_ann_dfc.style.format({
                "Receita Caixa": lambda x: format_currency_br(x),
                "Gastos Variáveis": lambda x: format_currency_br(x),
                "Gastos Fixos": lambda x: format_currency_br(x),
                "Tributos": lambda x: format_currency_br(x),
                "CF Operacional": lambda x: format_currency_br(x),
                "CF Financeiro": lambda x: format_currency_br(x),
                "CF Investimento": lambda x: format_currency_br(x),
                "CF Total": lambda x: format_currency_br(x),
            }),
            use_container_width=True,
        )
    else:
        pdf_data = generate_pdf(summary)
        st.download_button(label="Baixar PDF (Resumo Base)", data=pdf_data, file_name="relatorio_financeiro.pdf", mime="application/pdf", key="download_pdf_base")
        excel_data = generate_excel(summary)
        st.download_button(label="Baixar Excel (Resumo Base)", data=excel_data, file_name="relatorio_financeiro.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="download_excel_base")
        try:
            full_pdf_data = generate_full_pdf(
                st.session_state.project_name or "Projeto",
                int(st.session_state.horizon or 1),
                variation_pct,
                discount_rate,
                df_dre,
                df_fc,
                metrics_table,
                be if be else {"mc": 0.0, "mc_percent": 0.0, "fixed_costs": 0.0, "revenue_be": None},
                df_be_prod,
                df_ann,
            )
            st.download_button(
                label="Exportar todas as análises em PDF",
                data=full_pdf_data,
                file_name="analises_completas.pdf",
                mime="application/pdf",
                key="download_full_pdf",
            )
        except Exception:
            pass

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("◂ Voltar", key="back7"):
            st.session_state.step = 5
            safe_rerun()
    with col2:
        if st.button("Reiniciar", key="restart7"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            init_state()
            safe_rerun()


def show_governance_assessment() -> None:
    """Render the corporate governance self-assessment for startups."""

    st.header("Avaliação de governança corporativa (startups)")
    st.markdown(
        """
        Responda às perguntas abaixo para avaliar o nível de governança entre os fundadores. As
        questões cobrem alinhamento, contribuições, propriedade intelectual e regras societárias.
        Ao final, um mini relatório traz recomendações práticas para cada resposta e um resumo
        geral do estágio de governança.
        """
    )
    if st.button("← Trocar fluxo", key="governance_back_home"):
        go_to_home()

    existing_report = st.session_state.get("governance_report") or {}
    with st.form("governance_form"):
        responses: Dict[int, Optional[str]] = {}
        for idx, question in enumerate(GOVERNANCE_QUESTIONS, start=1):
            st.markdown(f"### {question['title']}")
            option_keys = list(question["options"].keys())
            previous = existing_report.get(idx)
            choice = st.radio(
                question["question"],
                options=option_keys,
                index=(option_keys.index(previous) if previous in option_keys else None),
                format_func=lambda opt, q=question: f"{opt}) {q['options'][opt]}",
                key=f"governance_q_{idx}",
            )
            responses[idx] = choice

        submitted = st.form_submit_button("Gerar relatório")

    if submitted:
        if any(value is None for value in responses.values()):
            st.session_state.governance_report = None
            st.warning("Responda todas as perguntas antes de gerar o relatório.")
            return
        st.session_state.governance_report = responses

    report = st.session_state.get("governance_report") or {}
    if report:
        st.subheader("Mini relatório de recomendações")
        ab_count = 0
        cd_count = 0
        for idx, question in enumerate(GOVERNANCE_QUESTIONS, start=1):
            answer_key = report.get(idx)
            if not answer_key:
                continue
            if answer_key in ["a", "b"]:
                ab_count += 1
            else:
                cd_count += 1
            answer_text = question["options"].get(answer_key, "")
            recommendation = question["recommendations"].get(answer_key, "")
            st.markdown(f"**{question['title']}**")
            st.markdown(f"{question['question']}")
            st.markdown(f"- **Resposta:** {answer_key}) {answer_text}")
            st.markdown(f"- **Recomendação:** {recommendation}")
            st.divider()

        st.subheader("Resumo geral")
        st.markdown(f"Respostas em **a/b**: {ab_count} · Respostas em **c/d**: {cd_count}")
        if ab_count > cd_count:
            st.info(
                "Sua governança está em estágio inicial. Priorize o alinhamento entre sócios, a formalização de combinados e a organização mínima de controles financeiros e societários."
            )
        else:
            st.success(
                "Vocês já têm boas práticas de governança para a fase de ideação. Mantenham a revisão periódica dos acordos e preparem-se para formalizá-los ainda mais à medida que a startup evolui."
            )


def main():
    st.set_page_config(page_title="Assistente Financeiro", layout="centered")
    init_state()

    if st.session_state.get("view") == "home":
        render_home_screen()
        return

    if st.session_state.module == "Planejamento financeiro":
        render_planning_sidebar()
        step = st.session_state.step
        if step == 1:
            wizard_step1()
        elif step == 2:
            wizard_step2()
        elif step == 3:
            wizard_step3()
        elif step == 4:
            wizard_step4()
        elif step == 5:
            wizard_step5()
        elif step in (6, 7):
            wizard_step7()
    else:
        show_governance_assessment()



if __name__ == "__main__":
    main()
