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
        A dictionary summarising revenue, costs, opex, capex and approximate
        profit based on the current inputs.
    """
    # Use the projection engine with no variation to compute base year values
    projections, cashflows, capex_total = compute_projections(state, variation=1.0)
    # The first element (year 1) holds the first full year of operations
    if len(projections) > 1:
        year1 = projections[1]
    else:
        year1 = {"Receita": 0.0, "Custos": 0.0, "Opex": 0.0, "Lucro": 0.0}
    summary = {
        "Receita Total": year1.get("Receita", 0.0),
        "Custos Diretos Totais": year1.get("Custos", 0.0),
        "Opex Anual Total": year1.get("Opex", 0.0),
        "Tributos (Simples)": year1.get("Tributos", 0.0),
        "Capex Total": capex_total,
        "Lucro Aproximado": year1.get("Lucro", 0.0),
    }
    return summary


def compute_projections(state: st.session_state, variation: float = 1.0) -> Tuple[List[Dict[str, float]], List[float], float]:
    """Compute multi‑year projections and cashflows.

    This function generates annual projections of revenue, costs, opex,
    financing payments and profit, along with the corresponding cash flow
    series used in viability analysis. The "variation" parameter scales
    sales quantities to facilitate scenario analysis.

    Args:
        state: Streamlit session_state object with collected data.
        variation: Multiplier applied to sales quantities (1.0 = base case).

    Returns:
        projections: A list of dicts per year (year 0 through horizon) with
            keys ``Ano``, ``Receita``, ``Custos``, ``Opex``, ``Pagamento Empréstimo`` and ``Lucro``.
        cashflows: A list of cash flows corresponding to each year.
        capex_total: Total capital expenditure (used outside for summary).
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
        # Compute cost per unit for this product based on total quantity across all months
        total_qty_for_cost = sum(qty_year)
        product_costs = 0.0
        for cost_item in state.get("costs", {}).get(i, []):
            c_qty = float(cost_item.get("qty", 0) or 0)
            c_unit = float(cost_item.get("unit", 0) or 0)
            product_costs += c_qty * c_unit
        cost_per_unit = (product_costs / total_qty_for_cost) if total_qty_for_cost > 0 else 0.0
        cost_per_unit_list.append(cost_per_unit)
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
    # Compute monthly opex across all categories
    opex_month = 0.0
    for cat in ["op", "adm", "sales"]:
        for exp in state.get("opex", {}).get(cat, []):
            val = float(exp.get("value", 0) or 0)
            opex_month += val
    opex_annual = opex_month * 12
    # Compute capex
    capex_total = 0.0
    for asset in state.get("capex", []):
        val = float(asset.get("value", 0) or 0)
        capex_total += val
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
            opex = 0.0
            loan_payment_year = 0.0
            tax_amount = 0.0
            profit = 0.0
            capex_outflow = capex_total if capex_total else 0.0
            loan_inflow = loan_amount
            # Cash flow at year 0: loan inflow minus capex outflow
            cash_flow = loan_inflow - capex_outflow
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
            opex = opex_annual
            # Loan payment occurs up to "years" periods (starting in year 1)
            loan_payment_year = payment if (t <= years) else 0.0
            # Compute tax amount if enabled
            tax_amount = 0.0
            if state.get("calculate_tax"):
                annex = state.get("tax_annex", "I")
                # Use annual revenue as RBT12
                _, tax_amount = compute_simples_tax(revenue, str(annex))
            # Profit and cash flow include tax
            profit = revenue - cost - opex - loan_payment_year - tax_amount
            cash_flow = revenue - cost - opex - loan_payment_year - tax_amount
        projections.append(
            {
                "Ano": t,
                "Receita": revenue,
                "Custos": cost,
                "Opex": opex,
                "Pagamento Empréstimo": loan_payment_year,
                "Tributos": tax_amount,
                "Lucro": profit,
            }
        )
        cashflows.append(cash_flow)
    return projections, cashflows, capex_total


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
# existing session state (which holds revenue, costs, opex, capex and financing)
# and the variation factor chosen by the user.  These helpers are called
# inside wizard_step7 to display results.

def compute_break_even(state: st.session_state, variation: float = 1.0) -> Optional[Dict[str, Any]]:
    """Compute break‑even metrics and contribution margin.

    The break‑even point is the level of revenue at which profit equals zero.
    We compute the margin of contribution (MC), its percentage, the total
    fixed costs (Opex) and then derive the revenue needed to cover those
    fixed costs.  Results are based on year 1 of the projection and honour
    the chosen variation factor.

    Args:
        state: Streamlit session_state containing inputs.
        variation: Multiplier applied to sales quantities (1.0 = base).

    Returns:
        A dictionary with keys:
            mc: total margin of contribution (revenue minus variable costs and taxes).
            mc_percent: MC divided by revenue (0–1).
            fixed_costs: annual fixed costs (Opex).
            revenue_be: break‑even revenue (or None if mc_percent <= 0).
            product_breakdown: list of dicts with per‑product share and break‑even values.
    """
    # Use projections to extract revenue, cost, opex and tax for year 1
    projections, _cash, _capex = compute_projections(state, variation)
    if len(projections) < 2:
        return None
    year1 = projections[1]
    revenue = year1.get("Receita", 0.0)
    variable_cost = year1.get("Custos", 0.0)
    fixed_costs = year1.get("Opex", 0.0)
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
        # Sum all cost items (qty * unit)
        total_direct = 0.0
        for c in state.get("costs", {}).get(idx, []):
            total_direct += float(c.get("qty", 0.0)) * float(c.get("unit", 0.0))
        cost_per_unit = (total_direct / qty_sum) if qty_sum > 0 else 0.0
        cost_per_unit_list.append(cost_per_unit)
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
    qty_total_list: List[float] = []
    for idx, prod in enumerate(state.get("revenue", [])):
        monthly_data = normalized_monthlies[idx]
        total_qty = sum(float(m.get("qty", 0.0)) * variation for m in monthly_data)
        qty_total_list.append(total_qty)
        # Sum direct costs (quantity * unit) from costs list
        total_direct = 0.0
        for c in state.get("costs", {}).get(idx, []):
            total_direct += float(c.get("qty", 0.0)) * float(c.get("unit", 0.0))
        cost_per_unit = (total_direct / total_qty) if total_qty > 0 else 0.0
        cost_per_unit_list.append(cost_per_unit)
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
    # Fixed cost per month from opex
    opex_total_monthly = 0.0
    for cat in ["op", "adm", "sales"]:
        for exp in state.get("opex", {}).get(cat, []):
            opex_total_monthly += float(exp.get("value", 0.0))
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
    # CapEx outflows per month: negative value at the specified month index (0‑based)
    capex_monthly = [0.0 for _ in range(months_total)]
    for asset in state.get("capex", []):
        m_idx = int(asset.get("month", 0) or 0)
        val = float(asset.get("value", 0.0))
        if 0 <= m_idx < months_total:
            capex_monthly[m_idx] -= val
    # Loan inflow occurs at month 0
    loan_inflow_monthly = [0.0 for _ in range(months_total)]
    if loan_amount > 0:
        loan_inflow_monthly[0] += loan_amount
    # Prepare previous revenue per product for receivables; start with zeros
    prev_rev_per_prod: List[float] = [0.0 for _ in state.get("revenue", [])]
    # Iterate months to compute metrics
    for m in range(months_total):
        # Determine year index for tax and loan payment cut‑off
        year_idx = min(m // 12, horizon - 1)
        # Revenue (competência), variable cost and cash receipts for this month
        revenue_m = 0.0
        var_cost_m = 0.0
        cash_receipt_m = 0.0
        # Build new list to update next loop outside (we will reassign after loop)
        new_prev_rev_per_prod: List[float] = []
        for idx, prod in enumerate(state.get("revenue", [])):
            monthly_data = normalized_monthlies[idx]
            m_data = monthly_data[m]
            qty_m = float(m_data.get("qty", 0.0)) * variation
            price_m = float(m_data.get("price", 0.0))
            rev_i_m = price_m * qty_m
            revenue_m += rev_i_m
            var_cost_m += (cost_per_unit_list[idx] + var_cost_per_unit_list[idx]) * qty_m
            # Cash receipts: immediate part + previous month's credit
            credit_pct = float(prod.get("prazo", 0.0) or 0.0) / 100.0
            immediate_part = rev_i_m * (1.0 - credit_pct)
            prev_credit = prev_rev_per_prod[idx] * credit_pct
            cash_receipt_m += immediate_part + prev_credit
            # Update new_prev_rev list with current revenue for next iteration
            new_prev_rev_per_prod.append(rev_i_m)
        # After finishing products update prev_rev_per_prod list for next iteration
        prev_rev_per_prod = new_prev_rev_per_prod
        # Fixed cost for this month
        fixed_cost_m = opex_total_monthly
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
        invest_cf_m = capex_monthly[m]
        # Operational cash flow: cash receipts minus variable and fixed costs minus taxes
        oper_cf_m = cash_receipt_m - var_cost_m - fixed_cost_m - tax_m
        # Profit (competency regime): revenue (accrual) minus variable and fixed costs minus taxes minus loan payment
        profit_m = revenue_m - var_cost_m - fixed_cost_m - tax_m - (loan_payment_ann / 12.0 if (m // 12) < years else 0.0)
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
        c.drawString(50, y, f"{key}: R$ {value:,.2f}")
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

    The report includes the DRE (income statement) projections, cash flow
    projections, viability metrics, break‑even analysis and annual summaries.

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
                fr.append(f"R$ {val:,.2f}")
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
    cf_lines = ["\t".join(cf_header)] + [f"{int(row['Ano'])}\tR$ {row['Fluxo de Caixa']:,.2f}" for _, row in fc_df.iterrows()]
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
    be_lines.append(f"MC total: R$ {break_even_summary['mc']:,.2f}")
    be_lines.append(f"MC%: {break_even_summary['mc_percent']*100:.2f}%")
    be_lines.append(f"Custos Fixos (Ano 1): R$ {break_even_summary['fixed_costs']:,.2f}")
    if break_even_summary['revenue_be'] is not None:
        be_lines.append(f"Receita de PE: R$ {break_even_summary['revenue_be']:,.2f}")
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
                f"R$ {r[1]:,.2f}",
                f"R$ {r[2]:,.2f}",
                f"R$ {r[3]:,.2f}",
                f"R$ {r[4]:,.2f}",
                f"R$ {r[5]:,.2f}",
                f"{r[6]:.2f}%",
                f"R$ {r[7]:,.2f}",
                f"{r[8]:,.2f}",
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
                row_fmt.append(f"R$ {val:,.2f}")
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
        "opex": {"op": [], "adm": [], "sales": []},
        "capex": [],
        "financing": {},
        # variable_expenses will map each product index to a list of variable expenses.
        # Each expense has fields: desc (description) and value (per unit cost).
        "variable_expenses": {},
        # Tax configuration: whether to compute taxes and which annex of the
        # Simples Nacional applies. The annex determines nominal rates and
        # deductions used in the effective tax calculation. Default: no tax.
        "calculate_tax": False,
        "tax_annex": "I",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


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


def render_step_index() -> None:
    """Render a navigation index across all steps at the top of each page.

    This function displays a horizontal row of buttons (1–7), each representing
    a step of the wizard. Clicking a button updates the current step in
    ``st.session_state`` and triggers a rerun to navigate accordingly.
    """
    step_labels = [
        "1. Projeto",
        "2. Receitas",
        "3. Custos",
        "4. Opex",
        "5. CapEx",
        "6. Financiamento",
        "7. Resultados",
    ]
    cols = st.columns(len(step_labels))
    for idx, label in enumerate(step_labels):
        if cols[idx].button(label, key=f"nav_step_{idx+1}"):
            st.session_state.step = idx + 1
            safe_rerun()


def wizard_step1():
    """Step 1: Project identification."""
    st.header("Etapa 1 · Identificação do Projeto")
    # Display navigation index across all steps
    render_step_index()
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
            "opex": st.session_state.get("opex", {}),
            "capex": st.session_state.get("capex", []),
            "financing": st.session_state.get("financing", {}),
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
    st.header("Etapa 2 · Estrutura de Receitas")
    # Display navigation index across all steps
    render_step_index()
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
        st.session_state.revenue.append({"name": "", "price": 0.0, "qty": 0.0, "prazo": 0.0})
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
    """Step 3: Direct costs linked to each product/service."""
    st.header("Etapa 3 · Custos Diretos")
    # Display navigation index across all steps
    render_step_index()
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

        Preencha para cada item: nome, quantidade (por ciclo de produção), valor unitário e prazo de
        pagamento (dias). Estes dados são usados para calcular o custo direto unitário.
        """
    )
    # Loop through each product/service defined in revenue step
    for prod_index, product in enumerate(st.session_state.revenue):
        product_name = product.get("name") or f"Produto/Serviço {prod_index + 1}"
        st.subheader(f"Custos de {product_name}")
        # Ensure a list of cost items exists for this product index
        if prod_index not in st.session_state.costs:
            st.session_state.costs[prod_index] = []
        # Render each cost item for this product
        for i, item in enumerate(st.session_state.costs[prod_index]):
            with st.expander(f"Item de custo {i + 1}", expanded=True):
                name = st.text_input(
                    "Nome do Item", value=item.get("name", ""), key=f"cost_name_{prod_index}_{i}"
                )
                qty = st.number_input(
                    "Quantidade",
                    min_value=0.0,
                    value=float(item.get("qty", 0.0)),
                    step=1.0,
                    key=f"cost_qty_{prod_index}_{i}",
                )
                unit = st.number_input(
                    "Valor unitário (R$)",
                    min_value=0.0,
                    value=float(item.get("unit", 0.0)),
                    key=f"cost_unit_{prod_index}_{i}",
                )
                term = st.number_input(
                    "Prazo pag. (dias)",
                    min_value=0.0,
                    value=float(item.get("term", 0.0)),
                    key=f"cost_term_{prod_index}_{i}",
                )
                # Update the cost item in session state
                st.session_state.costs[prod_index][i] = {
                    "name": name,
                    "qty": qty,
                    "unit": unit,
                    "term": term,
                }
        # Button to add a cost item for this product
        if st.button(f"+ Adicionar custo para {product_name}", key=f"add_cost_{prod_index}"):
            st.session_state.costs[prod_index].append({"name": "", "qty": 0.0, "unit": 0.0, "term": 0.0})
            safe_rerun()
        # Variable expenses section for this product
        st.markdown(f"### Despesas Variáveis de {product_name}")
        # Ensure a list of variable expenses exists for this product index
        if prod_index not in st.session_state.variable_expenses:
            st.session_state.variable_expenses[prod_index] = []
        # Render each variable expense item using the same structure as cost items
        for vi, vitem in enumerate(st.session_state.variable_expenses[prod_index]):
            with st.expander(f"Despesa variável {vi + 1}", expanded=True):
                name = st.text_input(
                    "Nome do Item",
                    value=vitem.get("name", ""),
                    key=f"var_name_{prod_index}_{vi}",
                )
                qty = st.number_input(
                    "Quantidade",
                    min_value=0.0,
                    value=float(vitem.get("qty", 0.0)),
                    step=1.0,
                    key=f"var_qty_{prod_index}_{vi}",
                )
                unit = st.number_input(
                    "Valor unitário (R$)",
                    min_value=0.0,
                    value=float(vitem.get("unit", 0.0)),
                    key=f"var_unit_{prod_index}_{vi}",
                )
                term = st.number_input(
                    "Prazo pag. (dias)",
                    min_value=0.0,
                    value=float(vitem.get("term", 0.0)),
                    key=f"var_term_{prod_index}_{vi}",
                )
                # Update variable expense in session state
                st.session_state.variable_expenses[prod_index][vi] = {
                    "name": name,
                    "qty": qty,
                    "unit": unit,
                    "term": term,
                }
        # Button to add variable expense for this product
        if st.button(f"+ Adicionar despesa variável para {product_name}", key=f"add_var_exp_{prod_index}"):
            st.session_state.variable_expenses[prod_index].append({"name": "", "qty": 0.0, "unit": 0.0, "term": 0.0})
            safe_rerun()
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
    """Step 4: Operating expenses (Opex)."""
    st.header("Etapa 4 · Despesas Operacionais (Opex)")
    # Display navigation index across all steps
    render_step_index()
    # Explanation for operating expenses
    st.markdown(
        """
        As **despesas operacionais** são todos os gastos fixos que não variam diretamente com o volume
        de vendas ou produção. Elas são agrupadas em três categorias:

        * **Operacionais** – despesas necessárias para manter o negócio funcionando, como aluguel,
          energia, internet e manutenção.  

        * **Administrativas** – custos administrativos e de suporte, como salários de funcionários
          administrativos, contabilidade, honorários jurídicos e softwares de gestão.  

        * **De Vendas** – despesas relacionadas à promoção e comercialização, como marketing,
          publicidade, comissões fixas e salários de vendedores.  

        Para cada despesa, informe uma descrição e o valor **mensal**. Essas despesas compõem os
        **custos fixos** utilizados no cálculo do ponto de equilíbrio e nas projeções.
        """
    )
    categories = [("op", "Operacionais"), ("adm", "Administrativas"), ("sales", "De Vendas")]
    for cat_key, cat_name in categories:
        st.subheader(cat_name)
        # Render each expense for this category
        for i, exp in enumerate(st.session_state.opex.get(cat_key, [])):
            col1, col2 = st.columns([3, 1])
            with col1:
                desc = st.text_input("Descrição", value=exp.get("desc", ""), key=f"opex_desc_{cat_key}_{i}")
            with col2:
                val = st.number_input("Valor mensal (R$)", min_value=0.0, value=float(exp.get("value", 0.0)), key=f"opex_val_{cat_key}_{i}")
            st.session_state.opex[cat_key][i] = {"desc": desc, "value": val}
        if st.button(f"+ Adicionar despesa {cat_name.lower()}", key=f"add_opex_{cat_key}"):
            st.session_state.opex[cat_key].append({"desc": "", "value": 0.0})
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
    """Step 5: Investments (CapEx)."""
    st.header("Etapa 5 · Investimentos (CapEx)")
    # Display navigation index across all steps
    render_step_index()
    # Explanation for investments
    st.markdown(
        """
        Os **investimentos (CapEx)** representam gastos em ativos de longa duração necessários para
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
    for i, asset in enumerate(st.session_state.capex):
        with st.expander(f"Ativo {i + 1}", expanded=True):
            desc = st.text_input("Descrição", value=asset.get("desc", ""), key=f"capex_desc_{i}")
            val = st.number_input("Valor (R$)", min_value=0.0, value=float(asset.get("value", 0.0)), key=f"capex_val_{i}")
            month = st.number_input("Mês de aquisição", min_value=0, max_value=120, value=int(asset.get("month", 0)), step=1, key=f"capex_month_{i}")
            st.session_state.capex[i] = {"desc": desc, "value": val, "month": month}
    if st.button("+ Adicionar Ativo", key="add_capex"):
        st.session_state.capex.append({"desc": "", "value": 0.0, "month": 0})
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
    st.header("Etapa 6 · Estrutura de Capital")
    # Display navigation index across all steps
    render_step_index()
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
    loan_amount = st.number_input("Valor do Empréstimo (R$)", min_value=0.0, value=float(st.session_state.financing.get("amount", 0.0)))
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
    st.header("Etapa 7 · Resultados e Análises")
    # Display navigation index across all steps
    render_step_index()
    # Explanation for results and analyses
    st.markdown(
        """
        Aqui você visualiza as projeções consolidadas, indicadores de viabilidade e análises finais:

        * **Projeções (BP/DRE)** – mostram a receita, custos, despesas, tributos e lucro por ano.
        * **Fluxo de Caixa (FC)** – demonstra os fluxos anuais de caixa, úteis para calcular VPL, TIR
          e payback.
        * **Análise de Viabilidade** – apresenta indicadores como VPL (Valor Presente Líquido),
          TIR (Taxa Interna de Retorno), TIRm (modificada) e Payback.
        * **Ponto de Equilíbrio (PE)** – calcula a margem de contribuição, custos fixos e a receita
          necessária para cobrir os custos, além da contribuição individual de cada produto.
        * **Projeção Mensal e Anual (Fluxo de Caixa e Resultado)** – detalha, mês a mês e ano a ano,
          a receita, custos variáveis e fixos, tributos, lucro e a decomposição do fluxo de caixa em
          **operacional**, **financeiro** e **investimento** (regimes de caixa e competência).  

        Ajuste a **Variação da quantidade de vendas** para simular cenários de aumento ou queda nas
        vendas e observe o impacto nos indicadores. Informe também a **taxa de desconto** para o
        cálculo do VPL.
        """
    )
    # Allow user to define scenario variation and discount rate
    st.subheader("Configurações de Cenário e Taxa de Desconto")
    col_var, col_rate = st.columns([1, 1])
    with col_var:
        variation_pct = st.slider(
            "Variação da quantidade de vendas (%)",
            min_value=-50.0,
            max_value=50.0,
            value=0.0,
            step=5.0,
        )
    with col_rate:
        discount_rate_input = st.number_input(
            "Taxa de desconto anual (%)",
            min_value=0.0,
            max_value=100.0,
            value=10.0,
            step=0.1,
        )
    variation_factor = 1.0 + variation_pct / 100.0
    discount_rate = discount_rate_input / 100.0
    # Compute projections and cash flows for the chosen scenario
    projections, cashflows, capex_total = compute_projections(st.session_state, variation=variation_factor)
    # Display income statement (DRE) excluding year 0
    st.subheader("Demonstração do Resultado do Exercício (Regime de Competência)")
    df_dre = pd.DataFrame(
        [p for p in projections[1:]],
        columns=["Ano", "Receita", "Custos", "Opex", "Pagamento Empréstimo", "Tributos", "Lucro"],
    )
    st.dataframe(
        df_dre.style.format(
            {
                "Receita": "R$ {:,.2f}",
                "Custos": "R$ {:,.2f}",
                "Opex": "R$ {:,.2f}",
                "Pagamento Empréstimo": "R$ {:,.2f}",
                "Tributos": "R$ {:,.2f}",
                "Lucro": "R$ {:,.2f}",
            }
        ),
        use_container_width=True,
    )
    # Compute cash flow projection (FC)
    st.subheader("Demonstração dos Fluxos de Caixa (Regime de Caixa)")
    df_fc = pd.DataFrame(
        {
            "Ano": list(range(len(cashflows))),
            "Fluxo de Caixa": cashflows,
        }
    )
    st.dataframe(df_fc.style.format({"Fluxo de Caixa": "R$ {:,.2f}"}), use_container_width=True)
    # Plot the cash flow over time
    st.line_chart(df_fc.set_index("Ano"))
    # Compute viability metrics
    npv = compute_npv(cashflows, discount_rate)
    irr = compute_irr(cashflows)  # returns a decimal or None
    mirr = compute_mirr(cashflows, finance_rate=discount_rate, reinvest_rate=discount_rate)
    payback, discounted_payback = compute_payback(cashflows, discount_rate)
    # Display viability summary
    st.subheader("Análise de Viabilidade")
    metrics_table = pd.DataFrame(
        {
            "Indicador": ["VPL (NPV)", "TIR", "TIRm", "Payback (anos)", "Payback Descontado (anos)"],
            "Valor": [
                f"R$ {npv:,.2f}",
                f"{irr * 100:.2f}%" if irr is not None else "N/D",
                f"{mirr * 100:.2f}%" if mirr is not None else "N/D",
                str(payback) if payback is not None else "> horizonte",
                str(discounted_payback) if discounted_payback is not None else "> horizonte",
            ],
        }
    )
    st.table(metrics_table)
    # Provide summary metrics similar to earlier summary for context
    summary = compute_summary(st.session_state)
    st.subheader("Resumo Financeiro (Ano 1 – caso base)")
    st.table(pd.DataFrame({"Categoria": summary.keys(), "Valor": summary.values()}))
    # Generate downloadable files based on base summary
    pdf_data = generate_pdf(summary)
    st.download_button(
        label="Baixar PDF (Resumo Base)",
        data=pdf_data,
        file_name="relatorio_financeiro.pdf",
        mime="application/pdf",
        key="download_pdf_base",
    )
    excel_data = generate_excel(summary)
    st.download_button(
        label="Baixar Excel (Resumo Base)",
        data=excel_data,
        file_name="relatorio_financeiro.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_excel_base",
    )

    # Compute break-even analysis early for reuse in PDF and display
    be = compute_break_even(st.session_state, variation_factor)
    df_be_prod = pd.DataFrame()
    if be:
        # Build DataFrame for break-even analysis. The order of columns emphasizes
        # price (P), unit variable cost (CVu) and unit variable expense (DVu),
        # followed by contribution margins and break-even figures.  The margin per
        # unit is computed as P - CVu - DVu and stored in the state already.
        df_be_prod = pd.DataFrame([
            {
                "Produto/Serviço": p["name"],
                "Preço (P)": p.get("price", 0.0),
                "Custo variável unitário (CVu)": p.get("cost_unit", 0.0),
                "Despesa variável unitária (DVu)": p.get("var_unit", 0.0),
                "Margem de Contribuição unitária (MCu)": p.get("mc_unit", 0.0),
                "Margem de Contribuição total (MCt)": p.get("mc_total", 0.0),
                "Participação (%)": p["share"] * 100.0,
                "Receita de PE (R$)": p["revenue_be"],
                "Quantidade de PE": p["quantity_be"],
            }
            for p in be["product_breakdown"]
        ])

    # Compute monthly and annual details for the selected scenario
    df_month, df_ann = compute_monthly_details(st.session_state, variation_factor)

    # Offer full PDF export with all analyses
    try:
        full_pdf_data = generate_full_pdf(
            project_name=st.session_state.get("project_name", "Projeto"),
            horizon=int(st.session_state.get("horizon", 1) or 1),
            variation_pct=variation_pct,
            discount_rate=discount_rate,
            dre_df=df_dre,
            fc_df=pd.DataFrame({"Ano": list(range(len(cashflows))), "Fluxo de Caixa": cashflows}),
            metrics_df=metrics_table,
            break_even_summary=be if be else {},
            break_even_df=df_be_prod if not df_be_prod.empty else pd.DataFrame(),
            ann_df=df_ann,
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

    # Break-even analysis and contribution margin
    if be:
        st.subheader("Ponto de Equilíbrio (PE) e Margem de Contribuição")
        st.markdown(f"**Margem de Contribuição (MC):** R$ {be['mc']:,.2f}")
        st.markdown(f"**Margem de Contribuição (%):** {be['mc_percent'] * 100:.2f}%")
        st.markdown(f"**Custos Fixos (Ano 1):** R$ {be['fixed_costs']:,.2f}")
        if be['revenue_be'] is not None:
            st.markdown(f"**Receita de Ponto de Equilíbrio:** R$ {be['revenue_be']:,.2f}")
        else:
            st.markdown("**Receita de Ponto de Equilíbrio:** N/D")
        st.dataframe(
            df_be_prod.style.format(
                {
                    "Participação (%)": "{:.2f}",
                    "Receita de PE (R$)": "R$ {:,.2f}",
                    "Quantidade de PE": "{:.2f}",
                    "Margem de Contribuição unitária (MCu)": "R$ {:,.2f}",
                    "Margem de Contribuição total (MCt)": "R$ {:,.2f}",
                    "Preço (P)": "R$ {:,.2f}",
                    "Custo variável unitário (CVu)": "R$ {:,.2f}",
                    "Despesa variável unitária (DVu)": "R$ {:,.2f}",
                }
            ),
            use_container_width=True,
        )

    # Separate monthly and annual projections into DRE (competência) and DFC (caixa)
    # Present individual sections for clarity
    # Monthly Income Statement (DRE) – accrual basis
    st.subheader("Projeções Mensais – Demonstração do Resultado (Competência)")
    df_month_dre = df_month[["Mês", "Receita", "Custo Variável", "Custo Fixo", "Tributos", "Lucro"]]
    st.dataframe(
        df_month_dre.style.format(
            {
                "Receita": "R$ {:,.2f}",
                "Custo Variável": "R$ {:,.2f}",
                "Custo Fixo": "R$ {:,.2f}",
                "Tributos": "R$ {:,.2f}",
                "Lucro": "R$ {:,.2f}",
            }
        ),
        use_container_width=True,
    )
    # Monthly Cash Flow – cash basis
    st.subheader("Projeções Mensais – Fluxo de Caixa (Regime de Caixa)")
    df_month_dfc = df_month[["Mês", "Receita Caixa", "Custo Variável", "Custo Fixo", "Tributos", "CF Operacional", "CF Financeiro", "CF Investimento", "CF Total"]]
    st.dataframe(
        df_month_dfc.style.format(
            {
                "Receita Caixa": "R$ {:,.2f}",
                "Custo Variável": "R$ {:,.2f}",
                "Custo Fixo": "R$ {:,.2f}",
                "Tributos": "R$ {:,.2f}",
                "CF Operacional": "R$ {:,.2f}",
                "CF Financeiro": "R$ {:,.2f}",
                "CF Investimento": "R$ {:,.2f}",
                "CF Total": "R$ {:,.2f}",
            }
        ),
        use_container_width=True,
    )
    # Annual Income Statement (DRE) – accrual basis
    st.subheader("Projeções Anuais – Demonstração do Resultado (Competência)")
    df_ann_dre = df_ann[["Ano", "Receita", "Custo Variável", "Custo Fixo", "Tributos", "Lucro"]]
    st.dataframe(
        df_ann_dre.style.format(
            {
                "Receita": "R$ {:,.2f}",
                "Custo Variável": "R$ {:,.2f}",
                "Custo Fixo": "R$ {:,.2f}",
                "Tributos": "R$ {:,.2f}",
                "Lucro": "R$ {:,.2f}",
            }
        ),
        use_container_width=True,
    )
    # Annual Cash Flow – cash basis
    st.subheader("Projeções Anuais – Fluxo de Caixa (Regime de Caixa)")
    df_ann_dfc = df_ann[["Ano", "Receita Caixa", "Custo Variável", "Custo Fixo", "Tributos", "CF Operacional", "CF Financeiro", "CF Investimento", "CF Total"]]
    st.dataframe(
        df_ann_dfc.style.format(
            {
                "Receita Caixa": "R$ {:,.2f}",
                "Custo Variável": "R$ {:,.2f}",
                "Custo Fixo": "R$ {:,.2f}",
                "Tributos": "R$ {:,.2f}",
                "CF Operacional": "R$ {:,.2f}",
                "CF Financeiro": "R$ {:,.2f}",
                "CF Investimento": "R$ {:,.2f}",
                "CF Total": "R$ {:,.2f}",
            }
        ),
        use_container_width=True,
    )
    # Navigation buttons
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("◂ Voltar", key="back7"):
            st.session_state.step = 6
            safe_rerun()
    with col2:
        if st.button("Reiniciar", key="restart7"):
            # Reset session state to start again
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            init_state()
            safe_rerun()


def main():
    st.set_page_config(page_title="Assistente Financeiro", page_icon="💰", layout="centered")
    init_state()
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
    elif step == 6:
        wizard_step6()
    elif step == 7:
        wizard_step7()


if __name__ == "__main__":
    main()