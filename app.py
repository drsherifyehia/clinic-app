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
        # Extract Item (B), Type (D), Branch (F), Master (G)
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

# --- 4 MAIN TABS (RENAME UPDATES) ---
tab_upload, tab_app1, tab_app2, tab_shop = st.tabs([
    "📂 1. Upload", 
    "📊 2. Average Monthly Usage", 
    "⚙️ 3. Inventory Forecast", 
    "🛒 4. Shopping List"
])

# ---------------------------------------------------------
# TAB 1: UPLOAD
# ---------------------------------------------------------
with tab_upload:
    st.header("Data Upload Center")
    col1, col2 = st.columns(2)
    with col1:
        # Renamed to Usage Transactions
        amu_files = st.file_uploader("Upload Usage Transactions", accept_multiple_files=True, key="up_amu")
    with col2:
        # Renamed to Upload Inventory
        stock_f = st.file_uploader("Upload Inventory", type=["xlsx"], key="up_stock")

    if st.button("🚀 Process & Sync All Data", use_container_width=True):
        if amu_files:
            st.session_state.usage_raw = get_amu_data(amu_files)
            st.success("✅ Usage records synced.")
        if stock_f:
            res = get_stock_data(stock_f)
            if isinstance(res, str):
                if res == "ERR_COLS": st.error("❌ Inventory file is missing required columns (B, D, F, G).")
                else: st.error(f"❌ File Error: {res}")
            else:
                st.session_state.stock_df = res
                st.success("✅ Inventory records synced.")

# ---------------------------------------------------------
# TAB 2: AVERAGE MONTHLY USAGE
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
            st.session_state.cons_view = cons
            st.dataframe(cons, use_container_width=True)
        with sub1_final:
            df_final = st.session_state.cons_view.copy()
            df_final['AMU'] = (df_final['Amount'] / df_final['No. of Months']).round(2)
            st.session_state.shared_amu = df_final[['Item', 'Type', 'Price', 'AMU']]
            st.dataframe(df_final, use_container_width=True)

# ---------------------------------------------------------
# TAB 3: INVENTORY FORECAST
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
# TAB 4: SHOPPING LIST (Rolling 3-Month View)
# ---------------------------------------------------------
with tab_shop:
    if st.session_state.merged_data is None:
        st.warning("⚠️ Complete Data Matching in Tab 3 first.")
    else:
        st.header("Interactive Shopping List")
        merged = st.session_state.merged_data
        
        start_m_base = datetime.now().date().replace(day=1)
        month_options = [(start_m_base + pd.DateOffset(months=i)).strftime("%B %Y") for i in range(12)]
        
        c1, c2 = st.columns([1, 2])
        with c1:
            sel_month_str = st.selectbox("📅 Select Month", month_options)
            sel_date = pd.to_datetime(sel_month_str)
        with c2:
            types = sorted(merged['Type'].unique().astype(str))
            sel_types = st.multiselect("🏷️ Filter by Type", types, default=types)

        st.divider()

        # THE 3-MONTH VERTICAL LOOP
        for i in range(3):
            current_target = sel_date + pd.DateOffset(months=i)
            target_label = current_target.strftime("%B %Y")
            
            mask = (merged['TargetDate'].dt.month == current_target.month) & \
                   (merged['TargetDate'].dt.year == current_target.year) & \
                   (merged['Type'].isin(sel_types))
            
            m_df = merged[mask].copy()

            st.subheader(f"🗓️ Shopping List: {target_label}")
            
            if not m_df.empty:
                # Rule: < 1 buy 1, others round up
                m_df['Qty_AMU'] = m_df['AMU'].apply(lambda x: 1.0 if x < 1 else float(math.ceil(x)))
                
                # Financials
                cost_single = (m_df['Price'] * 1).sum()
                cost_amu = (m_df['Price'] * m_df['Qty_AMU']).sum()

                col_met1, col_met2 = st.columns(2)
                col_met1.metric("Cost (1 Piece Each)", f"${cost_single:,.2f}")
                col_met2.metric("Cost (AMU Rounded)", f"${cost_amu:,.2f}")
                
                st.dataframe(m_df[['Item', 'Type', 'Price', 'AMU', 'Qty_AMU', 'Branch', 'Master']], use_container_width=True)
            else:
                st.info(f"No restock needed for {target_label} with current filters.")
            
            st.write("---")
