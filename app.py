import streamlit as st
import pandas as pd
import numpy as np
import math
import io
from datetime import datetime

# --- PAGE CONFIG ---
st.set_page_config(page_title="Clinic Inventory Suite", layout="wide", page_icon="🦷")

# --- CACHED FUNCTIONS (Stability) ---
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
        if len(df.columns) < 7: return "ERR_COLS"
        # Select B, D, F, G (Indices 1, 3, 5, 6)
        df_s2 = df.iloc[:, [1, 3, 5, 6]].dropna(how='all')
        df_s2.columns = ["Item", "Type_S2", "Branch", "Master"]
        return df_s2
    except Exception as e:
        return f"ERR_FILE: {str(e)}"

# --- INITIALIZE SESSION STATES ---
if 'usage_raw' not in st.session_state: st.session_state.usage_raw = pd.DataFrame()
if 'stock_df' not in st.session_state: st.session_state.stock_df = None
if 'shared_amu' not in st.session_state: st.session_state.shared_amu = None
if 'merged_data' not in st.session_state: st.session_state.merged_data = None

st.title("🦷 Clinic Inventory Hub")

# --- 4 MAIN TABS ---
tab_upload, tab_app1, tab_app2, tab_shop = st.tabs([
    "📂 1. Upload", 
    "📊 2. App 1 (AMU)", 
    "⚙️ 3. App 2 (Data)", 
    "🛒 4. Shopping List"
])

# ---------------------------------------------------------
# TAB 1: UPLOAD
# ---------------------------------------------------------
with tab_upload:
    st.header("Data Upload Center")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Usage Records")
        amu_files = st.file_uploader("Upload AMU Exports", accept_multiple_files=True, key="up_amu")
    
    with col2:
        st.subheader("Stock Levels")
        stock_f = st.file_uploader("Upload Sheet 2", type=["xlsx"], key="up_stock")

    if st.button("🚀 Process & Sync All Data", use_container_width=True):
        if amu_files:
            st.session_state.usage_raw = get_amu_data(amu_files)
            st.success("✅ Usage records synced.")
        if stock_f:
            res = get_stock_data(stock_f)
            if isinstance(res, str):
                st.error(f"Error: {res}")
            else:
                st.session_state.stock_df = res
                st.success("✅ Stock records synced.")

# ---------------------------------------------------------
# TAB 2: APP 1 (AMU ENGINE)
# ---------------------------------------------------------
with tab_app1:
    if st.session_state.usage_raw.empty:
        st.warning("Please upload usage data in Tab 1.")
    else:
        sub1_filter, sub1_cons, sub1_final = st.tabs(["1.a Filtering", "1.b Consolidation", "1.c Final AMU"])

        # Data processing
        cols_idx = [2, 5, 8, 10, 12] # C, F, I, K, M
        df_f = st.session_state.usage_raw.iloc[:, cols_idx].copy()
        df_f.columns = ['Amount', 'Price', 'Item', 'Type', 'Created']
        df_f['Created'] = pd.to_datetime(df_f['Created'], errors='coerce')

        with sub1_filter:
            st.subheader("Filtered Data")
            st.dataframe(df_f, use_container_width=True)

        with sub1_cons:
            st.subheader("Consolidated Data")
            cons = df_f.groupby(['Item', 'Type']).agg({
                'Amount': 'sum', 'Price': 'max', 'Created': 'min'
            }).reset_index()
            today = pd.to_datetime(datetime.now())
            cons['No. of Months'] = cons['Created'].apply(
                lambda x: max(1, round((today - x).days / 30, 2)) if pd.notnull(x) else 1
            )
            st.dataframe(cons, use_container_width=True)

        with sub1_final:
            st.subheader("AMU Calculation")
            df_final = cons.copy()
            df_final['AMU'] = (df_final['Amount'] / df_final['No. of Months']).round(2)
            st.session_state.shared_amu = df_final[['Item', 'Type', 'Price', 'AMU']]
            st.dataframe(df_final[['Item', 'Type', 'AMU', 'Price']], use_container_width=True)

# ---------------------------------------------------------
# TAB 3: APP 2 (MATCH & FORECAST)
# ---------------------------------------------------------
with tab_app2:
    if st.session_state.shared_amu is None or st.session_state.stock_df is None:
        st.warning("⚠️ Process both Usage and Stock data in Tab 1, and ensure App 1 has run.")
    else:
        sub2_match, sub2_forecast = st.tabs(["2.a Match Check", "2.b Depletion Forecast"])
        
        # Merging Logic
        df_a = st.session_state.shared_amu.copy()
        df_s = st.session_state.stock_df.copy()
        df_a['MKey'] = df_a['Item'].astype(str).str.strip().str.lower()
        df_s['MKey'] = df_s['Item'].astype(str).str.strip().str.lower()
        merged = pd.merge(df_a, df_s.drop(columns=['Item']), on="MKey", how="inner")

        def calc_target(row):
            m, a = float(row['Master'] or 0), float(row['AMU'] or 0)
            months = math.ceil(m / a) if a > 0 else 0
            return (datetime.now().date() + pd.DateOffset(months=months)).replace(day=1)

        merged['TargetDate'] = pd.to_datetime(merged.apply(calc_target, axis=1))
        st.session_state.merged_data = merged

        with sub2_match:
            st.subheader("Linked Database")
            st.dataframe(merged[['Item', 'Type', 'AMU', 'Branch', 'Master']], use_container_width=True)

        with sub2_forecast:
            st.subheader("Inventory Life Expectancy")
            forecast = merged[['Item', 'Master', 'AMU', 'TargetDate']].copy()
            forecast['TargetDate'] = forecast['TargetDate'].dt.strftime('%B %Y')
            st.dataframe(forecast, use_container_width=True)

# ---------------------------------------------------------
# TAB 4: SHOPPING LIST
# ---------------------------------------------------------
with tab_shop:
    if 'merged_data' not in st.session_state or st.session_state.merged_data is None:
        st.warning("⚠️ Ensure data is matched in Tab 3 before viewing the Shopping List.")
    else:
        st.header("Interactive Shopping List")
        merged = st.session_state.merged_data
        
        # --- 1. Month Dropdown ---
        start_m = datetime.now().date().replace(day=1)
        month_options = [(start_m + pd.DateOffset(months=i)).strftime("%B %Y") for i in range(12)]
        
        col_m, col_t = st.columns([1, 2])
        with col_m:
            selected_month_str = st.selectbox("📅 Select Target Month", month_options)
            selected_month_dt = pd.to_datetime(selected_month_str)
            
        # --- 2. Type Filter ---
        with col_t:
            all_types = sorted(merged['Type'].dropna().astype(str).unique())
            selected_types = st.multiselect("🏷️ Filter by Type", all_types, default=all_types)

        st.divider()

        # --- Filter the Data ---
        mask = (merged['TargetDate'].dt.month == selected_month_dt.month) & \
               (merged['TargetDate'].dt.year == selected_month_dt.year) & \
               (merged['Type'].isin(selected_types))
        
        m_df = merged[mask].copy()

        if not m_df.empty:
            # --- Calculate Quantities ---
            # Qty if buying strictly 1 piece of everything
            m_df['Qty_Single'] = 1 
            
            # Qty based on AMU Logic (<1 -> 1, fractions rounded up)
            m_df['Qty_AMU'] = m_df['AMU'].apply(lambda x: 1.0 if x < 1 else float(math.ceil(x)))
            
            # Calculate Costs
            cost_single = (m_df['Price'] * m_df['Qty_Single']).sum()
            cost_amu = (m_df['Price'] * m_df['Qty_AMU']).sum()

            # --- 3. Dual Cost Metrics ---
            m_col1, m_col2 = st.columns(2)
            m_col1.metric("Est. Cost (1 Piece Each)", f"${cost_single:,.2f}")
            m_col2.metric("Est. Cost (AMU Based)", f"${cost_amu:,.2f}")
            
            st.markdown(f"**Items required for {selected_month_str}:**")
            
            # Reorder columns for display to make it intuitive
            display_cols = ['Item', 'Type', 'Price', 'AMU', 'Qty_AMU', 'Branch', 'Master']
            st.dataframe(m_df[display_cols], use_container_width=True)
            
        else:
            st.info(f"No restocking required for **{selected_month_str}** with the selected types.")
