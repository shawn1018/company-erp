import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import plotly.graph_objects as go # 改用更強大的繪圖模組

# ==========================================
# 1. Google Sheets 連線設定
# ==========================================
SCOPE = ['https://www.googleapis.com/auth/spreadsheets',
         'https://www.googleapis.com/auth/drive']

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

def init_sheets(sheet):
    try:
        try: ws_trans = sheet.worksheet("Transactions")
        except:
            ws_trans = sheet.add_worksheet(title="Transactions", rows=1000, cols=10)
            ws_trans.append_row(["date", "type", "category", "amount", "note", "project_name", "created_at"])
        try: ws_projs = sheet.worksheet("Projects")
        except:
            ws_projs = sheet.add_worksheet(title="Projects", rows=100, cols=10)
            ws_projs.append_row(["name", "total_budget", "start_date", "status", "progress", "created_at"])
        return ws_trans, ws_projs
    except: return None, None

st.set_page_config(page_title="雲端公司中控台", layout="wide", page_icon="📈")
st.title("☁️ 公司營運中控台 (單圖決策版)")

sh = connect_google_sheet()
if not sh: st.stop()
ws_trans, ws_projs = init_sheets(sh)

# 讀取資料
raw_trans = ws_trans.get_all_values()
df_trans = pd.DataFrame(raw_trans[1:], columns=raw_trans[0]) if len(raw_trans) > 1 else pd.DataFrame(columns=["date", "type", "category", "amount", "note", "project_name", "created_at"])

raw_projs = ws_projs.get_all_values()
df_projs = pd.DataFrame(raw_projs[1:], columns=raw_projs[0]) if len(raw_projs) > 1 else pd.DataFrame(columns=["name", "total_budget", "start_date", "status", "progress", "created_at"])

# 資料轉型
if not df_trans.empty:
    df_trans['amount'] = pd.to_numeric(df_trans['amount'], errors='coerce').fillna(0)
    df_trans['date'] = pd.to_datetime(df_trans['date'], errors='coerce')
if not df_projs.empty:
    df_projs['total_budget'] = pd.to_numeric(df_projs['total_budget'], errors='coerce').fillna(0)
    df_projs['progress'] = pd.to_numeric(df_projs['progress'], errors='coerce').fillna(0)

# ==========================================
# 2. 戰情儀表板 (The Master Chart)
# ==========================================
today = datetime.today()

# 計算本月 KPI
if not df_trans.empty:
    mask_month = (df_trans['date'].dt.year == today.year) & (df_trans['date'].dt.month == today.month)
    df_month = df_trans[mask_month]
    m_income = df_month[df_month['type'] == '收入']['amount'].sum()
    m_expense = df_month[df_month['type'] == '支出']['amount'].sum()
    m_balance = m_income - m_expense
    total_balance = df_trans[df_trans['type'] == '收入']['amount'].sum() - df_trans[df_trans['type'] == '支出']['amount'].sum()
else:
    m_income = m_expense = m_balance = total_balance = 0

# 顯示 KPI
col1, col2, col3, col4 = st.columns(4)
col1.metric("📅 本月營收", f"${m_income:,.0f}")
col2.metric("💸 本月開銷", f"${m_expense:,.0f}")
col3.metric("💰 本月淨利", f"${m_balance:,.0f}")
col4.metric("🏦 總資金水位", f"${total_balance:,.0f}")

st.divider()

# --- 繪製「終極單一圖表」 ---
if not df_trans.empty:
    # 1. 資料處理：按月份分組
    df_chart = df_trans.copy()
    df_chart['Month'] = df_chart['date'].dt.strftime('%Y-%m')
    
    # 計算每月的收入與支出
    monthly_stats = df_chart.groupby(['Month', 'type'])['amount'].sum().unstack(fill_value=0)
    if '收入' not in monthly_stats.columns: monthly_stats['收入'] = 0
    if '支出' not in monthly_stats.columns: monthly_stats['支出'] = 0
    
    # 計算每月淨利與累計資金水位
    monthly_stats['Net'] = monthly_stats['收入'] - monthly_stats['支出']
    monthly_stats['Cumulative'] = monthly_stats['Net'].cumsum()
    
    # 2. 開始畫圖
    fig = go.Figure()

    # 柱狀圖：收入 (綠色)
    fig.add_trace(go.Bar(
        x=monthly_stats.index, 
        y=monthly_stats['收入'],
        name='收入 (Income)',
        marker_color='#00CC96'
    ))

    # 柱狀圖：支出 (紅色)
    fig.add_trace(go.Bar(
        x=monthly_stats.index, 
        y=monthly_stats['支出'],
        name='支出 (Expense)',
        marker_color='#EF553B'
    ))

    # 折線圖：資金水位 (藍色線，使用右邊的 Y 軸)
    fig.add_trace(go.Scatter(
        x=monthly_stats.index, 
        y=monthly_stats['Cumulative'],
        name='💰 資金水位 (Total Balance)',
        mode='lines+markers',
        line=dict(color='#636EFA', width=4),
        marker=dict(size=8),
        yaxis='y2' # 指定使用第二個 Y 軸
    ))

    # 3. 版面設定 (雙 Y 軸)
    fig.update_layout(
        title='公司財務全景圖 (月收支 vs 資金累計)',
        xaxis=dict(title='月份'),
        yaxis=dict(title='單月收支金額', side='left'),
        yaxis2=dict(
            title='累計資金水位', 
            side='right', 
            overlaying='y', # 疊加在原本的圖上
            showgrid=False  # 隱藏網格以免混亂
        ),
        barmode='group', # 收入支出的柱子並排顯示
        legend=dict(orientation="h", y=1.1, x=0), # 圖例放上面
        height=500
    )
    
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("💡 請先輸入記帳資料，全景圖將自動生成。")

st.divider()

# ==========================================
# 3. 功能分頁 (保持原樣，僅壓縮排版)
# ==========================================
tab1, tab2, tab3 = st.tabs(["🏗 專案管理", "✍️ 雲端記帳", "📋 報表修改"])

with tab1: 
    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("新增專案")
        with st.form("add_proj"):
            p_name = st.text_input("專案名稱")
            p_budget = st.number_input("預算", min_value=0)
            p_status = st.selectbox("狀態", ["進行中", "結案", "暫停"])
            p_progress = st.slider("進度", 0, 100, 0)
            if st.form_submit_button("上傳"):
                ws_projs.append_row([p_name, p_budget, str(date.today()), p_status, p_progress, str(datetime.now())])
                st.success("成功"); st.rerun()
    with c2:
        st.subheader("專案列表")
        if not df_projs.empty:
            proj_view = []
            for i, row in df_projs.iterrows():
                p_cost = 0; p_rev = 0
                if not df_trans.empty and 'project_name' in df_trans.columns:
                    p_trans = df_trans[df_trans['project_name'] == row['name']]
                    p_cost = p_trans[p_trans['type'] == '支出']['amount'].sum()
                    p_rev = p_trans[p_trans['type'] == '收入']['amount'].sum()
                proj_view.append({"專案": row['name'], "預算": f"${row['total_budget']:,.0f}", "狀態": row['status'], "進度": f"{row['progress']}%", "已投入": f"${p_cost:,.0f}", "獲利": p_rev - p_cost})
            st.dataframe(pd.DataFrame(proj_view), use_container_width=True)
            
            st.write("🛠 **修改或刪除專案**")
            proj_opts = {f"Row {i+1}: {r[0]}": i+1 for i, r in enumerate(raw_projs) if i>0}
            sel_proj = st.selectbox("選擇專案", list(proj_opts.keys()))
            if sel_proj:
                r_num = proj_opts[sel_proj]
                curr = raw_projs[r_num-1]
                with st.form("edit_p"):
                    es = st.selectbox("狀態", ["進行中", "結案", "暫停"], index=["進行中", "結案", "暫停"].index(curr[3]) if curr[3] in ["進行中", "結案", "暫停"] else 0)
                    ep = st.slider("進度", 0, 100, int(float(curr[4])))
                    c_e, c_d = st.columns(2)
                    if c_e.form_submit_button("💾 更新"): ws_projs.update_cell(r_num, 4, es); ws_projs.update_cell(r_num, 5, ep); st.rerun()
                    if c_d.form_submit_button("🗑 刪除", type="primary"): ws_projs.delete_rows(r_num); st.rerun()

with tab2:
    if 'form_type' not in st.session_state: st.session_state.form_type = "支出"
    if 'form_cat' not in st.session_state: st.session_state.form_cat = "專案款"
    if 'form_note' not in st.session_state: st.session_state.form_note = ""
    st.write("⚡️ **常用快速樣板**")
    t1, t2, t3 = st.columns(3)
    if t1.button("🏢 房租"): st.session_state.form_type="支出"; st.session_state.form_cat="房租"; st.session_state.form_note=f"{datetime.now().month}月房租"; st.rerun()
    if t2.button("👥 薪資"): st.session_state.form_type="支出"; st.session_state.form_cat="薪資"; st.session_state.form_note=f"{datetime.now().month}月薪資"; st.rerun()
    if t3.button("🔄 重置"): st.session_state.form_type="支出"; st.session_state.form_cat="專案款"; st.session_state.form_note=""; st.rerun()
    st.divider()
    p_list = ["公司固定開銷"] + (df_projs['name'].tolist() if not df_projs.empty else [])
    with st.form("add_t"):
        c1, c2, c3 = st.columns(3)
        d = c1.date_input("日期"); ty = c2.selectbox("類型", ["支出", "收入"], index=["支出", "收入"].index(st.session_state.form_type)); ca = c3.selectbox("科目", ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"], index=["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"].index(st.session_state.form_cat))
        c4, c5 = st.columns(2); am = c4.number_input("金額", min_value=0); pr = c5.selectbox("歸屬", p_list); no = st.text_input("備註", value=st.session_state.form_note)
        if st.form_submit_button("寫入雲端"): ws_trans.append_row([str(d), ty, ca, am, no, pr, str(datetime.now())]); st.success("成功"); st.session_state.form_note=""; st.rerun()

with tab3:
    if len(raw_trans) > 1:
        st.dataframe(df_trans, use_container_width=True)
        st.divider()
        st.write("🛠 **修改帳務**")
        opts = {f"Row {i+1}: {r[0]} | ${r[3]}": i+1 for i, r in enumerate(raw_trans) if i>0}
        sel = st.selectbox("選擇紀錄", sorted(list(opts.keys()), reverse=True))
        if sel:
            r = opts[sel]; cr = raw_trans[r-1]
            with st.form("ed_t"):
                nd = st.date_input("日期", datetime.strptime(cr[0], "%Y-%m-%d").date() if cr[0] else date.today())
                nc = st.selectbox("科目", ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"], index=["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"].index(cr[2]) if cr[2] in ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"] else 0)
                na = st.number_input("金額", value=float(cr[3]) if cr[3] else 0.0)
                nn = st.text_input("備註", value=cr[4])
                b1, b2 = st.columns(2)
                if b1.form_submit_button("💾 確認"): ws_trans.update(range_name=f"A{r}:E{r}", values=[[str(nd), cr[1], nc, na, nn]]); st.rerun()
                if b2.form_submit_button("🗑 刪除", type="primary"): ws_trans.delete_rows(r); st.rerun()
