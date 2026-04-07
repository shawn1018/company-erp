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
# 1. Google Sheets 連線設定
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
            for i, cat in enumerate(["專案款", "薪資", "房租", "外包", "雜支"]):
                ws_settings.update_cell(i+2, 1, cat)
            ws_settings.update_cell(2, 2, "公司固定開銷")
                
        return ws_trans, ws_projs, ws_settings
    except: return None, None, None

ws_trans, ws_projs, ws_settings = init_sheets(sh)

@st.cache_data(ttl=60)
def load_data(_ws_trans, _ws_projs, _ws_settings):
    raw_trans = _ws_trans.get_all_values()
    if len(raw_trans) > 1:
        df_trans = pd.DataFrame(raw_trans[1:], columns=raw_trans[0])
        df_trans['_sheet_row'] = range(2, len(df_trans) + 2)
    else:
        df_trans = pd.DataFrame(columns=["date", "type", "category", "amount", "note", "project_name", "created_at", "_sheet_row"])

    raw_projs = _ws_projs.get_all_values()
    std_columns = ["name", "total_budget", "start_date", "status", "progress", "created_at", "end_date", "mid_date"]
    if len(raw_projs) > 1:
        clean_data = []
        for row in raw_projs[1:]:
            while len(row) < 8: row.append("")
            clean_data.append(row[:8])
        df_projs = pd.DataFrame(clean_data, columns=std_columns)
        df_projs['_sheet_row'] = range(2, len(df_projs) + 2)
    else:
        df_projs = pd.DataFrame(columns=std_columns + ["_sheet_row"])

    raw_settings = _ws_settings.get_all_values()
    cat_list = []
    attr_list = []
    if len(raw_settings) > 1:
        cat_list = [row[0] for row in raw_settings[1:] if len(row) > 0 and row[0].strip() != ""]
        attr_list = [row[1] for row in raw_settings[1:] if len(row) > 1 and row[1].strip() != ""]
    if not cat_list: cat_list = ["專案款", "薪資", "雜支"]
    if not attr_list: attr_list = ["公司固定開銷"]
    return df_trans, df_projs, cat_list, attr_list

df_trans, df_projs, cat_list, attr_list = load_data(ws_trans, ws_projs, ws_settings)
project_options = attr_list + (df_projs['name'].tolist() if not df_projs.empty else [])

# 資料轉型
if not df_trans.empty:
    df_trans['amount'] = pd.to_numeric(df_trans['amount'], errors='coerce').fillna(0)
    df_trans['date'] = pd.to_datetime(df_trans['date'], errors='coerce')

if not df_projs.empty:
    df_projs['total_budget'] = pd.to_numeric(df_projs['total_budget'].str.replace(',',''), errors='coerce').fillna(0) if df_projs['total_budget'].dtype == object else pd.to_numeric(df_projs['total_budget'], errors='coerce').fillna(0)
    df_projs['progress'] = pd.to_numeric(df_projs['progress'], errors='coerce').fillna(0)
    df_projs['start_date'] = pd.to_datetime(df_projs['start_date'], errors='coerce')
    df_projs['end_date'] = pd.to_datetime(df_projs['end_date'], errors='coerce')
    df_projs['mid_date'] = pd.to_datetime(df_projs['mid_date'], errors='coerce')
    df_projs['created_at'] = pd.to_datetime(df_projs['created_at'], errors='coerce')
    status_mapping = {"進行中": "🟢 進行中", "暫停": "🟠 暫停", "結案": "🔘 結案", "待尾款": "🔴 待尾款"}
    df_projs['status'] = df_projs['status'].apply(lambda x: status_mapping.get(x, x))

def fmt_num(num):
    if num is None: return "$0"
    abs_num = abs(num)
    if abs_num >= 1_000_000: return f"${num/1_000_000:.1f}M"
    elif abs_num >= 1_000: return f"${num/1_000:.1f}K"
    else: return f"${num:,.0f}"

# ==========================================
# 2. 戰情儀表板 (KPI)
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

if not df_projs.empty:
    total_budget_sum = df_projs['total_budget'].sum()
    df_projs_calc = df_projs.copy()
    if not df_trans.empty:
        expenses = df_trans[df_trans['type'] == '支出']
        proj_costs = expenses.groupby('project_name')['amount'].sum()
        df_projs_calc['cost'] = df_projs_calc['name'].map(proj_costs).fillna(0)
    else: df_projs_calc['cost'] = 0
    total_real_income_sum = ((df_projs_calc['total_budget'] * 0.95) - df_projs_calc['cost']).sum()
else: total_budget_sum = total_real_income_sum = 0

st.set_page_config(page_title="雲端公司中控台", layout="wide", page_icon="🚥")
st.title("☁️ 公司營運中控台 (V43 多維統計版)")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("📅 本月營收", fmt_num(m_income))
col2.metric("💸 本月開銷", fmt_num(m_expense))
col3.metric("💰 本月淨利", fmt_num(m_balance))
col4.metric("🏦 總資金水位", fmt_num(total_balance))
col5.metric("🏆 年度營業額 / 實收", f"{fmt_num(total_budget_sum)} / {fmt_num(total_real_income_sum)}")
st.divider()

# ==========================================
# 全景圖
# ==========================================
if not df_trans.empty or not df_projs.empty:
    df_chart_projs = df_projs.copy()
    def prepare_chart_dates(row):
        s = row['start_date']; e = row['end_date']; m = row['mid_date']
        if pd.isnull(s): s = datetime.today()
        if pd.isnull(e): e = s + timedelta(days=30)
        if s == e: e = s + timedelta(days=1)
        if pd.notnull(m) and not (s < m < e): m = pd.NaT 
        return s, e, m
    if not df_chart_projs.empty:
        df_chart_projs[['start_date', 'end_date', 'mid_date']] = df_chart_projs.apply(lambda x: pd.Series(prepare_chart_dates(x)), axis=1)
    all_dates = []
    if not df_trans.empty: all_dates.extend(df_trans['date'].dropna().tolist())
    if not df_chart_projs.empty: 
        all_dates.extend(df_chart_projs['start_date'].dropna().tolist())
        all_dates.extend(df_chart_projs['end_date'].dropna().tolist())
    if all_dates:
        min_date = min(all_dates).replace(day=1) 
        max_date = (max(all_dates) + timedelta(days=40)).replace(day=1)
        full_date_range = pd.date_range(start=min_date, end=max_date, freq='MS')
    else:
        min_date = date.today(); max_date = date.today() + timedelta(days=90); full_date_range = pd.date_range(start=min_date, end=max_date, freq='MS')

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, row_heights=[0.5, 0.5], specs=[[{"secondary_y": True}], [{"secondary_y": False}]], subplot_titles=("💰 財務收支與水位", "🗓 專案時程概況"))
    if not df_trans.empty:
        df_chart = df_trans.copy(); df_chart['PlotDate'] = df_chart['date'].apply(lambda x: x.replace(day=1))
        monthly_stats = df_chart.groupby(['PlotDate', 'type'])['amount'].sum().unstack(fill_value=0)
        monthly_stats = monthly_stats.reindex(full_date_range, fill_value=0)
        if '收入' not in monthly_stats.columns: monthly_stats['收入'] = 0
        if '支出' not in monthly_stats.columns: monthly_stats['支出'] = 0
        monthly_stats['Cumulative'] = (monthly_stats['收入'] - monthly_stats['支出']).cumsum()
        fig.add_trace(go.Bar(x=monthly_stats.index, y=monthly_stats['收入'], name='收入', marker_color='#00CC96', opacity=0.7), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Bar(x=monthly_stats.index, y=monthly_stats['支出'], name='支出', marker_color='#EF553B', opacity=0.7), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=monthly_stats.index, y=monthly_stats['Cumulative'], name='資金水位', mode='lines+markers', line=dict(color='#636EFA', width=3)), row=1, col=1, secondary_y=True)
    if not df_chart_projs.empty:
        color_map = {"🟢 進行中": "#00CC96", "🔴 待尾款": "#EF553B", "🟠 暫停": "#FFA15A", "🔘 結案": "#B0B0B0"}
        df_p_sorted = df_chart_projs.sort_values("start_date")
        for i, row in df_p_sorted.iterrows():
            status_color = color_map.get(row['status'], "#888888")
            s = row['start_date']; e = row['end_date']; m = row['mid_date']
            proj_income_sum = df_trans[(df_trans['project_name'] == row['name']) & (df_trans['type'] == '收入')]['amount'].sum() if not df_trans.empty else 0
            income_label = f"💰{fmt_num(proj_income_sum)}" if proj_income_sum > 0 else ""
            budget_label = f"合約:{fmt_num(row['total_budget'])}" if row['total_budget'] > 0 else ""
            mid_tp = s + (e - s) / 2
            if pd.notnull(m) and s < m < e:
                fig.add_trace(go.Scatter(x=[s, m], y=[row['name'], row['name']], mode="lines+markers", line=dict(color=status_color, width=20), marker=dict(symbol="line-ns", size=10, color="white"), name=row['name'], showlegend=False), row=2, col=1)
                fig.add_trace(go.Scatter(x=[m, e], y=[row['name'], row['name']], mode="lines", line=dict(color=status_color, width=20), opacity=0.4, name=row['name'], showlegend=False), row=2, col=1)
                fig.add_trace(go.Scatter(x=[m], y=[row['name']], mode="markers", marker=dict(symbol="diamond", size=12, color="gold", line=dict(width=1, color="black")), name="期中", showlegend=False), row=2, col=1)
            else:
                fig.add_trace(go.Scatter(x=[s, e], y=[row['name'], row['name']], mode="lines", line=dict(color=status_color, width=20), name=row['name'], showlegend=False), row=2, col=1)
            if income_label: fig.add_trace(go.Scatter(x=[mid_tp], y=[row['name']], mode="text", text=[income_label], textposition="top center", textfont=dict(size=11, color="#006600"), showlegend=False, hoverinfo='skip'), row=2, col=1)
            if budget_label: fig.add_trace(go.Scatter(x=[e], y=[row['name']], mode="text", text=[budget_label], textposition="middle right", textfont=dict(size=11, color="#CC0000"), showlegend=False, hoverinfo='skip'), row=2, col=1)
    fig.update_layout(height=700, barmode='group', legend=dict(orientation="h", y=1.1, x=0), yaxis=dict(title="單月收支", tickformat=".2s"), yaxis2=dict(title="累計水位", overlaying='y', side='right', tickformat=".2s"), yaxis3=dict(title="專案"))
    fig.update_xaxes(range=[min_date, max_date], tickformat="%Y-%m", dtick="M1", showgrid=True, gridwidth=1, gridcolor='rgba(211, 211, 211, 0.6)', griddash='dash', ticklabelmode="period")
    st.plotly_chart(fig, use_container_width=True)
else: st.info("💡 請輸入資料")

st.divider()

# ==========================================
# 3. 功能分頁
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🏗 專案管理", "✍️ 雲端記帳", "📋 帳務總表", "📊 統計報表"])

def save_and_reload():
    st.cache_data.clear(); st.success("成功！"); time.sleep(1); st.rerun()

# --- Tab 1 & 2 & 3 (保持 V42 功能) ---
with tab1: # 專案
    with st.expander("➕ 新增專案"):
        with st.form("add_proj"):
            c1, c2, c3 = st.columns(3); p_name = c1.text_input("專案名稱"); p_budget = c2.number_input("預算", min_value=0); p_status = c3.selectbox("狀態", ["🟢 進行中", "🔴 待尾款", "🔘 結案", "🟠 暫停"])
            c4, c5, c6 = st.columns(3); p_start = c4.date_input("開始日期", date.today()); p_mid = c5.date_input("🔸 期中驗收 (選填)", value=None); p_end = c6.date_input("預計結束", date.today() + timedelta(days=30))
            p_progress = st.slider("進度", 0, 100, 0)
            if st.form_submit_button("新增"):
                ws_projs.append_row([p_name, p_budget, str(p_start), p_status, p_progress, str(datetime.now()), str(p_end), str(p_mid) if p_mid else ""]); save_and_reload()
    st.subheader("專案列表 (Excel 編輯模式)")
    if not df_projs.empty:
        sort_col, spacer = st.columns([1, 2]); sort_opt = sort_col.selectbox("🔃 排序方式", ["依建立日期 (預設)", "依金額", "依狀態", "依名稱"])
        if sort_opt == "依金額": df_disp = df_projs.sort_values("total_budget", ascending=False)
        elif sort_opt == "依狀態": df_disp = df_projs.sort_values("status")
        elif sort_opt == "依名稱": df_disp = df_projs.sort_values("name")
        else: df_disp = df_projs.sort_values("created_at", ascending=False)
        costs = df_trans[df_trans['type'] == '支出'].groupby('project_name')['amount'].sum() if not df_trans.empty else pd.Series()
        df_disp['real_income'] = (df_disp['total_budget'] * 0.95) - df_disp['name'].map(costs).fillna(0)
        df_disp['profit_margin'] = (df_disp['real_income'] / df_disp['total_budget'] * 100).fillna(0)
        edited_df = st.data_editor(df_disp, key="proj_editor", num_rows="dynamic", use_container_width=True, column_config={"name": "專案名稱", "total_budget": st.column_config.NumberColumn("預算", format="$%d"), "real_income": st.column_config.NumberColumn("實收", format="$%d", disabled=True), "profit_margin": st.column_config.ProgressColumn("利潤比", format="%.1f%%", min_value=-100, max_value=100), "progress": st.column_config.NumberColumn("進度 (%)", format="%d%%", min_value=0, max_value=100, step=5), "status": st.column_config.SelectboxColumn("狀態", options=["🟢 進行中", "🔴 待尾款", "🔘 結案", "🟠 暫停"]), "created_at": None, "_sheet_row": None}, hide_index=True)
        if st.button("💾 儲存專案變更"):
            try:
                ch = st.session_state["proj_editor"]; header_p = ws_projs.row_values(1)
                if ch.get("deleted_rows"):
                    for r in sorted([int(df_disp.iloc[idx]['_sheet_row']) for idx in ch["deleted_rows"]], reverse=True): ws_projs.delete_rows(r)
                if ch.get("edited_rows"):
                    col_map = {name: i+1 for i, name in enumerate(header_p)}
                    for idx_s, c_dict in ch["edited_rows"].items():
                        idx = int(idx_s); r_row = int(df_disp.iloc[idx]['_sheet_row'])
                        for c_name, val in c_dict.items():
                            if c_name in col_map: ws_projs.update_cell(r_row, col_map[c_name], str(val) if isinstance(val, (date, datetime)) else val)
                save_and_reload()
            except Exception as e: st.error(f"失敗: {e}")

with tab2: # 記帳
    with st.expander("⚙️ 設定"):
        sc1, sc2 = st.columns(2)
        with sc1:
            st.write("📂 科目"); n_cat = st.text_input("新增科目");
            if st.button("➕"): ws_settings.append_row([n_cat]); save_and_reload()
            d_cat = st.selectbox("刪除科目", ["(選取)"] + cat_list)
            if st.button("🗑"): ws_settings.update_cell(ws_settings.find(d_cat).row, 1, ""); save_and_reload()
        with sc2:
            st.write("🏢 歸屬"); n_attr = st.text_input("新增歸屬");
            if st.button("➕ "): ws_settings.update_cell(len(attr_list)+2, 2, n_attr); save_and_reload()
    st.write("⚡️ 樣板"); t1, t2, t3 = st.columns(3)
    if t1.button("🏢 房租"): st.session_state.form_type="支出"; st.session_state.form_cat="房租"; st.session_state.form_note=f"{datetime.now().month}月房租"; st.rerun()
    if t2.button("👥 薪資"): st.session_state.form_type="支出"; st.session_state.form_cat="薪資"; st.session_state.form_note=f"{datetime.now().month}月薪資"; st.rerun()
    with st.form("add_t"):
        c1, c2, c3 = st.columns(3); d = c1.date_input("日期"); ty = c2.selectbox("類型", ["支出", "收入"], index=0); ca = c3.selectbox("科目", cat_list); am = st.number_input("金額", min_value=0); pr = st.selectbox("歸屬", project_options); no = st.text_input("備註", value=st.session_state.get('form_note', ''))
        if st.form_submit_button("寫入雲端"): ws_trans.append_row([str(d), ty, ca, am, no, pr, str(datetime.now())]); save_and_reload()

with tab3: # 帳務總表
    if not df_trans.empty:
        df_trans['YearMonth'] = df_trans['date'].dt.strftime('%Y-%m'); grouped = df_trans.groupby('YearMonth'); sorted_m = sorted(list(grouped.groups.keys()), reverse=True); all_ed = {}
        for m in sorted_m:
            g_df = grouped.get_group(m).sort_values('date', ascending=False); m_inc = g_df[g_df['type']=='收入']['amount'].sum(); m_exp = g_df[g_df['type']=='支出']['amount'].sum()
            with st.expander(f"📅 {m} | 🟢 +{fmt_num(m_inc)} | 🔴 -{fmt_num(m_exp)}"):
                all_ed[m] = st.data_editor(g_df, key=f"ed_{m}", num_rows="dynamic", use_container_width=True, column_config={"date": st.column_config.DateColumn("日期"), "type": st.column_config.SelectboxColumn("類型", options=["支出", "收入"]), "category": st.column_config.SelectboxColumn("科目", options=cat_list), "amount": st.column_config.NumberColumn("金額", format="$%d"), "project_name": st.column_config.SelectboxColumn("歸屬", options=project_options), "created_at": None, "_sheet_row": None, "YearMonth": None}, hide_index=True)
        if st.button("💾 儲存變更"):
            header_t = ws_trans.row_values(1); col_map_t = {name: i+1 for i, name in enumerate(header_t)}
            for key in st.session_state:
                if key.startswith("ed_"):
                    ch = st.session_state[key]; o_df = grouped.get_group(key.replace("ed_",""))
                    if ch.get("deleted_rows"):
                        for r in sorted([int(o_df.iloc[idx]['_sheet_row']) for idx in ch["deleted_rows"]], reverse=True): ws_trans.delete_rows(r)
                    if ch.get("edited_rows"):
                        for idx_s, c_dict in ch["edited_rows"].items():
                            r_row = int(o_df.iloc[int(idx_s)]['_sheet_row'])
                            for c_name, val in c_dict.items():
                                if c_name in col_map_t: ws_trans.update_cell(r_row, col_map_t[c_name], str(val) if isinstance(val, (date, datetime)) else val)
            save_and_reload()

# --- Tab 4: 統計報表 (V43 多維度時間版) ---
with tab4:
    st.subheader("📊 統計分析報表")
    
    if not df_trans.empty:
        # 【V43】時間維度選擇器
        with st.expander("⏳ 選擇統計範圍", expanded=True):
            t_mode = st.radio("統計模式", ["單一月份", "年初至今 (YTD)", "全部資料"], horizontal=True)
            
            # 準備可選年份與月份
            df_trans['Year'] = df_trans['date'].dt.year
            df_trans['YearMonth'] = df_trans['date'].dt.strftime('%Y-%m')
            
            all_years = sorted(df_trans['Year'].unique().tolist(), reverse=True)
            all_months = sorted(df_trans['YearMonth'].unique().tolist(), reverse=True)

            if t_mode == "單一月份":
                sel_m = st.selectbox("選擇月份", all_months)
                df_time_filtered = df_trans[df_trans['YearMonth'] == sel_m]
                stat_title = f"{sel_m}"
            elif t_mode == "年初至今 (YTD)":
                sel_y = st.selectbox("選擇年份", all_years)
                # 過濾該年份且日期小於等於今天的資料
                df_time_filtered = df_trans[(df_trans['Year'] == sel_y) & (df_trans['date'] <= pd.Timestamp(date.today()))]
                stat_title = f"{sel_y} 年初至今"
            else:
                df_time_filtered = df_trans
                stat_title = "全部歷史"

        # 進階篩選：科目與歸屬
        with st.expander("🔎 進階項目篩選"):
            f1, f2 = st.columns(2)
            # 動態抓取該時間範圍內有的項目
            cats_in_range = df_time_filtered['category'].unique().tolist()
            projs_in_range = df_time_filtered['project_name'].unique().tolist()
            
            sel_cats = f1.multiselect("科目 (預設全選)", cats_in_range, default=cats_in_range)
            sel_projs = f2.multiselect("歸屬 (預設全選)", projs_in_range, default=projs_in_range)
        
        # 執行最終過濾
        final_stat_df = df_time_filtered[
            (df_time_filtered['category'].isin(sel_cats)) & 
            (df_time_filtered['project_name'].isin(sel_projs))
        ]
        
        if not final_stat_df.empty:
            st.divider()
            st.markdown(f"#### 📈 {stat_title} 統計結果")
            
            # 計算該範圍總額
            total_in = final_stat_df[final_stat_df['type']=='收入']['amount'].sum()
            total_out = final_stat_df[final_stat_df['type']=='支出']['amount'].sum()
            
            c_s1, c_s2, c_s3 = st.columns(3)
            c_s1.metric(f"{stat_title} 總收入", fmt_num(total_in))
            c_s2.metric(f"{stat_title} 總支出", fmt_num(total_out))
            c_s3.metric(f"{stat_title} 淨損益", fmt_num(total_in - total_out), delta=total_in - total_out)

            chart1, chart2 = st.columns(2)
            with chart1:
                st.markdown("##### 📂 科目統計")
                df_c = final_stat_df.groupby(['category', 'type'])['amount'].sum().reset_index()
                st.plotly_chart(px.bar(df_c, x='category', y='amount', color='type', barmode='group', color_discrete_map={'收入':'#00CC96', '支出':'#EF553B'}, text_auto='.2s'), use_container_width=True)
            with chart2:
                st.markdown("##### 🏢 歸屬統計")
                df_p = final_stat_df.groupby(['project_name', 'type'])['amount'].sum().reset_index()
                st.plotly_chart(px.bar(df_p, x='project_name', y='amount', color='type', barmode='group', color_discrete_map={'收入':'#00CC96', '支出':'#EF553B'}, text_auto='.2s'), use_container_width=True)
            
            with st.expander("📋 查看此範圍明細"):
                st.dataframe(final_stat_df[['date', 'type', 'category', 'amount', 'project_name', 'note']].sort_values('date', ascending=False), use_container_width=True)
        else:
            st.warning("所選範圍內無資料")
    else:
        st.info("尚無帳務資料")
