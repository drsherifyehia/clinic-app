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
    try:
        df = pd.read_excel(uploaded_file, engine='openpyxl')
        if len(df.columns) < 7: 
            return "ERR_COLS"
        # Select Columns B, D, F, G (Indices 1, 3, 5, 6)
        df_s2 = df.iloc[:, [1, 3, 5, 6]].dropna(how='all')
        df_s2.columns = ["Item", "Type_S2", "Branch", "Master"]
        return df_s2
    except Exception as e:
        return f"ERR_FILE: {str(e)}"

# --- INITIALIZE SESSION STATES ---
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
    t1_upload, t1_filter, t1_consolidate, t1_final = st.tabs([
        "1.a Upload", "1.b Filtering", "1.c Consolidation", "1.d AMU Calc"
    ])

    with t1_upload:
        st.subheader("Step 1: File Intake")
        amu_files = st.file_uploader("Upload Usage Exports", accept_multiple_files=True, key="up_amu")
        stock_file = st.file_uploader("Upload Sheet 2 (Stock Levels)", type=["xlsx"], key="up_stock")
        
        if st.button("🚀 Process & Sync All Files", use_container_width=True):
            if amu_files:
                st.session_state.usage_raw = get_amu_data(amu_files)
                st.success("Usage records synced.")
            
            if stock_file:
                res = get_stock_data(stock_file)
                # FIX: Check if res is a string (Error) or DataFrame (Success)
                if isinstance(res, str):
                    if "ERR_COLS" in res:
                        st.error("Sheet 2 is missing columns. It must have data up to Column G.")
                    else:
                        st.error(f"Error: {res}")
                else:
                    st.session_state.stock_df = res
                    st.success("Stock records synced.")

    with t1_filter:
        if not st.session_state.usage_raw.empty:
            st.subheader("Filtered Usage Data")
            # Columns C, F, I, K, M
            cols_idx = [2, 5, 8, 10, 12]
            df_f = st.session_state.usage_raw.iloc[:, cols_idx].copy()
            df_f.columns = ['Amount', 'Price', 'Item', 'Type', 'Created']
            st.session_state.filtered_view = df_f
            st.dataframe(df_f, use_container_width=True)
        else:
            st.info("Please upload data in tab 1.a and click 'Process'.")

    with t1_consolidate:
        if 'filtered_view' in st.session_state:
            st.subheader("Consolidated View")
            df = st.session_state.filtered_view.copy()
            df['Created'] = pd.to_datetime(df['Created'], errors='coerce')
            cons = df.groupby(['Item', 'Type']).agg({
                'Amount': 'sum', 'Price': 'max', 'Created': 'min'
            }).reset_index()
            
            today = pd.to_datetime(datetime.now())
            cons['No. of Months'] = cons['Created'].apply(
                lambda x: max(1, round((today - x).days / 30, 2)) if pd.notnull(x) else 1
            )
            st.session_state.cons_view = cons
            st.dataframe(cons, use_container_width=True)
        else:
            st.info("No filtered data found.")

    with t1_final:
        if 'cons_view' in st.session_state:
            st.subheader("Final AMU Results")
            df_final = st.session_state.cons_view.copy()
            df_final['AMU'] = (df_final['Amount'] / df_final['No. of Months']).round(2)
            # Sync to shared memory for App 2
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
        st.warning("⚠️ Waiting for data from App 1. Ensure you uploaded both sets of files.")
    else:
        # Cross-App Merging Logic
        df_a = st.session_state.shared_amu.copy()
        df_s = st.session_state.stock_df.copy()
        
        df_a['MKey'] = df_a['Item'].astype(str).str.strip().str.lower()
        df_s['MKey'] = df_s['Item'].astype(str).str.strip().str.lower()
        
        merged = pd.merge(df_a, df_s.drop(columns=['Item']), on="MKey", how="inner")

        def calc_target(row):
            try:
                m = float(row['Master']) if pd.notnull(row['Master']) else 0
                a = float(row['AMU']) if pd.notnull(row['AMU']) else 0
                months = math.ceil(m / a) if a > 0 else 0
                return (datetime.now().date() + pd.DateOffset(months=months)).replace(day=1)
            except: return datetime.now().date().replace(day=1)

        merged['TargetDate'] = pd.to_datetime(merged.apply(calc_target, axis=1))

        with t2_match:
            st.subheader("Linked Database")
            st.dataframe(merged[['Item', 'Type', 'AMU', 'Branch', 'Master']], use_container_width=True)

        with t2_forecast:
            st.subheader("Inventory Life Expectancy")
            forecast = merged[['Item', 'Master', 'AMU', 'TargetDate']].copy()
            forecast['TargetDate'] = forecast['TargetDate'].dt.strftime('%B %Y')
            st.dataframe(forecast, use_container_width=True)

        with t2_shopping:
            st.subheader("Smart Purchase Orders")
            start_m = datetime.now().date().replace(day=1)
            
            # Show the next 3 months as interactive sections
            for i in range(3):
                curr = (pd.Timestamp(start_m) + pd.DateOffset(months=i))
                m_label = curr.strftime("%B %Y")
                
                mask = (merged['TargetDate'].dt.month == curr.month) & (merged['TargetDate'].dt.year == curr.year)
                month_data = merged[mask].copy()
                
                with st.expander(f"📅 {m_label}", expanded=(i==0)):
                    if not month_data.empty:
                        # Apply clinical rounding: <1 = 1, >=1 = CEIL
                        month_data['Order'] = month_data['AMU'].apply(lambda x: 1.0 if x < 1 else float(math.ceil(x)))
                        total = (month_data['Price'] * month_data['Order']).sum()
                        
                        st.metric("Estimated Expenditure", f"${total:,.2f}")
                        st.dataframe(month_data[['Item', 'Type', 'Price', 'AMU', 'Branch', 'Master']], use_container_width=True)
                    else:
                        st.write("No restocking required for this period.")
                st.divider()
