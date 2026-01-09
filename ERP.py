import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import plotly.express as px  # 引入繪圖庫

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
            st.error("找不到 google_key，請確認 Streamlit Cloud 的 Secrets 設定。")
            st.stop()
        client = gspread.authorize(creds)
        sheet = client.open("Company_Database")
        return sheet
    except Exception as e:
        st.error(f"連線失敗！錯誤訊息: {e}")
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
    except Exception as e:
        st.error(f"初始化欄位失敗: {e}")
        return None, None

st.set_page_config(page_title="雲端公司中控台", layout="wide", page_icon="📊")
st.title("☁️ 公司營運中控台 (V6 視覺化版)")

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
# 2. 戰情儀表板 (KPI & Charts)
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

# 2.1 數字卡片
col1, col2, col3, col4 = st.columns(4)
col1.metric("📅 本月營收", f"${m_income:,.0f}")
col2.metric("💸 本月總開銷", f"${m_expense:,.0f}")
col3.metric("💰 本月淨利", f"${m_balance:,.0f}", delta_color="normal")
col4.metric("🏦 資金水位", f"${total_balance:,.0f}")

st.divider()

# 2.2 視覺化圖表區 (新增功能)
st.subheader("📈 營運視覺化分析")

if not df_trans.empty:
    c_chart1, c_chart2 = st.columns(2)
    
    # 圖表 1: 每月收支趨勢
    with c_chart1:
        st.caption("每月收支對比")
        df_trend = df_trans.copy()
        df_trend['YearMonth'] = df_trend['date'].dt.strftime('%Y-%m')
        df_grouped = df_trend.groupby(['YearMonth', 'type'])['amount'].sum().reset_index()
        
        fig_trend = px.bar(df_grouped, x='YearMonth', y='amount', color='type', 
                           barmode='group', text_auto='.2s',
                           color_discrete_map={'收入':'#00CC96', '支出':'#EF553B'},
                           labels={'amount': '金額', 'YearMonth': '月份'})
        st.plotly_chart(fig_trend, use_container_width=True)

    # 圖表 2: 支出結構 (圓餅圖)
    with c_chart2:
        st.caption("支出佔比分析 (總計)")
        df_exp = df_trans[df_trans['type'] == '支出']
        if not df_exp.empty:
            fig_pie = px.pie(df_exp, values='amount', names='category', hole=0.4,
                             color_discrete_sequence=px.colors.sequential.RdBu)
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("尚無支出數據")
            
    # 圖表 3: 專案獲利排行 (橫向長條圖)
    st.caption("各專案實際獲利 (綠色賺錢 / 紅色賠錢)")
    if not df_projs.empty:
        proj_data = []
        for i, row in df_projs.iterrows():
            p_cost = 0
            p_rev = 0
            if 'project_name' in df_trans.columns:
                p_trans = df_trans[df_trans['project_name'] == row['name']]
                p_cost = p_trans[p_trans['type'] == '支出']['amount'].sum()
                p_rev = p_trans[p_trans['type'] == '收入']['amount'].sum()
            proj_data.append({"專案": row['name'], "獲利": p_rev - p_cost})
        
        df_profit = pd.DataFrame(proj_data).sort_values("獲利", ascending=True)
        # 設定顏色：賺錢綠色，賠錢紅色
        df_profit['color'] = df_profit['獲利'].apply(lambda x: '#00CC96' if x >= 0 else '#EF553B')
        
        fig_proj = px.bar(df_profit, x='獲利', y='專案', orientation='h', text_auto=',',
                          color='color', color_discrete_map="identity") # 使用自定義顏色欄位
        fig_proj.update_layout(showlegend=False)
        st.plotly_chart(fig_proj, use_container_width=True)

else:
    st.info("💡 請先輸入記帳資料，圖表將會自動產生。")

st.divider()

# ==========================================
# 3. 功能分頁 (與 V5 相同)
# ==========================================
tab1, tab2, tab3 = st.tabs(["🏗 專案管理", "✍️ 雲端記帳", "📋 報表修改"])

with tab1: # 專案
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
                st.success("成功")
                st.rerun()
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
            proj_options = {}
            for idx, row in enumerate(raw_projs):
                if idx == 0: continue
                label = f"Row {idx+1}: {row[0]} ({row[3]})"
                proj_options[label] = idx + 1
            sel_proj_label = st.selectbox("選擇操作專案", list(proj_options.keys()))
            if sel_proj_label:
                row_num = proj_options[sel_proj_label]
                curr_data = raw_projs[row_num - 1]
                with st.form("edit_proj"):
                    e_status = st.selectbox("狀態", ["進行中", "結案", "暫停"], index=["進行中", "結案", "暫停"].index(curr_data[3]) if curr_data[3] in ["進行中", "結案", "暫停"] else 0)
                    e_progress = st.slider("進度", 0, 100, int(float(curr_data[4])))
                    c_edit, c_del = st.columns(2)
                    if c_edit.form_submit_button("💾 更新"):
                        ws_projs.update_cell(row_num, 4, e_status); ws_projs.update_cell(row_num, 5, e_progress)
                        st.success("成功"); st.rerun()
                    if c_del.form_submit_button("🗑 刪除", type="primary"):
                        ws_projs.delete_rows(row_num); st.warning("已刪除"); st.rerun()

with tab2: # 記帳
    if 'form_type' not in st.session_state: st.session_state.form_type = "支出"
    if 'form_cat' not in st.session_state: st.session_state.form_cat = "專案款"
    if 'form_note' not in st.session_state: st.session_state.form_note = ""
    
    st.write("⚡️ **常用快速樣板**")
    col_t1, col_t2, col_t3 = st.columns(3)
    if col_t1.button("🏢 帶入：房租"):
        st.session_state.form_type = "支出"; st.session_state.form_cat = "房租"; st.session_state.form_note = f"{datetime.now().month}月 辦公室房租"; st.rerun()
    if col_t2.button("👥 帶入：薪資"):
        st.session_state.form_type = "支出"; st.session_state.form_cat = "薪資"; st.session_state.form_note = f"{datetime.now().month}月 全體薪資"; st.rerun()
    if col_t3.button("🔄 重置"):
        st.session_state.form_type = "支出"; st.session_state.form_cat = "專案款"; st.session_state.form_note = ""; st.rerun()
    
    st.divider()
    p_list = ["公司固定開銷"] + (df_projs['name'].tolist() if not df_projs.empty else [])
    with st.form("add_trans"):
        c1, c2, c3 = st.columns(3)
        t_date = c1.date_input("日期")
        type_opts = ["支出", "收入"]; cat_opts = ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"]
        t_type = c2.selectbox("類型", type_opts, index=type_opts.index(st.session_state.form_type) if st.session_state.form_type in type_opts else 0)
        t_cat = c3.selectbox("科目", cat_opts, index=cat_opts.index(st.session_state.form_cat) if st.session_state.form_cat in cat_opts else 0)
        c4, c5 = st.columns(2)
        t_amt = c4.number_input("金額", min_value=0)
        t_proj = c5.selectbox("歸屬", p_list)
        t_note = st.text_input("備註", value=st.session_state.form_note)
        if st.form_submit_button("寫入雲端"):
            ws_trans.append_row([str(t_date), t_type, t_cat, t_amt, t_note, t_proj, str(datetime.now())])
            st.success("成功"); st.session_state.form_note = ""; st.rerun()

with tab3: # 報表修改
    if len(raw_trans) > 1:
        st.dataframe(df_trans, use_container_width=True)
        st.divider()
        st.write("🛠 **修改帳務**")
        trans_options = {}
        for idx in range(len(raw_trans)-1, 0, -1):
            row = raw_trans[idx]; label = f"Row {idx+1}: {row[0]} | ${row[3]} | {row[2]}"
            trans_options[label] = idx + 1
        sel_trans_label = st.selectbox("選擇紀錄", list(trans_options.keys()))
        if sel_trans_label:
            r_num = trans_options[sel_trans_label]
            curr_row = raw_trans[r_num - 1]
            with st.form("edit_trans"):
                try: default_date = datetime.strptime(curr_row[0], "%Y-%m-%d").date()
                except: default_date = date.today()
                ec1, ec2, ec3 = st.columns(3)
                new_date = ec1.date_input("日期", default_date)
                new_cat = ec2.selectbox("科目", ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"], index=["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"].index(curr_row[2]) if curr_row[2] in ["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"] else 0)
                new_amt = ec3.number_input("金額", min_value=0.0, value=float(curr_row[3]) if curr_row[3] else 0.0)
                new_note = st.text_input("備註", value=curr_row[4])
                b1, b2 = st.columns(2)
                if b1.form_submit_button("💾 確認"):
                    ws_trans.update(range_name=f"A{r_num}:E{r_num}", values=[[str(new_date), curr_row[1], new_cat, new_amt, new_note]])
                    st.success("成功"); st.rerun()
                if b2.form_submit_button("🗑 刪除", type="primary"):
                    ws_trans.delete_rows(r_num); st.warning("已刪除"); st.rerun()
