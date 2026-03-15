import streamlit as st
import pandas as pd
import numpy as np
import math
import io
from datetime import datetime

# --- PAGE CONFIG ---
st.set_page_config(page_title="Clinic Inventory Suite", layout="wide", page_icon="🦷")

# --- CACHED FUNCTIONS (Mobile Stability) ---
@st.cache_data
def get_amu_data(uploaded_files):
    if not uploaded_files: return pd.DataFrame()
    dfs = [pd.read_excel(f, engine='openpyxl') for f in uploaded_files]
    return pd.concat(dfs, ignore_index=True)

@st.cache_data
def get_stock_data(uploaded_file):
    if not uploaded_file: return None
    df = pd.read_excel(uploaded_file, engine='openpyxl')
    if len(df.columns) < 7: return "ERR_COLS"
    df_s2 = df.iloc[:, [1, 3, 5, 6]].dropna(how='all')
    df_s2.columns = ["Item", "Type_S2", "Branch", "Master"]
    return df_s2

# --- INITIALIZE DATA ---
if 'usage_raw' not in st.session_state: st.session_state.usage_raw = pd.DataFrame()
if 'stock_df' not in st.session_state: st.session_state.stock_df = None
if 'shared_amu' not in st.session_state: st.session_state.shared_amu = None

st.title("🦷 Clinic Inventory Hub")

# --- MAIN NAVIGATION ---
main_tab1, main_tab2 = st.tabs(["📊 APP 1: AMU Engine", "🛒 APP 2: Smart Shopping List"])

# ---------------------------------------------------------
# APP 1: AMU ENGINE
# ---------------------------------------------------------
with main_tab1:
    # Sub-tabs for App 1
    t1_upload, t1_filter, t1_consolidate, t1_final = st.tabs([
        "1.a Upload", "1.b Filtering", "1.c Consolidation", "1.d AMU Calc"
    ])

    with t1_upload:
        st.subheader("Upload Usage Data")
        files = st.file_uploader("Upload Excel exports", accept_multiple_files=True, key="up_amu")
        stock_f = st.file_uploader("Upload Sheet 2 (For Shopping List)", type=["xlsx"], key="up_stock")
        
        if st.button("🚀 Process & Sync All Files", use_container_width=True):
            if files:
                st.session_state.usage_raw = get_amu_data(files)
                st.success("Usage records synced.")
            if stock_f:
                res = get_stock_data(stock_f)
                if res == "ERR_COLS": st.error("Sheet 2 missing columns.")
                else: 
                    st.session_state.stock_df = res
                    st.success("Stock records synced.")

    with t1_filter:
        if not st.session_state.usage_raw.empty:
            st.subheader("Filtered Data (C, F, I, K, M)")
            cols = [2, 5, 8, 10, 12]
            df_f = st.session_state.usage_raw.iloc[:, cols].copy()
            df_f.columns = ['Amount', 'Price', 'Item', 'Type', 'Created']
            st.dataframe(df_f, use_container_width=True)
            st.session_state.filtered_view = df_f
        else:
            st.info("Upload data in 1.a first.")

    with t1_consolidate:
        if 'filtered_view' in st.session_state:
            df = st.session_state.filtered_view.copy()
            df['Created'] = pd.to_datetime(df['Created'], errors='coerce')
            cons = df.groupby(['Item', 'Type']).agg({
                'Amount': 'sum', 'Price': 'max', 'Created': 'min'
            }).reset_index()
            
            today = pd.to_datetime(datetime.now())
            cons['No. of Months'] = cons['Created'].apply(
                lambda x: max(1, round((today - x).days / 30, 2)) if pd.notnull(x) else 1
            )
            st.dataframe(cons, use_container_width=True)
            st.session_state.cons_view = cons
        else:
            st.info("No data to consolidate.")

    with t1_final:
        if 'cons_view' in st.session_state:
            df_final = st.session_state.cons_view.copy()
            df_final['AMU'] = (df_final['Amount'] / df_final['No. of Months']).round(2)
            st.session_state.shared_amu = df_final[['Item', 'Type', 'Price', 'AMU']]
            st.dataframe(df_final[['Item', 'Type', 'AMU', 'Price']], use_container_width=True)
        else:
            st.info("Run consolidation first.")

# ---------------------------------------------------------
# APP 2: SMART SHOPPING LIST
# ---------------------------------------------------------
with main_tab2:
    t2_match, t2_forecast, t2_shopping = st.tabs([
        "2.a Match Check", "2.b Depletion Forecast", "2.c Shopping List"
    ])

    if st.session_state.shared_amu is None or st.session_state.stock_df is None:
        st.warning("⚠️ Please upload both sets of data in App 1 (1.a) to unlock these features.")
    else:
        # Core Calculation for App 2
        df_a = st.session_state.shared_amu.copy()
        df_s = st.session_state.stock_df.copy()
        df_a['MKey'] = df_a['Item'].astype(str).str.strip().str.lower()
        df_s['MKey'] = df_s['Item'].astype(str).str.strip().str.lower()
        merged = pd.merge(df_a, df_s.drop(columns=['Item']), on="MKey", how="inner")

        def calc_target(row):
            m = float(row['Master']) if pd.notnull(row['Master']) else 0
            a = float(row['AMU']) if pd.notnull(row['AMU']) else 0
            months = math.ceil(m / a) if a > 0 else 0
            return (datetime.now().date() + pd.DateOffset(months=months)).replace(day=1)

        merged['TargetDate'] = pd.to_datetime(merged.apply(calc_target, axis=1))

        with t2_match:
            st.subheader("Linked Items")
            st.dataframe(merged[['Item', 'Type', 'AMU', 'Branch', 'Master']], use_container_width=True)

        with t2_forecast:
            st.subheader("Stock Depletion Timeline")
            forecast = merged[['Item', 'Master', 'AMU', 'TargetDate']].copy()
            forecast['TargetDate'] = forecast['TargetDate'].dt.strftime('%B %Y')
            st.dataframe(forecast, use_container_width=True)

        with t2_shopping:
            st.subheader("Interactive Shopping List")
            start_m = datetime.now().date().replace(day=1)
            for i in range(3):
                curr = (pd.Timestamp(start_m) + pd.DateOffset(months=i))
                m_label = curr.strftime("%B %Y")
                
                mask = (merged['TargetDate'].dt.month == curr.month) & (merged['TargetDate'].dt.year == curr.year)
                m_df = merged[mask].copy()
                
                with st.expander(f"📅 {m_label}", expanded=(i==0)):
                    if not m_df.empty:
                        # Logic: <1 = 1, >=1 = Round Up
                        m_df['Order'] = m_df['AMU'].apply(lambda x: 1.0 if x < 1 else float(math.ceil(x)))
                        total = (m_df['Price'] * m_df['Order']).sum()
                        st.metric("Total Order Cost", f"${total:,.2f}")
                        st.dataframe(m_df[['Item', 'Type', 'Price', 'AMU', 'Branch', 'Master']], use_container_width=True)
                    else:
                        st.write("No items due for purchase.")
