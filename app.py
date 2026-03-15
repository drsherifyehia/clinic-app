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
if 'stock_df' not in st.session_state: st.session_state.stock_df = None
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
        amu_files = st.file_uploader("Upload usage records", accept_multiple_files=True, key="main_amu_up")
        if amu_files:
            try:
                dfs = [pd.read_excel(f, engine='openpyxl') for f in amu_files]
                st.session_state.usage_raw = pd.concat(dfs, ignore_index=True)
                st.success(f"✅ {len(amu_files)} usage files merged.")
            except Exception as e:
                st.error(f"Error loading usage files: {e}")

    with col2:
        st.subheader("Step 2: Stock Levels (Sheet 2)")
        stock_file = st.file_uploader("Upload Sheet 2", type=["xlsx"], key="main_stock_up")
        if stock_file:
            try:
                # Load first to check columns
                df_test = pd.read_excel(stock_file, engine='openpyxl')
                if len(df_test.columns) < 7:
                    st.error("❌ Sheet 2 does not have enough columns. Need at least columns up to G.")
                else:
                    # Specifically grab B, D, F, G (Indices 1, 3, 5, 6)
                    df_s2 = df_test.iloc[:, [1, 3, 5, 6]].dropna(how='all')
                    df_s2.columns = ["Item", "Type_S2", "Branch", "Master"]
                    st.session_state.stock_df = df_s2
                    st.success("✅ Stock levels loaded successfully.")
            except Exception as e:
                st.error(f"❌ Error processing Sheet 2: {e}")

# ---------------------------------------------------------
# TAB 2: AMU ENGINE
# ---------------------------------------------------------
with main_tab2:
    if st.session_state.usage_raw.empty:
        st.info("Waiting for usage records in Tab 1...")
    else:
        # Filtering (Columns C, F, I, K, M)
        try:
            cols_idx = [2, 5, 8, 10, 12]
            filtered = st.session_state.usage_raw.iloc[:, cols_idx].copy()
            filtered.columns = ['Amount', 'Price', 'inventoryItem', 'inventoryType', 'Created']
            
            # Clean and process
            filtered['Created'] = pd.to_datetime(filtered['Created'], errors='coerce')
            consolidated = filtered.groupby(['inventoryItem', 'inventoryType']).agg({
                'Amount': 'sum', 'Price': 'max', 'Created': 'min'
            }).reset_index()
            
            today = pd.to_datetime(datetime.now())
            consolidated['No. of Months'] = consolidated['Created'].apply(
                lambda x: max(1, round((today - x).days / 30, 2)) if pd.notnull(x) else 1
            )
            consolidated['AMU'] = (consolidated['Amount'] / consolidated['No. of Months']).round(2)
            
            # Save for Shopping List
            st.session_state.shared_amu = consolidated[['inventoryItem', 'inventoryType', 'Price', 'AMU']].rename(
                columns={'inventoryItem': 'Item', 'inventoryType': 'Type'}
            )
            
            st.dataframe(consolidated, use_container_width=True)
        except Exception as e:
            st.error(f"Processing error in AMU Engine: {e}")

# ---------------------------------------------------------
# TAB 3: SMART SHOPPING LIST
# ---------------------------------------------------------
with main_tab3:
    if st.session_state.shared_amu is None or st.session_state.stock_df is None:
        st.warning("Please upload both files in Tab 1 to see the Shopping List.")
    else:
        try:
            df_amu = st.session_state.shared_amu.copy()
            df_s2 = st.session_state.stock_df.copy()
            
            # Match on lower-case cleaned keys
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
            
            # Controls
            all_types = sorted(merged['Type'].unique().astype(str))
            selected_types = st.multiselect("Filter Material Type:", all_types, default=all_types)

            # Show next 3 months
            start_month = datetime.now().date().replace(day=1)
            for i in range(3):
                current_month = (pd.Timestamp(start_month) + pd.DateOffset(months=i))
                m_str = current_month.strftime("%B %Y")
                
                mask = (merged['TargetDate'].dt.month == current_month.month) & \
                       (merged['TargetDate'].dt.year == current_month.year) & \
                       (merged['Type'].isin(selected_types))
                
                month_df = merged[mask].copy()
                st.markdown(f"### 📅 {m_str}")
                
                if not month_df.empty:
                    month_df['Order_Qty'] = month_df['AMU'].apply(lambda x: 1.0 if x < 1 else float(math.ceil(x)))
                    total_cost = (month_df['Price'] * month_df['Order_Qty']).sum()
                    st.metric("Estimated Order Cost", f"${total_cost:,.2f}")
                    st.dataframe(month_df[['Item', 'Type', 'Price', 'AMU', 'Branch', 'Master']], use_container_width=True)
                else:
                    st.write("No items predicted.")
                st.divider()
        except Exception as e:
            st.error(f"Shopping List Error: {e}")
