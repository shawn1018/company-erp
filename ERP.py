import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# ==========================================
# 1. Google Sheets 連線設定 (安全版)
# ==========================================
SCOPE = ['https://www.googleapis.com/auth/spreadsheets',
         'https://www.googleapis.com/auth/drive']

def connect_google_sheet():
    """連線到 Google 試算表"""
    try:
        # 從 Streamlit Cloud 的 Secrets 讀取鑰匙
        # 如果是在本機執行且沒有設 secrets，請確保有 .streamlit/secrets.toml 或改回用檔案讀取
        if "google_key" in st.secrets:
            key_dict = json.loads(st.secrets["google_key"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
        else:
            st.error("找不到 google_key，請確認 Streamlit Cloud 的 Secrets 設定。")
            st.stop()
            
        client = gspread.authorize(creds)
        sheet = client.open("Company_Database")
        return sheet
    except Exception as e:
        st.error(f"連線失敗！錯誤訊息: {e}")
        return None

def init_sheets(sheet):
    """初始化欄位"""
    try:
        # Transactions 分頁
        try:
            ws_trans = sheet.worksheet("Transactions")
        except:
            ws_trans = sheet.add_worksheet(title="Transactions", rows=1000, cols=10)
            ws_trans.append_row(["date", "type", "category", "amount", "note", "project_name", "created_at"])

        # Projects 分頁
        try:
            ws_projs = sheet.worksheet("Projects")
        except:
            ws_projs = sheet.add_worksheet(title="Projects", rows=100, cols=10)
            ws_projs.append_row(["name", "total_budget", "start_date", "status", "progress", "created_at"])
            
        return ws_trans, ws_projs
    except Exception as e:
        st.error(f"初始化欄位失敗: {e}")
        return None, None

# 設定頁面
st.set_page_config(page_title="雲端公司中控台", layout="wide", page_icon="☁️")
st.title("☁️ 公司營運中控台 (Web完整版)")

# 連線
sh = connect_google_sheet()
if not sh:
    st.stop()

ws_trans, ws_projs = init_sheets(sh)

# 讀取資料 (使用 get_all_values 以便取得列號)
# Transactions
raw_trans = ws_trans.get_all_values()
if len(raw_trans) > 1:
    df_trans = pd.DataFrame(raw_trans[1:], columns=raw_trans[0])
else:
    df_trans = pd.DataFrame(columns=["date", "type", "category", "amount", "note", "project_name", "created_at"])

# Projects
raw_projs = ws_projs.get_all_values()
if len(raw_projs) > 1:
    df_projs = pd.DataFrame(raw_projs[1:], columns=raw_projs[0])
else:
    df_projs = pd.DataFrame(columns=["name", "total_budget", "start_date", "status", "progress", "created_at"])

# 資料轉型
if not df_trans.empty:
    df_trans['amount'] = pd.to_numeric(df_trans['amount'], errors='coerce').fillna(0)
    df_trans['date'] = pd.to_datetime(df_trans['date'], errors='coerce')
if not df_projs.empty:
    df_projs['total_budget'] = pd.to_numeric(df_projs['total_budget'], errors='coerce').fillna(0)
    df_projs['progress'] = pd.to_numeric(df_projs['progress'], errors='coerce').fillna(0)

# ==========================================
# 2. 戰情儀表板
# ==========================================
today = datetime.today()
if not df_trans.empty:
    mask_month = (df_trans['date'].dt.year == today.year) & (df_trans['date'].dt.month == today.month)
    df_month = df_trans[mask_month]
    m_income = df_month[df_month['type'] == '收入']['amount'].sum()
    m_expense = df_month[df_month['type'] == '支出']['amount'].sum()
    m_balance = m_income - m_expense
    total_balance = df_trans[df_trans['type'] == '收入']['amount'].sum() - df_trans[df_trans['type'] == '支出']['amount'].sum()
else:
    m_income = m_expense = m_balance = total_balance = 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("📅 本月營收", f"${m_income:,.0f}")
col2.metric("💸 本月總開銷", f"${m_expense:,.0f}")
col3.metric("💰 本月淨利", f"${m_balance:,.0f}")
col4.metric("🏦 資金水位", f"${total_balance:,.0f}")
st.divider()

# ==========================================
# 3. 功能分頁
# ==========================================
tab1, tab2, tab3 = st.tabs(["🏗 專案管理 (含修改)", "✍️ 雲端記帳", "📋 報表修改與刪除"])

# --- Tab 1: 專案管理 ---
with tab1: 
    c1, c2 = st.columns([1, 2])
    
    # 新增專案
    with c1:
        st.subheader("新增專案")
        with st.form("add_proj"):
            p_name = st.text_input("專案名稱")
            p_budget = st.number_input("預算", min_value=0)
            p_status = st.selectbox("狀態", ["進行中", "結案", "暫停"])
            p_progress = st.slider("進度", 0, 100, 0)
            if st.form_submit_button("上傳"):
                ws_projs.append_row([p_name, p_budget, str(date.today()), p_status, p_progress, str(datetime.now())])
                st.success("成功")
                st.rerun()

    # 修改/列表專案
    with c2:
        st.subheader("專案列表與管理")
        if not df_projs.empty:
            # 顯示列表
            proj_view = []
            for i, row in df_projs.iterrows():
                p_cost = 0
                p_rev = 0
                if not df_trans.empty and 'project_name' in df_trans.columns:
                    p_trans = df_trans[df_trans['project_name'] == row['name']]
                    p_cost = p_trans[p_trans['type'] == '支出']['amount'].sum()
                    p_rev = p_trans[p_trans['type'] == '收入']['amount'].sum()
                proj_view.append({"專案": row['name'], "狀態": row['status'], "進度": f"{row['progress']}%", "獲利": p_rev - p_cost})
            st.dataframe(pd.DataFrame(proj_view), use_container_width=True)
            
            st.divider()
            st.write("🛠 **修改或刪除專案**")
            
            # 製作選單：顯示 (行號: 專案名)
            # raw_projs[0] 是標題，所以資料從 index 1 開始，對應 Google Sheet 的 Row 2
            proj_options = {}
            for idx, row in enumerate(raw_projs):
                if idx == 0: continue # 跳過標題
                label = f"Row {idx+1}: {row[0]} (狀態: {row[3]})"
                proj_options[label] = idx + 1 # 儲存真實的 Row Number

            sel_proj_label = st.selectbox("選擇要操作的專案", list(proj_options.keys()))
            
            if sel_proj_label:
                row_num = proj_options[sel_proj_label]
                # 取得當前資料
                curr_data = raw_projs[row_num - 1] # List index = Row - 1
                
                with st.form("edit_proj"):
                    e_status = st.selectbox("更新狀態", ["進行中", "結案", "暫停"], index=["進行中", "結案", "暫停"].index(curr_data[3]) if curr_data[3] in ["進行中", "結案", "暫停"] else 0)
                    e_progress = st.slider("更新進度", 0, 100, int(float(curr_data[4])))
                    
                    c_edit, c_del = st.columns(2)
                    if c_edit.form_submit_button("💾 更新狀態"):
                        # 更新 Google Sheet (只更新狀態和進度欄位 D 和 E)
                        ws_projs.update_cell(row_num, 4, e_status) # Col 4 = status
                        ws_projs.update_cell(row_num, 5, e_progress) # Col 5 = progress
                        st.success("更新成功！")
                        st.rerun()
                    
                    if c_del.form_submit_button("🗑 刪除此專案", type="primary"):
                        ws_projs.delete_rows(row_num)
                        st.warning("專案已刪除")
                        st.rerun()

# --- Tab 2: 記帳 ---
with tab2:
    p_list = ["公司固定開銷"] + (df_projs['name'].tolist() if not df_projs.empty else [])
    
    st.info("在此輸入收支，資料直接存入雲端。")
    with st.form("add_trans"):
        c1, c2, c3 = st.columns(3)
        t_date = c1.date_input("日期")
        t_type = c2.selectbox("類型", ["支出", "收入"])
        t_cat = c3.selectbox("科目", ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"])
        c4, c5 = st.columns(2)
        t_amt = c4.number_input("金額", min_value=0)
        t_proj = c5.selectbox("歸屬", p_list)
        t_note = st.text_input("備註")
        if st.form_submit_button("寫入雲端"):
            ws_trans.append_row([str(t_date), t_type, t_cat, t_amt, t_note, t_proj, str(datetime.now())])
            st.success("成功")
            st.rerun()

# --- Tab 3: 報表修改與刪除 ---
with tab3:
    st.subheader("📋 帳務明細 (含修改功能)")
    
    if len(raw_trans) > 1:
        # 顯示完整表格
        st.dataframe(df_trans, use_container_width=True)
        
        st.divider()
        st.subheader("🛠 修改或刪除帳務")
        
        # 製作選單：(Row: 日期 | 金額 | 備註)
        trans_options = {}
        # 這裡我們倒序顯示 (最新的在最上面)
        for idx in range(len(raw_trans)-1, 0, -1):
            row = raw_trans[idx]
            label = f"Row {idx+1}: {row[0]} | ${row[3]} | {row[2]} | {row[4]}"
            trans_options[label] = idx + 1
            
        sel_trans_label = st.selectbox("選擇要修改的紀錄", list(trans_options.keys()))
        
        if sel_trans_label:
            r_num = trans_options[sel_trans_label]
            curr_row = raw_trans[r_num - 1]
            
            with st.form("edit_trans"):
                st.write(f"正在編輯第 {r_num} 列的資料")
                # 日期處理
                try:
                    default_date = datetime.strptime(curr_row[0], "%Y-%m-%d").date()
                except:
                    default_date = date.today()
                
                ec1, ec2, ec3 = st.columns(3)
                new_date = ec1.date_input("日期", default_date)
                new_cat = ec2.selectbox("科目", ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"], index=["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"].index(curr_row[2]) if curr_row[2] in ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"] else 0)
                new_amt = ec3.number_input("金額", min_value=0.0, value=float(curr_row[3]) if curr_row[3] else 0.0)
                new_note = st.text_input("備註", value=curr_row[4])
                
                b1, b2 = st.columns(2)
                if b1.form_submit_button("💾 確認修改"):
                    # 組合要更新的資料 (Col 1 to 5)
                    # Google Sheet update 使用 range, e.g. "A2:E2"
                    update_range = f"A{r_num}:E{r_num}" 
                    # 注意：我們不改 project_name (Col 6) 和 timestamp (Col 7) 以免亂掉，或者您可以自行加入
                    ws_trans.update(range_name=update_range, values=[[str(new_date), curr_row[1], new_cat, new_amt, new_note]])
                    st.success("修改成功！")
                    st.rerun()
                    
                if b2.form_submit_button("🗑 刪除此紀錄", type="primary"):
                    ws_trans.delete_rows(r_num)
                    st.warning("已刪除")
                    st.rerun()
    else:
        st.info("目前沒有資料")
