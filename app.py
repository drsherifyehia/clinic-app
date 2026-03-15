import streamlit as st
import pandas as pd
import numpy as np
import math
from datetime import datetime

# --- PAGE CONFIG ---
st.set_page_config(page_title="Clinic Inventory Hub", layout="wide", page_icon="🦷")

# --- CACHED FUNCTIONS ---
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
        df_s2 = df.iloc[:, [1, 3, 5, 6]].dropna(how='all')
        df_s2.columns = ["Item", "Type_S2", "Branch", "Master"]
        return df_s2
    except Exception as e:
        return f"ERR_FILE: {str(e)}"

# --- INITIALIZE SESSION STATES ---
for key in ['usage_raw', 'stock_df', 'shared_amu', 'merged_data']:
    if key not in st.session_state:
        st.session_state[key] = None if key != 'usage_raw' else pd.DataFrame()

st.title("🦷 Clinic Inventory Hub")

# --- 4 MAIN TABS ---
tab_upload, tab_app1, tab_app2, tab_shop = st.tabs([
    "📂 1. Upload", "📊 2. App 1 (AMU)", "⚙️ 3. App 2 (Data)", "🛒 4. Shopping List"
])

# ---------------------------------------------------------
# TAB 1: UPLOAD
# ---------------------------------------------------------
with tab_upload:
    st.header("Data Upload Center")
    col1, col2 = st.columns(2)
    with col1:
        amu_files = st.file_uploader("Upload AMU Exports", accept_multiple_files=True)
    with col2:
        stock_f = st.file_uploader("Upload Sheet 2", type=["xlsx"])

    if st.button("🚀 Process & Sync All Data", use_container_width=True):
        if amu_files:
            st.session_state.usage_raw = get_amu_data(amu_files)
            st.success("✅ Usage records synced.")
        if stock_f:
            res = get_stock_data(stock_f)
            if isinstance(res, str): st.error(f"Error: {res}")
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
        df_f = st.session_state.usage_raw.iloc[:, [2, 5, 8, 10, 12]].copy()
        df_f.columns = ['Amount', 'Price', 'Item', 'Type', 'Created']
        df_f['Created'] = pd.to_datetime(df_f['Created'], errors='coerce')

        with sub1_filter: st.dataframe(df_f, use_container_width=True)
        with sub1_cons:
            cons = df_f.groupby(['Item', 'Type']).agg({'Amount': 'sum', 'Price': 'max', 'Created': 'min'}).reset_index()
            cons['No. of Months'] = cons['Created'].apply(lambda x: max(1, round((pd.to_datetime(datetime.now()) - x).days / 30, 2)) if pd.notnull(x) else 1)
            st.dataframe(cons, use_container_width=True)
            st.session_state.cons_cache = cons
        with sub1_final:
            df_final = st.session_state.cons_cache.copy()
            df_final['AMU'] = (df_final['Amount'] / df_final['No. of Months']).round(2)
            st.session_state.shared_amu = df_final[['Item', 'Type', 'Price', 'AMU']]
            st.dataframe(df_final, use_container_width=True)

# ---------------------------------------------------------
# TAB 3: APP 2 (DATA MATCHING)
# ---------------------------------------------------------
with tab_app2:
    if st.session_state.shared_amu is None or st.session_state.stock_df is None:
        st.warning("⚠️ Sync both files in Tab 1 first.")
    else:
        sub2_match, sub2_forecast = st.tabs(["2.a Match Check", "2.b Depletion Forecast"])
        df_a, df_s = st.session_state.shared_amu.copy(), st.session_state.stock_df.copy()
        df_a['MKey'], df_s['MKey'] = df_a['Item'].str.strip().str.lower(), df_s['Item'].str.strip().str.lower()
        merged = pd.merge(df_a, df_s.drop(columns=['Item']), on="MKey", how="inner")

        def calc_target(row):
            m, a = float(row['Master'] or 0), float(row['AMU'] or 0)
            months = math.ceil(m / a) if a > 0 else 0
            return (datetime.now().date() + pd.DateOffset(months=months)).replace(day=1)

        merged['TargetDate'] = pd.to_datetime(merged.apply(calc_target, axis=1))
        st.session_state.merged_data = merged
        with sub2_match: st.dataframe(merged[['Item', 'Type', 'AMU', 'Branch', 'Master']], use_container_width=True)
        with sub2_forecast: st.dataframe(merged[['Item', 'Master', 'AMU', 'TargetDate']], use_container_width=True)

# ---------------------------------------------------------
# TAB 4: SHOPPING LIST (UPDATED WITH DROPDOWN & FILTERS)
# ---------------------------------------------------------
with tab_shop:
    if st.session_state.merged_data is None:
        st.warning("⚠️ Complete Data Matching in Tab 3 first.")
    else:
        st.header("Interactive Shopping List")
        merged = st.session_state.merged_data
        
        # 1. 12-Month Dropdown
        start_m = datetime.now().date().replace(day=1)
        month_list = [(start_m + pd.DateOffset(months=i)).strftime("%B %Y") for i in range(12)]
        
        c1, c2 = st.columns([1, 2])
        with c1:
            sel_month_str = st.selectbox("📅 Select Month", month_list)
            sel_date = pd.to_datetime(sel_month_str)
        
        # 2. Type Multi-select Filter
        with c2:
            types = sorted(merged['Type'].unique().astype(str))
            sel_types = st.multiselect("🏷️ Filter by Type", types, default=types)

        # Filtering Data
        mask = (merged['TargetDate'].dt.month == sel_date.month) & \
               (merged['TargetDate'].dt.year == sel_date.year) & \
               (merged['Type'].isin(sel_types))
        final_list = merged[mask].copy()

        if not final_list.empty:
            # Applying Clinical Rounding Logic
            final_list['Qty_AMU'] = final_list['AMU'].apply(lambda x: 1.0 if x < 1 else float(math.ceil(x)))
            
            # 3. Dual Cost Metrics
            cost_single = (final_list['Price'] * 1).sum()
            cost_amu = (final_list['Price'] * final_list['Qty_AMU']).sum()
            
            m1, m2 = st.columns(2)
            m1.metric("Cost (1 Piece Each)", f"${cost_single:,.2f}")
            m2.metric("Cost (AMU Rounded)", f"${cost_amu:,.2f}")
            
            st.dataframe(final_list[['Item', 'Type', 'Price', 'AMU', 'Qty_AMU', 'Branch', 'Master']], use_container_width=True)
        else:
            st.info(f"No restock needed for {sel_month_str} with current filters.")
