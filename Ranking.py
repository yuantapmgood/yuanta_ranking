import streamlit as st
import pandas as pd
import re
import os
import io

# --- 頁面與全域變數設定 ---
st.set_page_config(page_title="投信公會券商排名分析系統", layout="wide")

REPORT_PERIOD = "2026/1月-7月"
ADMIN_PASSWORD = "yuanta_admin"

# 抓取目前 Ranking.py 所在的資料夾路徑
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 強制將存檔路徑綁定在跟程式碼同一個資料夾下
mapping_file = os.path.join(BASE_DIR, 'funds_mapping.csv')
latest_data_file = os.path.join(BASE_DIR, 'latest_report.csv')
# 新增：規模與經理人的快取存檔路徑
scale_data_file = os.path.join(BASE_DIR, 'scale_report.csv')
manager_data_file = os.path.join(BASE_DIR, 'manager_report.csv')

# 初始化 Session State
if 'raw_data' not in st.session_state:
    st.session_state.raw_data = None
if 'fund_scale_data' not in st.session_state:
    st.session_state.fund_scale_data = None
if 'fund_manager_data' not in st.session_state:
    st.session_state.fund_manager_data = None

# 啟動時：自動讀取 GitHub / 伺服器上已存在的 CSV 快取檔案
if st.session_state.raw_data is None and os.path.exists(latest_data_file):
    try:
        st.session_state.raw_data = pd.read_csv(latest_data_file)
    except Exception:
        pass

if st.session_state.fund_scale_data is None and os.path.exists(scale_data_file):
    try:
        st.session_state.fund_scale_data = pd.read_csv(scale_data_file)
    except Exception:
        pass

if st.session_state.fund_manager_data is None and os.path.exists(manager_data_file):
    try:
        st.session_state.fund_manager_data = pd.read_csv(manager_data_file)
    except Exception:
        pass

# ====================================================================
# 新版基礎函數定義：精準萃取主基金名稱
# ====================================================================
def get_main_fund_name(name):
    """取得主基金名稱：精準排除警語，並利用『最後一個基金』神邏輯截斷雜訊"""
    clean_name = str(name).strip()
    
    # 1. 專門切除公會的警語括號 (特徵：括號內開頭為「本基金」或「基金之」或「基金有」)
    clean_name = re.sub(r'\s*[\(（](本基金|基金之|基金有).*?[\)）]', '', clean_name).strip()
    
    # 2. 尋找「基金」兩字，直接截斷到「最後一個基金」為止
    if "基金" in clean_name:
        match = re.match(r'^(.*基金)', clean_name)
        if match:
            clean_name = match.group(1).strip()
    else:
        # 3. 處理少數沒有「基金」兩字的純 ETF
        suffixes = r'(?:[A-Za-z]+[類型別]|累積|配息|收益|新臺幣|新台幣|美元|美金|人民幣|日圓|澳幣|南非幣|後收|各級別)'
        clean_name = re.split(rf'-{suffixes}', clean_name)[0].strip()
        clean_name = re.sub(r'-([A-Za-z]+)$', '', clean_name).strip()
        
    return clean_name

def get_base_id(fund_id):
    """提取基金統編的數字主體"""
    if pd.isna(fund_id):
        return None
    match = re.search(r'^(\d+)', str(fund_id).strip())
    if match:
        return match.group(1)
    return str(fund_id).strip()

def robust_read_html(uploaded_file):
    uploaded_file.seek(0)
    raw_bytes = uploaded_file.read()
    
    if raw_bytes.startswith(b'\xef\xbb\xbf'):
        html_str = raw_bytes.decode('utf-8-sig', errors='ignore')
    else:
        try:
            html_str = raw_bytes.decode('utf-8', errors='strict')
        except:
            html_str = raw_bytes.decode('big5', errors='ignore')
            
    virtual_file = io.StringIO(html_str)
    dfs = pd.read_html(virtual_file, flavor='lxml')
    return dfs

@st.cache_data
def process_raw_data(uploaded_file):
    try:
        dfs = robust_read_html(uploaded_file)
        df = dfs[0].iloc[2:].copy()
        df.columns = ["基金名稱", "名次", "券商", "總手續費", "總手續費占比", "交易金額", "股票手續費", "平均手續費率"]
        
        def clean_broker_name(name):
            name = str(name)
            clean_name = re.split(r'\(|（', name)[0].strip()
            
            # 【新增】海外券商防誤殺機制：
            # 如果名稱中包含這些海外地區關鍵字，就直接保留原名，不歸入台灣母公司
            overseas_keywords = r'韓國|Korea|越南|Vietnam|香港|Hong Kong|HK|印尼|Indonesia|泰國|Thailand|新加坡|Singapore|亞洲|Asia'
            if re.search(overseas_keywords, clean_name, re.IGNORECASE):
                return clean_name
            
            # 國內券商歸戶邏輯
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
        
        # 投信名稱智慧萃取
        def extract_amc_name(fund_name):
            name = str(fund_name)
            special_amcs = [
                '中國信託', '第一金', '大華銀', '華南永昌', '富蘭克林華美', 
                '貝萊德', '鋒裕匯理', '路博邁', '施羅德', '保德信', 'PGIM保德信', '台中銀'
            ]
            for amc in special_amcs:
                if name.startswith(amc):
                    return amc + '投信'
            return name[:2] + '投信'
            
        df['投信'] = df['基金名稱'].apply(extract_amc_name)
        df['主基金名稱'] = df['基金名稱'].apply(get_main_fund_name)
        return df
    except Exception as e:
        st.error(f"排名檔案解析失敗。錯誤訊息: {e}")
        return None
        
@st.cache_data
def process_scale_data(uploaded_file):
    try:
        dfs = robust_read_html(uploaded_file)
        df = dfs[0].iloc[1:].copy()
        df.columns = dfs[0].iloc[0].tolist()
        
        df['主基金統編'] = df['基金統編'].apply(get_base_id)
        df['基金規模 (台幣)'] = pd.to_numeric(df['基金規模 (台幣)'], errors='coerce').fillna(0)
        
        grouped = df.groupby('主基金統編').agg({
            '基金名稱': 'first',
            '基金規模 (台幣)': 'sum'
        }).reset_index()
        
        grouped['主基金名稱'] = grouped['基金名稱'].apply(get_main_fund_name)
        return grouped[['主基金名稱', '基金規模 (台幣)']]
    except Exception as e:
        st.error(f"規模檔案解析失敗。錯誤訊息: {e}")
        return None

@st.cache_data
def process_manager_data(uploaded_file):
    try:
        dfs = robust_read_html(uploaded_file)
        df = dfs[0].iloc[2:].copy()
        df.columns = dfs[0].iloc[0].tolist()
        
        df['主基金統編'] = df['基金統編'].apply(get_base_id)
        
        managers = df.dropna(subset=['經理 人姓名']).groupby('主基金統編').agg({
            '基金名稱': 'first',
            '經理 人姓名': 'first'
        }).reset_index()
        
        managers['主基金名稱'] = managers['基金名稱'].apply(get_main_fund_name)
        return managers[['主基金名稱', '經理 人姓名']]
    except Exception as e:
        st.error(f"基本資料檔案解析失敗。錯誤訊息: {e}")
        return None

# --- UI 開始 ---
st.title(f"📊 投信公會券商排名分析系統 ({REPORT_PERIOD})")

# ==========================================
# 側邊欄 (Sidebar) - 基金設定管理
# ==========================================
with st.sidebar:
    st.header("⚙️ 基金複委託設定檢視與管理")
    
    if os.path.exists(mapping_file):
        existing_mapping = pd.read_csv(mapping_file)
        st.write(f"目前資料庫已記錄 **{len(existing_mapping)}** 檔基金。")
        
        st.divider()
        st.write("🔒 **管理員修改區**")
        pwd_input = st.text_input("輸入密碼以解鎖編輯權限：", type="password")
        
        if pwd_input == ADMIN_PASSWORD:
            st.success("✅ 已解鎖！您可以直接在下方表格修改設定。")
            
            edited_mapping = st.data_editor(
                existing_mapping, 
                num_rows="dynamic", 
                key="edit_existing",
                use_container_width=True
            )
            
            if st.button("💾 儲存修改至資料庫", type="primary"):
                edited_mapping.to_csv(mapping_file, index=False, encoding='utf-8-sig')
                st.success("設定已儲存！")
                st.rerun()
                
            st.write("📥 **備份與發布**")
            st.info("若要讓設定永久生效，請點擊下方下載，並手動上傳至 GitHub 覆蓋舊檔。")
            
            csv_data = edited_mapping.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                label="下載 funds_mapping.csv",
                data=csv_data,
                file_name="funds_mapping.csv",
                mime="text/csv",
                type="secondary"
            )                
                
            if st.button("🗑️ 清除所有基金分類紀錄"):
                os.remove(mapping_file)
                st.success("紀錄已清除！")
                st.rerun()
        else:
            if pwd_input != "":
                st.error("密碼錯誤。")
            st.info("目前為唯讀模式。")
            st.dataframe(existing_mapping, use_container_width=True, hide_index=True)
            
    else:
        st.warning("目前尚無基金分類紀錄。")
        pwd_input = st.text_input("輸入密碼以解鎖新基金設定：", type="password")

# ==========================================
# 主畫面邏輯 - 檔案上傳區
# ==========================================
with st.expander("📁 點擊上傳 / 更新公會報表資料", expanded=(st.session_state.raw_data is None)):
    col_upload1, col_upload2, col_upload3 = st.columns(3)
    with col_upload1:
        file_rank = st.file_uploader("1. 排名報表 (必傳)", type=['xls', 'xlsx'], key="f1")
    with col_upload2:
        file_scale = st.file_uploader("2. 規模報表 (選傳)", type=['xls', 'xlsx'], key="f2")
    with col_upload3:
        file_manager = st.file_uploader("3. 基本資料(經理人) (選傳)", type=['xls', 'xlsx'], key="f3")

    if st.button("上傳並解析檔案", type="primary"):
        if file_rank is not None:
            with st.spinner("正在解析排名檔案..."):
                parsed_df = process_raw_data(file_rank)
                if parsed_df is not None:
                    st.session_state.raw_data = parsed_df
                    parsed_df.to_csv(latest_data_file, index=False, encoding='utf-8-sig')
        
        if file_scale is not None:
            with st.spinner("正在解析規模檔案..."):
                parsed_scale = process_scale_data(file_scale)
                if parsed_scale is not None:
                    st.session_state.fund_scale_data = parsed_scale
                    parsed_scale.to_csv(scale_data_file, index=False, encoding='utf-8-sig')
                
        if file_manager is not None:
            with st.spinner("正在解析經理人檔案..."):
                parsed_manager = process_manager_data(file_manager)
                if parsed_manager is not None:
                    st.session_state.fund_manager_data = parsed_manager
                    parsed_manager.to_csv(manager_data_file, index=False, encoding='utf-8-sig')
                
        if file_rank is not None or file_scale is not None or file_manager is not None:
            st.success("✅ 檔案處理完成！")
            st.rerun()

    # --- 供 GitHub 長期備份用的 CSV 下載區 ---
    if st.session_state.raw_data is not None or st.session_state.fund_scale_data is not None:
        st.divider()
        st.write("📥 **下載處理好的快取檔案 (供上傳至 GitHub 以永久保存)**")
        st.caption("將下方檔案上傳至 GitHub 後，同事開啟網頁即可直接看到最新資料，無需重新解析。")
        dl_col1, dl_col2, dl_col3 = st.columns(3)
        
        if st.session_state.raw_data is not None:
            with dl_col1:
                csv_rank = st.session_state.raw_data.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("📥 下載 latest_report.csv", csv_rank, "latest_report.csv", "text/csv")
                
        if st.session_state.fund_scale_data is not None:
            with dl_col2:
                csv_scale = st.session_state.fund_scale_data.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("📥 下載 scale_report.csv", csv_scale, "scale_report.csv", "text/csv")
                
        if st.session_state.fund_manager_data is not None:
            with dl_col3:
                csv_mgr = st.session_state.fund_manager_data.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("📥 下載 manager_report.csv", csv_mgr, "manager_report.csv", "text/csv")

# ==========================================
# 資料處理與呈現區
# ==========================================
if st.session_state.raw_data is not None:
    df = st.session_state.raw_data.copy()
    
    if os.path.exists(mapping_file):
        mapping_df = pd.read_csv(mapping_file)
    else:
        mapping_df = pd.DataFrame(columns=["基金名稱", "是複委託"])
        
    current_funds = pd.DataFrame({'基金名稱': df['基金名稱'].unique()})
    new_funds = current_funds[~current_funds['基金名稱'].isin(mapping_df['基金名稱'])]

    if not new_funds.empty:
        st.warning(f"⚠️ 發現 {len(new_funds)} 檔系統未記錄的新基金！請在左側輸入密碼解鎖後，在下方勾選是否為複委託：")
        new_funds['是複委託'] = False
        
        if pwd_input == ADMIN_PASSWORD:
            edited_new = st.data_editor(new_funds, key="edit_new", use_container_width=True)
            if st.button("➕ 儲存新基金並繼續", type="primary"):
                mapping_df = pd.concat([mapping_df, edited_new], ignore_index=True)
                mapping_df.to_csv(mapping_file, index=False, encoding='utf-8-sig')
                st.success("新基金已儲存！請重新整理以檢視排名。")
                st.rerun()
        else:
            st.dataframe(new_funds, use_container_width=True, hide_index=True)
            st.error("🔒 請先在左側輸入管理員密碼解鎖，才能勾選與儲存新基金設定。")
    else:
        st.divider()
        st.subheader("🏆 複委託業務交易量分析")
        
        merged_df = df.merge(mapping_df, on="基金名稱", how="left")
        sub_broker_df = merged_df[merged_df['是複委託'] == True]

        if not sub_broker_df.empty:
            view_mode = st.radio(
                "請選擇分析視角：", 
                ["券商視角 (觀察特定券商在各投信的市佔)", "投信視角 (觀察特定投信下單給各券商的排名)"], 
                horizontal=True
            )
            st.write("") 
            
            amc_vol = sub_broker_df.groupby(['投信', '券商'])['交易金額'].sum().reset_index()
            col1, col2 = st.columns([1, 2])
            
            # --- 排名主表格顯示邏輯 ---
            if "券商視角" in view_mode:
                with col1:
                    available_brokers = sorted(sub_broker_df['券商'].dropna().astype(str).unique())
                    default_index = available_brokers.index('元大證券') if '元大證券' in available_brokers else 0
                    target_broker = st.selectbox("請選擇要觀察的券商：", available_brokers, index=default_index)
                
                amc_vol['名次'] = amc_vol.groupby('投信')['交易金額'].rank(ascending=False, method='min').astype(int)
                result = amc_vol[amc_vol['券商'] == target_broker].sort_values('交易金額', ascending=False)
                result['交易金額'] = result['交易金額'].apply(lambda x: f"{x:,.0f}")
                
                st.write(f"**{target_broker}** 在各投信複委託交易量的排名整理：")
                st.dataframe(result, use_container_width=True, hide_index=True)
                
                target_funds_raw = sub_broker_df[sub_broker_df['券商'] == target_broker]
                
            else:
                with col1:
                    available_amcs = sorted(sub_broker_df['投信'].dropna().astype(str).unique())
                    target_amc = st.selectbox("請選擇要觀察的投信：", available_amcs)
                
                result = amc_vol[amc_vol['投信'] == target_amc].sort_values('交易金額', ascending=False).reset_index(drop=True)
                result['名次'] = result['交易金額'].rank(ascending=False, method='min').astype(int)
                result = result[['名次', '券商', '交易金額']]
                result['交易金額'] = result['交易金額'].apply(lambda x: f"{x:,.0f}")
                
                st.write(f"**{target_amc}** 投信下單給各券商的複委託交易量排名：")
                st.dataframe(result, use_container_width=True, hide_index=True)
                
                target_funds_raw = sub_broker_df[sub_broker_df['投信'] == target_amc]

            # --- 附加功能：基金明細與規模、經理人 ---
            with st.expander("🔍 點擊查看納入計算之基金明細 (自動載入快取資料)"):
                
                # --- 新增：明細表二次過濾器 ---
                if "券商視角" in view_mode:
                    amc_options = ["顯示全部投信"] + sorted(target_funds_raw['投信'].dropna().astype(str).unique())
                    detail_filter = st.selectbox("🔍 選擇特定投信查看明細：", amc_options)
                    if detail_filter != "顯示全部投信":
                        filtered_raw = target_funds_raw[target_funds_raw['投信'] == detail_filter]
                    else:
                        filtered_raw = target_funds_raw
                else:
                    broker_options = ["顯示全部券商"] + sorted(target_funds_raw['券商'].dropna().astype(str).unique())
                    # 在投信視角，預設幫國金部同仁選好「元大證券」以精準看自家單量
                    default_idx = broker_options.index('元大證券') if '元大證券' in broker_options else 0
                    detail_filter = st.selectbox("🔍 選擇特定券商查看明細 (預設為元大證券)：", broker_options, index=default_idx)
                    if detail_filter != "顯示全部券商":
                        filtered_raw = target_funds_raw[target_funds_raw['券商'] == detail_filter]
                    else:
                        filtered_raw = target_funds_raw

                # 將過濾後的子基金「交易金額」依照投信與主基金名稱進行加總
                funds_list = filtered_raw.groupby(['投信', '主基金名稱'], as_index=False)['交易金額'].sum()
                
                if st.session_state.fund_scale_data is not None:
                    funds_list = funds_list.merge(st.session_state.fund_scale_data, on='主基金名稱', how='left')
                    funds_list['基金規模 (億台幣)'] = (funds_list['基金規模 (台幣)'] / 100000000).fillna(0).round(2)
                    funds_list = funds_list.drop(columns=['基金規模 (台幣)'])
                else:
                    funds_list['基金規模 (億台幣)'] = "未上傳規模資料"
                    
                if st.session_state.fund_manager_data is not None:
                    funds_list = funds_list.merge(st.session_state.fund_manager_data, on='主基金名稱', how='left')
                    funds_list.rename(columns={'經理 人姓名': '基金經理人'}, inplace=True)
                    funds_list['基金經理人'] = funds_list['基金經理人'].fillna("查無資料")
                else:
                    funds_list['基金經理人'] = "未上傳經理人資料"
                
                # 下方表格：依各基金專屬貢獻的「交易金額」降冪排列
                funds_list = funds_list.sort_values(by=['交易金額'], ascending=False)
                
                # 加上千分位逗號，方便閱讀
                funds_list['交易金額'] = funds_list['交易金額'].apply(lambda x: f"{x:,.0f}")
                
                st.dataframe(funds_list, use_container_width=True, hide_index=True)

        else:
            st.info("目前勾選的複委託基金中，沒有找到對應的交易紀錄。請確認設定。")
