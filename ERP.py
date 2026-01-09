import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json # 引入 json 模組來讀取鑰匙

# ==========================================
# 1. Google Sheets 連線設定 (安全版)
# ==========================================
SCOPE = ['https://www.googleapis.com/auth/spreadsheets',
         'https://www.googleapis.com/auth/drive']

def connect_google_sheet():
    """連線到 Google 試算表"""
    try:
        # 從 Streamlit 雲端的「秘密保險箱」讀取鑰匙，而不是寫死在程式碼裡
        # 這裡的 "google_key" 是我們等一下要在網頁上設定的代號
        key_dict = json.loads(st.secrets["google_key"])
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open("Company_Database")
        return sheet

    except Exception as e:
        st.error(f"連線失敗！請檢查 Streamlit Cloud 的 Secrets 設定。\n錯誤訊息: {e}")
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
st.title("☁️ 公司營運中控台 (Web版)")

# 連線
sh = connect_google_sheet()
if not sh:
    st.stop()

ws_trans, ws_projs = init_sheets(sh)

# 以下邏輯不變，讀取資料
try:
    data_trans = ws_trans.get_all_records()
    df_trans = pd.DataFrame(data_trans)
    data_projs = ws_projs.get_all_records()
    df_projs = pd.DataFrame(data_projs)
except:
    df_trans = pd.DataFrame()
    df_projs = pd.DataFrame()

# 資料轉型
if not df_trans.empty:
    df_trans['amount'] = pd.to_numeric(df_trans['amount'], errors='coerce').fillna(0)
    df_trans['date'] = pd.to_datetime(df_trans['date'], errors='coerce')
if not df_projs.empty:
    df_projs['total_budget'] = pd.to_numeric(df_projs['total_budget'], errors='coerce').fillna(0)
    df_projs['progress'] = pd.to_numeric(df_projs['progress'], errors='coerce').fillna(0)

# Dashboard
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

# Tabs
tab1, tab2, tab3 = st.tabs(["🏗 專案進度", "✍️ 雲端記帳", "📋 詳細報表"])

with tab1: # 專案
    c1, c2 = st.columns([1, 2])
    with c1:
        with st.form("add_proj"):
            p_name = st.text_input("專案名稱")
            p_budget = st.number_input("預算", min_value=0)
            p_status = st.selectbox("狀態", ["進行中", "結案", "暫停"])
            p_progress = st.slider("進度", 0, 100, 0)
            if st.form_submit_button("上傳"):
                ws_projs.append_row([p_name, p_budget, str(date.today()), p_status, p_progress, str(datetime.now())])
                st.success("成功")
                st.rerun()
    with c2:
        if not df_projs.empty:
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

with tab2: # 記帳
    p_list = ["公司固定開銷"] + (df_projs['name'].tolist() if not df_projs.empty else [])
    with st.form("add_trans"):
        c1, c2, c3 = st.columns(3)
        t_date = c1.date_input("日期")
        t_type = c2.selectbox("類型", ["支出", "收入"])
        t_cat = c3.selectbox("科目", ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"])
        c4, c5 = st.columns(2)
        t_amt = c4.number_input("金額", min_value=0)
        t_proj = c5.selectbox("歸屬", p_list)
        t_note = st.text_input("備註")
        if st.form_submit_button("寫入"):
            ws_trans.append_row([str(t_date), t_type, t_cat, t_amt, t_note, t_proj, str(datetime.now())])
            st.success("成功")
            st.rerun()

with tab3: # 報表
    if not df_trans.empty:
        st.dataframe(df_trans, use_container_width=True)