import streamlit as st
import pandas as pd
import re
import os

# --- 頁面設定 ---
st.set_page_config(page_title="投信公會券商排名分析系統", layout="wide")

# --- 參數與實體檔案路徑 ---
mapping_file = 'funds_mapping.csv'
latest_data_file = 'latest_report.csv' # 新增：用來儲存最新上傳的報表資料

# --- 初始化 Session State ---
if 'raw_data' not in st.session_state:
    st.session_state.raw_data = None

# 如果伺服器上已經有人上傳過並存檔，就自動載入給所有連線進來的人看
if st.session_state.raw_data is None and os.path.exists(latest_data_file):
    try:
        st.session_state.raw_data = pd.read_csv(latest_data_file)
    except Exception as e:
        st.error("讀取伺服器暫存報表失敗，請重新上傳。")

# --- 資料清理與名稱整合函數 ---
@st.cache_data
def process_raw_data(uploaded_file):
    try:
        dfs = pd.read_html(uploaded_file)
        df = dfs[0].iloc[2:].copy()
        df.columns = ["基金名稱", "名次", "券商", "總手續費", "總手續費占比", "交易金額", "股票手續費", "平均手續費率"]
        
        def clean_broker_name(name):
            name = str(name)
            clean_name = re.split(r'\(|（', name)[0].strip()
            
            if re.search(r'元大|yuanta', clean_name, re.IGNORECASE):
                return '元大證券'
            elif re.search(r'凱基|kgi', clean_name, re.IGNORECASE):
                return '凱基證券'
            elif re.search(r'台新', clean_name, re.IGNORECASE):
                return '台新證券'
            elif re.search(r'中信|中國信託|ctbc', clean_name, re.IGNORECASE):
                return '中信證券'
            elif re.search(r'永豐|sinopac', clean_name, re.IGNORECASE):
                return '永豐金證券'
            elif re.search(r'群益|capital', clean_name, re.IGNORECASE):
                return '群益金鼎證券'
            elif re.search(r'富邦|fubon', clean_name, re.IGNORECASE):
                return '富邦證券'
            
            return clean_name
            
        df['券商'] = df['券商'].apply(clean_broker_name)
        df['交易金額'] = pd.to_numeric(df['交易金額'], errors='coerce').fillna(0)
        df['投信'] = df['基金名稱'].str[:2]
        return df
    except Exception as e:
        st.error(f"檔案解析失敗，請確認格式。錯誤訊息: {e}")
        return None

# --- UI 開始 ---
st.title("📊 投信公會券商排名分析系統")

# ==========================================
# 側邊欄 (Sidebar) - 基金設定管理
# ==========================================
with st.sidebar:
    st.header("⚙️ 基金複委託設定管理")
    
    if os.path.exists(mapping_file):
        existing_mapping = pd.read_csv(mapping_file)
        st.write(f"目前資料庫已記錄 **{len(existing_mapping)}** 檔基金。")
        
        edited_mapping = st.data_editor(
            existing_mapping, 
            num_rows="dynamic", 
            key="edit_existing",
            use_container_width=True
        )
        
        if st.button("💾 儲存修改至資料庫", type="primary"):
            edited_mapping.to_csv(mapping_file, index=False)
            st.success("設定已儲存！")
            st.rerun()
            
        st.divider()
        if st.button("🗑️ 清除所有基金分類紀錄"):
            os.remove(mapping_file)
            st.success("紀錄已清除！")
            st.rerun()
    else:
        st.warning("目前尚無基金分類紀錄。上傳檔案後若有新基金，系統會請您設定。")

# ==========================================
# 主畫面邏輯 
# ==========================================
# 1. 檔案上傳區
uploaded_file = st.file_uploader("請上傳當月投信公會 Excel 檔 (會覆蓋伺服器舊資料)", type=['xls', 'xlsx'])

if uploaded_file is not None:
    if 'last_uploaded' not in st.session_state or st.session_state.last_uploaded != uploaded_file.name:
        with st.spinner("正在解析檔案中..."):
            parsed_df = process_raw_data(uploaded_file)
            if parsed_df is not None:
                st.session_state.raw_data = parsed_df
                st.session_state.last_uploaded = uploaded_file.name
                
                # 新增：將解析後的資料存成實體檔案，分享給其他連線進來的人
                parsed_df.to_csv(latest_data_file, index=False)
                st.success("✅ 報表已成功上傳並更新至伺服器，其他同事重新整理網頁即可看見最新數據！")

# 2. 資料處理與呈現
if st.session_state.raw_data is not None:
    df = st.session_state.raw_data.copy()
    
    if os.path.exists(mapping_file):
        mapping_df = pd.read_csv(mapping_file)
    else:
        mapping_df = pd.DataFrame(columns=["基金名稱", "是複委託"])
        
    current_funds = pd.DataFrame({'基金名稱': df['基金名稱'].unique()})
    new_funds = current_funds[~current_funds['基金名稱'].isin(mapping_df['基金名稱'])]

    if not new_funds.empty:
        st.warning(f"⚠️ 發現 {len(new_funds)} 檔系統未記錄的新基金！請在下方勾選是否為複委託：")
        new_funds['是複委託'] = False
        edited_new = st.data_editor(new_funds, key="edit_new", use_container_width=True)
        
        if st.button("➕ 儲存新基金並繼續"):
            mapping_df = pd.concat([mapping_df, edited_new], ignore_index=True)
            mapping_df.to_csv(mapping_file, index=False)
            st.success("新基金已儲存！請重新整理以檢視排名。")
            st.rerun()
    else:
        # --- 計算排名 ---
        st.divider()
        st.subheader("🏆 複委託業務券商排名")
        
        merged_df = df.merge(mapping_df, on="基金名稱", how="left")
        sub_broker_df = merged_df[merged_df['是複委託'] == True]

        if not sub_broker_df.empty:
            col1, col2 = st.columns([1, 2])
            
            with col1:
                available_brokers = sorted(sub_broker_df['券商'].unique())
                default_index = available_brokers.index('元大證券') if '元大證券' in available_brokers else 0
                target_broker = st.selectbox("請選擇要觀察的券商：", available_brokers, index=default_index)
            
            amc_vol = sub_broker_df.groupby(['投信', '券商'])['交易金額'].sum().reset_index()
            amc_vol['名次'] = amc_vol.groupby('投信')['交易金額'].rank(ascending=False, method='min').astype(int)
            result = amc_vol[amc_vol['券商'] == target_broker].sort_values('交易金額', ascending=False)
            result['交易金額'] = result['交易金額'].apply(lambda x: f"{x:,.0f}")
            
            st.write(f"**{target_broker}** 在各投信複委託交易量的排名整理：")
            st.dataframe(result, use_container_width=True, hide_index=True)
        else:
            st.info("目前勾選的複委託基金中，沒有找到對應的交易紀錄。請確認左側設定。")
