import streamlit as st
import pandas as pd
import numpy as np
import math
import io
from datetime import datetime

# --- PAGE CONFIG ---
st.set_page_config(page_title="Clinic Inventory Suite", layout="wide", page_icon="🦷")

# --- CACHED FUNCTIONS (Prevents server timeouts) ---
@st.cache_data
def process_usage_files(uploaded_files):
    if not uploaded_files:
        return pd.DataFrame()
    dfs = []
    for f in uploaded_files:
        # Only read the columns we actually need to save memory
        df = pd.read_excel(f, engine='openpyxl')
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)

@st.cache_data
def process_stock_file(uploaded_file):
    if not uploaded_file:
        return None
    df = pd.read_excel(uploaded_file, engine='openpyxl')
    if len(df.columns) < 7:
        return "ERROR_COLS"
    # Select B, D, F, G
    df_s2 = df.iloc[:, [1, 3, 5, 6]].dropna(how='all')
    df_s2.columns = ["Item", "Type_S2", "Branch", "Master"]
    return df_s2

# --- INITIALIZE SESSION STATES ---
if 'usage_raw' not in st.session_state: st.session_state.usage_raw = pd.DataFrame()
if 'stock_df' not in st.session_state: st.session_state.stock_df = None
if 'shared_amu' not in st.session_state: st.session_state.shared_amu = None

st.title("🦷 Clinic Inventory Control Center")

# --- MAIN TAB NAVIGATION ---
main_tab1, main_tab2, main_tab3 = st.tabs(["📂 1. Data Upload", "📊 2. AMU Engine", "🛒 3. Smart Shopping List"])

# ---------------------------------------------------------
# TAB 1: DATA UPLOAD CENTER
# ---------------------------------------------------------
with main_tab1:
    st.header("Upload Clinical Data")
    
    with st.container():
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("1. Usage Records (AMU)")
            amu_files = st.file_uploader("Select one or more files", accept_multiple_files=True, key="amu_up")
        
        with col2:
            st.subheader("2. Stock Levels (Sheet 2)")
            stock_file = st.file_uploader("Select stock level file", type=["xlsx"], key="stock_up")

    st.divider()
    
    # THE FIX: Only process when this button is clicked
    if st.button("🚀 Process and Link All Data", use_container_width=True):
        if amu_files:
            with st.spinner("Processing Usage Records..."):
                st.session_state.usage_raw = process_usage_files(amu_files)
                st.success("✅ Usage Records Loaded.")
        
        if stock_file:
            with st.spinner("Processing Stock Levels..."):
                result = process_stock_file(stock_file)
                if isinstance(result, str) and result == "ERROR_COLS":
                    st.error("❌ Sheet 2 error: Missing columns. Ensure it has data up to Column G.")
                else:
                    st.session_state.stock_df = result
                    st.success("✅ Stock Levels Loaded.")

# ---------------------------------------------------------
# TAB 2: AMU ENGINE
# ---------------------------------------------------------
with main_tab2:
    if st.session_state.usage_raw.empty:
        st.info("Upload and 'Process' data in Tab 1 first.")
    else:
        try:
            # Columns C, F, I, K, M (Indices 2, 5, 8, 10, 12)
            cols_idx = [2, 5, 8, 10, 12]
            df_raw = st.session_state.usage_raw
            
            filtered = df_raw.iloc[:, cols_idx].copy()
            filtered.columns = ['Amount', 'Price', 'inventoryItem', 'inventoryType', 'Created']
            filtered['Created'] = pd.to_datetime(filtered['Created'], errors='coerce')
            
            consolidated = filtered.groupby(['inventoryItem', 'inventoryType']).agg({
                'Amount': 'sum', 'Price': 'max', 'Created': 'min'
            }).reset_index()
            
            today = pd.to_datetime(datetime.now())
            consolidated['No. of Months'] = consolidated['Created'].apply(
                lambda x: max(1, round((today - x).days / 30, 2)) if pd.notnull(x) else 1
            )
            consolidated['AMU'] = (consolidated['Amount'] / consolidated['No. of Months']).round(2)
            
            st.session_state.shared_amu = consolidated[['inventoryItem', 'inventoryType', 'Price', 'AMU']].rename(
                columns={'inventoryItem': 'Item', 'inventoryType': 'Type'}
            )
            
            st.subheader("Consolidated Usage (AMU)")
            st.dataframe(consolidated, use_container_width=True)
        except Exception as e:
            st.error(f"AMU calculation error: {e}")

# ---------------------------------------------------------
# TAB 3: SMART SHOPPING LIST
# ---------------------------------------------------------
with main_tab3:
    if st.session_state.shared_amu is None or st.session_state.stock_df is None:
        st.warning("Ensure both data types are uploaded and processed in Tab 1.")
    else:
        try:
            df_amu = st.session_state.shared_amu.copy()
            df_s2 = st.session_state.stock_df.copy()
            
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
            
            # Month Selection
            start_month = datetime.now().date().replace(day=1)
            for i in range(3):
                current_month = (pd.Timestamp(start_month) + pd.DateOffset(months=i))
                m_str = current_month.strftime("%B %Y")
                
                mask = (merged['TargetDate'].dt.month == current_month.month) & \
                       (merged['TargetDate'].dt.year == current_month.year)
                
                month_df = merged[mask].copy()
                st.markdown(f"### 📅 {m_str}")
                
                if not month_df.empty:
                    # AMU Logic: <1 = 1, >=1 = Round Up
                    month_df['Order_Qty'] = month_df['AMU'].apply(lambda x: 1.0 if x < 1 else float(math.ceil(x)))
                    total_cost = (month_df['Price'] * month_df['Order_Qty']).sum()
                    st.metric("Estimated Cost", f"${total_cost:,.2f}")
                    st.dataframe(month_df[['Item', 'Type', 'Price', 'AMU', 'Branch', 'Master']], use_container_width=True)
                else:
                    st.write("No items predicted for this month.")
                st.divider()
        except Exception as e:
            st.error(f"Shopping List calculation error: {e}")
