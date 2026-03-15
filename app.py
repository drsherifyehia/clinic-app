import streamlit as st
import pandas as pd
import numpy as np
import math
import io
from datetime import datetime

# --- PAGE CONFIG (Must be first) ---
st.set_page_config(page_title="Clinic Inventory Suite", layout="wide", page_icon="🦷")

# --- HELPER: EXCEL DOWNLOADER ---
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

# --- INITIALIZE GLOBAL STATES ---
if 'amu_final' not in st.session_state: st.session_state.amu_final = pd.DataFrame()
if 'master_df' not in st.session_state: st.session_state.master_df = None
if 'shared_amu' not in st.session_state: st.session_state.shared_amu = None

# --- APP NAVIGATION ---
app_mode = st.sidebar.selectbox("Select Application", ["AMU Engine", "Smart Shopping List"])

# ---------------------------------------------------------
# APP 1: AMU ENGINE
# ---------------------------------------------------------
if app_mode == "AMU Engine":
    st.title("🦷 Average Monthly Usage (AMU) Engine")

    if 'usage_raw' not in st.session_state: st.session_state.usage_raw = pd.DataFrame()
    if 'usage_filtered' not in st.session_state: st.session_state.usage_filtered = pd.DataFrame()

    search_query = st.sidebar.text_input("Search Item Name:", placeholder="e.g. Articaine")

    t1, t2, t3, t4 = st.tabs(["1.a Data Upload", "1.b Filtering", "1.c Consolidation", "1.d AMU Calc"])

    with t1:
        st.subheader("1.a Upload Excel Sheets")
        files = st.file_uploader("Upload usage records", accept_multiple_files=True, key="amu_uploader")
        if files:
            dfs = [pd.read_excel(f, engine='openpyxl') for f in files]
            st.session_state.usage_raw = pd.concat(dfs, ignore_index=True)
            st.success(f"Merged {len(files)} files.")
            
            display_df = st.session_state.usage_raw
            if search_query:
                # Assuming Column I (Index 8) is the Item Name
                item_col = display_df.columns[8] 
                display_df = display_df[display_df[item_col].astype(str).str.contains(search_query, case=False, na=False)]
            st.dataframe(display_df)

    with t2:
        st.subheader("1.b Data Filtering (C, F, I, K, M)")
        if not st.session_state.usage_raw.empty:
            cols = [2, 5, 8, 10, 12]
            filtered = st.session_state.usage_raw.iloc[:, cols].copy()
            filtered.columns = ['Amount', 'Price', 'inventoryItem', 'inventoryType', 'Created']
            if search_query:
                filtered = filtered[filtered['inventoryItem'].str.contains(search_query, case=False, na=False)]
            st.session_state.usage_filtered = filtered
            st.dataframe(filtered)

    with t3:
        st.subheader("1.c Consolidation")
        if not st.session_state.usage_filtered.empty:
            df = st.session_state.usage_filtered.copy()
            df['Created'] = pd.to_datetime(df['Created'], errors='coerce')
            consolidated = df.groupby(['inventoryItem', 'inventoryType']).agg({
                'Amount': 'sum', 'Price': 'max', 'Created': 'min'
            }).reset_index()
            
            today = pd.to_datetime(datetime.now())
            consolidated['No. of Months'] = consolidated['Created'].apply(
                lambda x: max(1, round((today - x).days / 30, 2)) if pd.notnull(x) else 1
            )
            st.session_state.amu_final = consolidated
            st.dataframe(consolidated)

    with t4:
        st.subheader("1.d Final AMU Results")
        if not st.session_state.amu_final.empty:
            df = st.session_state.amu_final.copy()
            df['AMU'] = (df['Amount'] / df['No. of Months']).round(2)
            
            # Prepare data for the Shopping List
            df_ready = df[['inventoryItem', 'inventoryType', 'Price', 'AMU']].rename(
                columns={'inventoryItem': 'Item', 'inventoryType': 'Type'}
            )
            st.session_state['shared_amu'] = df_ready
            
            st.dataframe(df_ready)
            st.success("✅ AMU data is now available for the Shopping List!")
            st.download_button("📥 Download AMU Results", data=to_excel(df_ready), file_name="amu_results.xlsx")

# ---------------------------------------------------------
# APP 2: SMART SHOPPING LIST
# ---------------------------------------------------------
else:
    st.title("🛒 Smart Shopping List")
    
    s_tab1, s_tab2, s_tab3, s_tab4 = st.tabs(["1. Upload", "2. Consolidate", "3. Forecast", "4. Interactive Shopping List"])

    with s_tab1:
        col1, col2 = st.columns(2)
        
        # Choice: Use internal data or upload new AMU
        use_internal = col1.checkbox("Use AMU data from Engine", value='shared_amu' in st.session_state)
        
        df_amu = None
        if use_internal and st.session_state['shared_amu'] is not None:
            df_amu = st.session_state['shared_amu']
            col1.info("Using AMU data from the Engine tab.")
        else:
            file_amu = col1.file_uploader("Upload AMU Sheet (A,B,D,G)", type=["xlsx"], key="shop_amu")
            if file_amu:
                df_amu = pd.read_excel(file_amu, engine='openpyxl', usecols="A,B,D,G").dropna(how='all')
                df_amu.columns = ["Item", "Type", "Price", "AMU"]

        file_s2 = col2.file_uploader("Upload Sheet 2 (B,D,F,G)", type=["xlsx"], key="shop_s2")

        if df_amu is not None and file_s2:
            try:
                # Optimized reading to prevent server crash
                df_s2 = pd.read_excel(file_s2, usecols="B,D,F,G", engine='openpyxl').dropna(how='all')
                df_s2.columns = ["Item", "Type_S2", "Branch", "Master"]
                
                # Cleaning keys for better matching
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
                st.session_state['master_df'] = merged
                st.success(f"🔗 Linked {len(merged)} items!")
            except Exception as e:
                st.error(f"Error matching data: {e}")

    with s_tab2:
        if st.session_state['master_df'] is not None:
            st.header("Consolidated View")
            st.dataframe(st.session_state['master_df'][['Item', 'Type', 'Price', 'AMU', 'Branch', 'Master']], use_container_width=True)

    with s_tab3:
        if st.session_state['master_df'] is not None:
            st.header("Depletion Forecast")
            forecast_df = st.session_state['master_df'][['Item', 'Master', 'AMU', 'TargetDate']].copy()
            forecast_df['TargetDate'] = forecast_df['TargetDate'].dt.strftime('%B %Y')
            st.dataframe(forecast_df, use_container_width=True)

    with s_tab4:
        if st.session_state['master_df'] is not None:
            df = st.session_state['master_df']
            start_month = st.date_input("Start Month", datetime.now().date().replace(day=1))
            start_ts = pd.Timestamp(start_month)
            month_list = [start_ts + pd.DateOffset(months=i) for i in range(3)]
            
            st.write("**Filter Material Type:**")
            all_types = sorted(df['Type'].unique().astype(str))
            cols = st.columns(3)
            selected_types = [t for i, t in enumerate(all_types) if cols[i % 3].checkbox(t, value=True, key=f"shop_c_{t}")]

            def style_rows(row):
                branch_val = row.get('Branch', 0)
                if pd.isna(branch_val) or branch_val <= 0:
                    return ['background-color: #ff4b4b; color: white'] * len(row)
                return ['background-color: #fffd80; color: black'] * len(row)

            for i, current_month in enumerate(month_list):
                m_str = current_month.strftime("%B %Y")
                mask = (df['TargetDate'].dt.month == current_month.month) & \
                       (df['TargetDate'].dt.year == current_month.year) & \
                       (df['Type'].isin(selected_types))
                
                month_df = df[mask].copy()
                st.markdown(f"### 📅 {m_str}")
                
                if not month_df.empty:
                    # Logic: if AMU < 1 treat as 1, else round up
                    def round_amu_logic(val):
                        if val < 1: return 1.0
                        return float(math.ceil(val))

                    month_df['Rounded_AMU'] = month_df['AMU'].apply(round_amu_logic)
                    total_amu_cost = (month_df['Price'] * month_df['Rounded_AMU']).sum()

                    st.metric("Estimated Monthly Order Cost", f"${total_amu_cost:,.2f}")

                    st.data_editor(
                        month_df[['Item', 'Type', 'Price', 'AMU', 'Branch', 'Master']].style.apply(style_rows, axis=1),
                        key=f"shop_editor_{i}",
                        use_container_width=True
                    )
                else:
                    st.write("No items predicted for this month.")
                st.divider()
        else:
            st.info("Please provide AMU and Stock data in Tab 1.")
