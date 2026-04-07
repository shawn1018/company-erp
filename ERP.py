import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import time

# ==========================================
# 1. 系統設定與連線 (含快取)
# ==========================================
SCOPE = ['https://www.googleapis.com/auth/spreadsheets',
         'https://www.googleapis.com/auth/drive']

@st.cache_resource
def connect_google_sheet():
    try:
        if "google_key" in st.secrets:
            key_dict = json.loads(st.secrets["google_key"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, SCOPE)
        else:
            st.error("找不到 google_key，請確認 Secrets 設定。")
            st.stop()
        client = gspread.authorize(creds)
        return client.open("Company_Database")
    except Exception as e:
        st.error(f"連線失敗: {e}")
        return None

sh = connect_google_sheet()
if not sh: st.stop()

def init_sheets(sheet):
    try:
        try: ws_trans = sheet.worksheet("Transactions")
        except:
            ws_trans = sheet.add_worksheet(title="Transactions", rows=1000, cols=10)
            ws_trans.append_row(["date", "type", "category", "amount", "note", "project_name", "created_at"])
        try: ws_projs = sheet.worksheet("Projects")
        except:
            ws_projs = sheet.add_worksheet(title="Projects", rows=100, cols=10)
            ws_projs.append_row(["name", "total_budget", "start_date", "status", "progress", "created_at", "end_date", "mid_date"])
        try: ws_settings = sheet.worksheet("Settings")
        except:
            ws_settings = sheet.add_worksheet(title="Settings", rows=100, cols=5)
            ws_settings.append_row(["category_list", "attribution_list"])
            for i, cat in enumerate(["專案款", "薪資", "房租", "外包", "雜支"]): ws_settings.update_cell(i+2, 1, cat)
            ws_settings.update_cell(2, 2, "公司固定開銷")
        return ws_trans, ws_projs, ws_settings
    except: return None, None, None

ws_trans, ws_projs, ws_settings = init_sheets(sh)

@st.cache_data(ttl=60)
def load_data(_ws_trans, _ws_projs, _ws_settings):
    raw_t = _ws_trans.get_all_values()
    df_t = pd.DataFrame(raw_t[1:], columns=raw_t[0]) if len(raw_t) > 1 else pd.DataFrame(columns=["date", "type", "category", "amount", "note", "project_name", "created_at"])
    df_t['_sheet_row'] = range(2, len(df_t) + 2)
    raw_p = _ws_projs.get_all_values()
    std_p_cols = ["name", "total_budget", "start_date", "status", "progress", "created_at", "end_date", "mid_date"]
    if len(raw_p) > 1:
        clean_p = [ (r + [""]*8)[:8] for r in raw_p[1:] ]
        df_p = pd.DataFrame(clean_p, columns=std_p_cols)
        df_p['_sheet_row'] = range(2, len(df_p) + 2)
    else:
        df_p = pd.DataFrame(columns=std_p_cols + ["_sheet_row"])
    raw_s = _ws_settings.get_all_values()
    c_list = [r[0] for r in raw_s[1:] if len(r)>0 and r[0].strip()!=""]
    a_list = [r[1] for r in raw_s[1:] if len(r)>1 and r[1].strip()!=""]
    return df_t, df_p, c_list, a_list

df_trans, df_projs, cat_list, attr_list = load_data(ws_trans, ws_projs, ws_settings)
project_options = (attr_list if attr_list else ["公司固定開銷"]) + (df_projs['name'].tolist() if not df_projs.empty else [])

# 格式轉換
if not df_trans.empty:
    df_trans['amount'] = pd.to_numeric(df_trans['amount'], errors='coerce').fillna(0)
    df_trans['date'] = pd.to_datetime(df_trans['date'], errors='coerce')
if not df_projs.empty:
    df_projs['total_budget'] = pd.to_numeric(df_projs['total_budget'], errors='coerce').fillna(0)
    df_projs['progress'] = pd.to_numeric(df_projs['progress'], errors='coerce').fillna(0)
    df_projs['start_date'] = pd.to_datetime(df_projs['start_date'], errors='coerce')
    df_projs['end_date'] = pd.to_datetime(df_projs['end_date'], errors='coerce')
    df_projs['mid_date'] = pd.to_datetime(df_projs['mid_date'], errors='coerce')
    df_projs['created_at'] = pd.to_datetime(df_projs['created_at'], errors='coerce')
    status_map = {"進行中": "🟢 進行中", "待尾款": "🔴 待尾款", "結案": "🔘 結案", "暫停": "🟠 暫停"}
    df_projs['status'] = df_projs['status'].apply(lambda x: status_map.get(x, x))

def fmt_num(num):
    if num is None: return "$0"
    abs_n = abs(num)
    if abs_n >= 1_000_000: return f"${num/1_000_000:.1f}M"
    elif abs_n >= 1_000: return f"${num/1_000:.1f}K"
    else: return f"${num:,.0f}"

# ==========================================
# 2. 戰情儀表板 (KPI & 圖表)
# ==========================================
st.set_page_config(page_title="雲端公司中控台", layout="wide", page_icon="🚥")
st.title("☁️ 公司營運中控台 (V44 究極版)")

today = datetime.today()
m_income = m_expense = m_balance = total_balance = 0
if not df_trans.empty:
    m_mask = (df_trans['date'].dt.year == today.year) & (df_trans['date'].dt.month == today.month)
    m_income = df_trans[m_mask & (df_trans['type'] == '收入')]['amount'].sum()
    m_expense = df_trans[m_mask & (df_trans['type'] == '支出')]['amount'].sum()
    m_balance = m_income - m_expense
    total_balance = df_trans[df_trans['type'] == '收入']['amount'].sum() - df_trans[df_trans['type'] == '支出']['amount'].sum()

# 營業額與實收
if not df_projs.empty:
    total_budget_sum = df_projs['total_budget'].sum()
    costs = df_trans[df_trans['type']=='支出'].groupby('project_name')['amount'].sum() if not df_trans.empty else pd.Series()
    total_real_income_sum = ((df_projs['total_budget'] * 0.95) - df_projs['name'].map(costs).fillna(0)).sum()
else: total_budget_sum = total_real_income_sum = 0

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("📅 本月營收", fmt_num(m_income))
col2.metric("💸 本月開銷", fmt_num(m_expense))
col3.metric("💰 本月淨利", fmt_num(m_balance))
col4.metric("🏦 總資金水位", fmt_num(total_balance))
col5.metric("🏆 年度營業額 / 實收", f"{fmt_num(total_budget_sum)} / {fmt_num(total_real_income_sum)}")
st.divider()

# 全景圖
if not df_trans.empty or not df_projs.empty:
    df_chart_p = df_projs.copy()
    def prep_dates(row):
        s, e, m = row['start_date'], row['end_date'], row['mid_date']
        if pd.isnull(s): s = datetime.today()
        if pd.isnull(e): e = s + timedelta(days=30)
        if s == e: e = s + timedelta(days=1)
        return s, e, m
    if not df_chart_p.empty: df_chart_p[['start_date', 'end_date', 'mid_date']] = df_chart_p.apply(lambda x: pd.Series(prep_dates(x)), axis=1)
    all_d = []
    if not df_trans.empty: all_d.extend(df_trans['date'].dropna().tolist())
    if not df_chart_p.empty: all_d.extend(df_chart_p['start_date'].tolist() + df_chart_p['end_date'].tolist())
    min_d = min(all_d).replace(day=1) if all_d else date.today()
    max_d = (max(all_d) + timedelta(days=40)).replace(day=1) if all_d else date.today()+timedelta(days=90)
    full_range = pd.date_range(start=min_d, end=max_d, freq='MS')
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, row_heights=[0.5, 0.5], specs=[[{"secondary_y": True}], [{"secondary_y": False}]], subplot_titles=("💰 財務收支與水位", "🗓 專案時程概況"))
    if not df_trans.empty:
        df_ct = df_trans.copy(); df_ct['PlotDate'] = df_ct['date'].apply(lambda x: x.replace(day=1))
        m_st = df_ct.groupby(['PlotDate', 'type'])['amount'].sum().unstack(fill_value=0).reindex(full_range, fill_value=0)
        if '收入' not in m_st.columns: m_st['收入'] = 0
        if '支出' not in m_st.columns: m_st['支出'] = 0
        m_st['Cumulative'] = (m_st['收入'] - m_st['支出']).cumsum()
        fig.add_trace(go.Bar(x=m_st.index, y=m_st['收入'], name='收入', marker_color='#00CC96',
