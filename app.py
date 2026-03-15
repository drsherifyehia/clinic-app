import streamlit as st
import pandas as pd
import numpy as np
import math
import io
from datetime import datetime

# --- PAGE CONFIG ---
st.set_page_config(page_title="Clinic Inventory Suite", layout="wide", page_icon="🦷")

# --- HELPER: EXCEL DOWNLOADER ---
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

# --- INITIALIZE SESSION STATES ---
if 'usage_raw' not in st.session_state: st.session_state.usage_raw = pd.DataFrame()
if 'master_df' not in st.session_state: st.session_state.master_df = None
if 'shared_amu' not in st.session_state: st.session_state.shared_amu = None

st.title("🦷 Clinic Inventory Control Center")

# --- MAIN TAB NAVIGATION ---
main_tab1, main_tab2, main_tab3 = st.tabs(["📂 1. Data Upload Center", "📊 2. AMU Engine", "🛒 3. Smart Shopping List"])

# ---------------------------------------------------------
# TAB 1: DATA UPLOAD CENTER
# ---------------------------------------------------------
with main_tab1:
    st.header("Upload Clinical Data")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Step 1: Usage Records")
        amu_files = st.file_uploader("Upload usage records (Multiple allowed)", accept_multiple_files=True, key="main_amu_up")
        if amu_files:
            try:
                dfs = [pd.read_excel(f, engine='openpyxl') for f in amu_files]
                st.session_state.usage_raw = pd.concat(dfs, ignore_index=True)
                st.success(f"Successfully merged {len(amu_files)} usage files.")
            except Exception as e:
                st.error(f"Error loading usage files: {e}")

    with col2:
        st.subheader("Step 2: Stock Levels (Sheet 2)")
        stock_file = st.file_uploader("Upload Sheet 2 (B,D,F,G)", type=["xlsx"], key="main_stock_up")
        if stock_file:
            try:
                # Optimized reading for Sheet 2
                df_s2 = pd.read_excel(stock_file, usecols="B,D,F,G", engine='openpyxl').dropna(how='all')
                df_s2.columns = ["Item", "Type_S2", "Branch", "Master"]
                st.session_state.stock_df = df_s2
                st.success("Stock levels loaded.")
            except Exception as e:
                st.error(f"Error loading stock file: {e}")

    if not st.session_state.usage_raw.empty or 'stock_df' in st.session_state:
        st.info("💡 Data is loaded. Move to the next tabs to see results.")

# ---------------------------------------------------------
# TAB 2: AMU ENGINE
# ---------------------------------------------------------
with main_tab2:
    if st.session_state.usage_raw.empty:
        st.warning("Please upload usage records in Tab 1.")
    else:
        st.subheader("AMU Calculation & Filtering")
        search_query = st.text_input("Search Item Name:", placeholder="e.g. Articaine", key="amu_search")
        
        # Filtering (Columns C, F, I, K, M)
        cols = [2, 5, 8, 10, 12]
        filtered = st.session_state.usage_raw.iloc[:, cols].copy()
        filtered.columns = ['Amount', 'Price', 'inventoryItem', 'inventoryType', 'Created']
        
        if search_query:
            filtered = filtered[filtered['inventoryItem'].astype(str).str.contains(search_query, case=False, na=False)]
        
        # Consolidation Logic
        filtered['Created'] = pd.to_datetime(filtered['Created'], errors='coerce')
        consolidated = filtered.groupby(['inventoryItem', 'inventoryType']).agg({
            'Amount': 'sum', 'Price': 'max', 'Created': 'min'
        }).reset_index()
        
        today = pd.to_datetime(datetime.now())
        consolidated['No. of Months'] = consolidated['Created'].apply(
            lambda x: max(1, round((today - x).days / 30, 2)) if pd.notnull(x) else 1
        )
        
        # AMU Final Calc
        consolidated['AMU'] = (consolidated['Amount'] / consolidated['No. of Months']).round(2)
        
        # Shared AMU for Tab 3
        df_ready = consolidated[['inventoryItem', 'inventoryType', 'Price', 'AMU']].rename(
            columns={'inventoryItem': 'Item', 'inventoryType': 'Type'}
        )
        st.session_state['shared_amu'] = df_ready
        
        st.dataframe(consolidated, use_container_width=True)
        st.download_button("📥 Download AMU Results", data=to_excel(df_ready), file_name="amu_results.xlsx")

# ---------------------------------------------------------
# TAB 3: SMART SHOPPING LIST
# ---------------------------------------------------------
with main_tab3:
    if st.session_state.shared_amu is None or 'stock_df' not in st.session_state:
        st.warning("Please ensure both Usage Records and Stock Levels are uploaded in Tab 1.")
    else:
        df_amu = st.session_state['shared_amu'].copy()
        df_s2 = st.session_state['stock_df'].copy()
        
        # Matching Logic
        df_amu['MatchKey'] = df_amu['Item'].astype(str).str.strip().str.lower()
        df_s2['MatchKey'] = df_s2['Item'].astype(str).str.strip().str.lower()
        
        merged = pd.merge(df_amu, df_s2.drop(columns=['Item']), on="MatchKey", how="inner")
        
        def calc_month(row):
            try:
                m_val = float(row['Master']) if pd.notnull(row['Master']) else 0
                a_val = float(row['AMU']) if pd.notnull(row['AMU']) else 0
                months = math.ceil(m_val / a_val) if a_val > 0 else 0
                return (datetime.now().date() + pd.DateOffset(months=months)).replace(day=1)
            except: return datetime.now().date().replace(day=1)

        merged['TargetDate'] = pd.to_datetime(merged.apply(calc_month, axis=1))
        
        # Shopping List Controls
        start_month = st.date_input("Start Month", datetime.now().date().replace(day=1))
        start_ts = pd.Timestamp(start_month)
        month_list = [start_ts + pd.DateOffset(months=i) for i in range(3)]
        
        all_types = sorted(merged['Type'].unique().astype(str))
        selected_types = st.multiselect("Filter Material Type:", all_types, default=all_types)

        def style_rows(row):
            branch_val = row.get('Branch', 0)
            if pd.isna(branch_val) or branch_val <= 0:
                return ['background-color: #ff4b4b; color: white'] * len(row)
            return ['background-color: #fffd80; color: black'] * len(row)

        for i, current_month in enumerate(month_list):
            m_str = current_month.strftime("%B %Y")
            mask = (merged['TargetDate'].dt.month == current_month.month) & \
                   (merged['TargetDate'].dt.year == current_month.year) & \
                   (merged['Type'].isin(selected_types))
            
            month_df = merged[mask].copy()
            st.markdown(f"### 📅 {m_str}")
            
            if not month_df.empty:
                # Logic: if AMU < 1 treat as 1, else round up
                month_df['Rounded_AMU'] = month_df['AMU'].apply(lambda x: 1.0 if x < 1 else float(math.ceil(x)))
                total_cost = (month_df['Price'] * month_df['Rounded_AMU']).sum()

                st.metric(f"Total Cost for {m_str}", f"${total_cost:,.2f}")
                st.data_editor(
                    month_df[['Item', 'Type', 'Price', 'AMU', 'Branch', 'Master']].style.apply(style_rows, axis=1),
                    key=f"shop_edit_{i}",
                    use_container_width=True
                )
            else:
                st.write("No items predicted for this month.")
            st.divider()
