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
# 1. 系統設定與 Google Sheets 連線
# ==========================================
st.set_page_config(page_title="雲端公司中控台", layout="wide", page_icon="🚥")

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

# --- 資料讀取與快取 ---
@st.cache_data(ttl=60)
def load_data(_ws_trans, _ws_projs, _ws_settings):
    # 讀取交易紀錄
    raw_t = _ws_trans.get_all_values()
    df_t = pd.DataFrame(raw_t[1:], columns=raw_t[0]) if len(raw_t) > 1 else pd.DataFrame(columns=["date", "type", "category", "amount", "note", "project_name", "created_at"])
    df_t['_sheet_row'] = range(2, len(df_t) + 2) # 記錄 Google Sheet 真實行號
    
    # 讀取專案
    raw_p = _ws_projs.get_all_values()
    std_p_cols = ["name", "total_budget", "start_date", "status", "progress", "created_at", "end_date", "mid_date"]
    if len(raw_p) > 1:
        clean_p = [ (r + [""]*8)[:8] for r in raw_p[1:] ]
        df_p = pd.DataFrame(clean_p, columns=std_p_cols)
        df_p['_sheet_row'] = range(2, len(df_p) + 2)
    else:
        df_p = pd.DataFrame(columns=std_p_cols + ["_sheet_row"])
        
    # 讀取設定
    raw_s = _ws_settings.get_all_values()
    c_list = [r[0] for r in raw_s[1:] if len(r)>0 and r[0].strip()!=""]
    a_list = [r[1] for r in raw_s[1:] if len(r)>1 and r[1].strip()!=""]
    return df_t, df_p, c_list, a_list

df_trans, df_projs, cat_list, attr_list = load_data(ws_trans, ws_projs, ws_settings)
project_options = attr_list + (df_projs['name'].tolist() if not df_projs.empty else [])

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

# 數字美化 (1500 -> $1.5K)
def fmt_num(num):
    if num is None: return "$0"
    abs_n = abs(num)
    prefix = "-" if num < 0 else ""
    if abs_n >= 1_000_000: val = f"${prefix}{abs_n/1_000_000:.1f}M"
    elif abs_n >= 1_000: val = f"${prefix}{abs_n/1_000:.1f}K"
    else: val = f"${prefix}{abs_n:,.0f}"
    return val

# ==========================================
# 2. 頂部看板 (KPI & 全景圖)
# ==========================================
today = datetime.today()
m_income = m_expense = m_balance = total_balance = 0
if not df_trans.empty:
    m_mask = (df_trans['date'].dt.year == today.year) & (df_trans['date'].dt.month == today.month)
    m_income = df_trans[m_mask & (df_trans['type'] == '收入')]['amount'].sum()
    m_expense = df_trans[m_mask & (df_trans['type'] == '支出')]['amount'].sum()
    m_balance = m_income - m_expense
    total_balance = df_trans[df_trans['type'] == '收入']['amount'].sum() - df_trans[df_trans['type'] == '支出']['amount'].sum()

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

# 全景圖繪製
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

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, row_heights=[0.5, 0.5], 
                        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
                        subplot_titles=("💰 財務收支與水位", "🗓 專案時程概況"))

    if not df_trans.empty:
        df_ct = df_trans.copy(); df_ct['PlotDate'] = df_ct['date'].apply(lambda x: x.replace(day=1))
        m_st = df_ct.groupby(['PlotDate', 'type'])['amount'].sum().unstack(fill_value=0).reindex(full_range, fill_value=0)
        if '收入' not in m_st.columns: m_st['收入'] = 0
        if '支出' not in m_st.columns: m_st['支出'] = 0
        m_st['Cumulative'] = (m_st['收入'] - m_st['支出']).cumsum()
        fig.add_trace(go.Bar(x=m_st.index, y=m_st['收入'], name='收入', marker_color='#00CC96', opacity=0.7), row=1, col=1)
        fig.add_trace(go.Bar(x=m_st.index, y=m_st['支出'], name='支出', marker_color='#EF553B', opacity=0.7), row=1, col=1)
        fig.add_trace(go.Scatter(x=m_st.index, y=m_st['Cumulative'], name='資金水位', mode='lines+markers', line=dict(color='#636EFA', width=3)), row=1, col=1, secondary_y=True)

    if not df_chart_p.empty:
        c_map = {"🟢 進行中": "#00CC96", "🔴 待尾款": "#EF553B", "🟠 暫停": "#FFA15A", "🔘 結案": "#B0B0B0"}
        for i, row in df_chart_p.sort_values("start_date").iterrows():
            clr = c_map.get(row['status'], "#888888"); s, e, m = row['start_date'], row['end_date'], row['mid_date']
            proj_in = df_trans[(df_trans['project_name']==row['name']) & (df_trans['type']=='收入')]['amount'].sum() if not df_trans.empty else 0
            if pd.notnull(m) and s < m < e:
                fig.add_trace(go.Scatter(x=[s, m], y=[row['name'], row['name']], mode="lines+markers", line=dict(color=clr, width=18), marker=dict(symbol="line-ns", color="white"), showlegend=False), row=2, col=1)
                fig.add_trace(go.Scatter(x=[m, e], y=[row['name'], row['name']], mode="lines", line=dict(color=clr, width=18), opacity=0.4, showlegend=False), row=2, col=1)
                fig.add_trace(go.Scatter(x=[m], y=[row['name']], mode="markers", marker=dict(symbol="diamond", size=10, color="gold"), showlegend=False), row=2, col=1)
            else:
                fig.add_trace(go.Scatter(x=[s, e], y=[row['name'], row['name']], mode="lines", line=dict(color=clr, width=18), showlegend=False), row=2, col=1)
            if proj_in > 0: fig.add_trace(go.Scatter(x=[s+(e-s)/2], y=[row['name']], mode="text", text=[f"💰{fmt_num(proj_in)}"], textposition="top center", textfont=dict(size=10, color="green"), showlegend=False), row=2, col=1)
            fig.add_trace(go.Scatter(x=[e], y=[row['name']], mode="text", text=[f"合約:{fmt_num(row['total_budget'])}"], textposition="middle right", textfont=dict(size=10, color="red"), showlegend=False), row=2, col=1)

    fig.update_layout(height=700, barmode='group', legend=dict(orientation="h", y=1.1, x=0), yaxis=dict(title="單月收支", tickformat=".2s"), yaxis2=dict(title="累計水位", overlaying='y', side='right', tickformat=".2s", showgrid=False))
    fig.update_xaxes(range=[min_d, max_d], tickformat="%Y-%m", dtick="M1", showgrid=True, gridcolor='rgba(211,211,211,0.5)', griddash='dash', ticklabelmode="period")
    st.plotly_chart(fig, use_container_width=True)
    st.markdown('<div style="display: flex; gap: 15px; justify-content: center; font-size: 13px; color: #666;"><span>🟢 進行中</span><span>🔴 待尾款</span><span>🔘 結案</span><span>🟠 暫停</span></div>', unsafe_allow_html=True)
else: st.info("💡 請輸入資料以生成圖表")

# ==========================================
# 3. 功能分頁
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🏗 專案管理", "✍️ 雲端記帳", "📋 帳務總表", "📊 統計報表"])

def save_and_reload():
    st.cache_data.clear(); st.success("已同步雲端！"); time.sleep(1); st.rerun()

# --- Tab 1: 專案管理 (精準刪除版) ---
with tab1:
    with st.expander("➕ 新增專案"):
        with st.form("add_p"):
            c1, c2, c3 = st.columns(3); name = c1.text_input("名稱"); budg = c2.number_input("預算", min_value=0); stat = c3.selectbox("狀態", ["🟢 進行中", "🔴 待尾款", "🔘 結案", "🟠 暫停"])
            c4, c5, c6 = st.columns(3); s_d = c4.date_input("開始"); m_d = c5.date_input("驗收(選填)", value=None); e_d = c6.date_input("結束", date.today()+timedelta(days=30))
            if st.form_submit_button("新增"):
                ws_projs.append_row([name, budg, str(s_d), stat, 0, str(datetime.now()), str(e_d), str(m_d) if m_d else ""]); save_and_reload()
    
    if not df_projs.empty:
        sort_p = st.selectbox("🔃 列表排序方式", ["依建立日期", "依金額", "依狀態", "依名稱"])
        if sort_p=="依金額": df_dp = df_projs.sort_values("total_budget", ascending=False)
        elif sort_p=="依狀態": df_dp = df_projs.sort_values("status")
        elif sort_p=="依名稱": df_dp = df_projs.sort_values("name")
        else: df_dp = df_projs.sort_values("created_at", ascending=False)
        
        costs = df_trans[df_trans['type']=='支出'].groupby('project_name')['amount'].sum() if not df_trans.empty else pd.Series()
        df_dp['real_income'] = (df_dp['total_budget']*0.95) - df_dp['name'].map(costs).fillna(0)
        df_dp['profit_margin'] = (df_dp['real_income']/df_dp['total_budget']*100).fillna(0)
        
        edit_p = st.data_editor(df_dp, key="p_edit", num_rows="dynamic", use_container_width=True, 
                                column_config={"name":"名稱","total_budget":st.column_config.NumberColumn("預算", format="$%d"),
                                "real_income":st.column_config.NumberColumn("實收", format="$%d", disabled=True),
                                "profit_margin":st.column_config.ProgressColumn("利潤比", format="%.1f%%", min_value=-100, max_value=100),
                                "progress":st.column_config.NumberColumn("進度%", min_value=0, max_value=100, step=5),
                                "status":st.column_config.SelectboxColumn("狀態", options=["🟢 進行中", "🔴 待尾款", "🔘 結案", "🟠 暫停"]),
                                "created_at":None,"_sheet_row":None}, hide_index=True)
        
        if st.button("💾 儲存專案變更"):
            try:
                ch = st.session_state["p_edit"]; head = ws_projs.row_values(1)
                # 處理刪除：依據絕對列號由大到小刪除
                if ch.get("deleted_rows"):
                    del_rows = [int(df_dp.iloc[i]['_sheet_row']) for i in ch["deleted_rows"]]
                    for r in sorted(del_rows, reverse=True): ws_projs.delete_rows(r)
                # 處理修改
                if ch.get("edited_rows"):
                    col_map = {n: i+1 for i, n in enumerate(head)}
                    t_head = ws_trans.row_values(1); t_col = t_head.index("project_name")+1 if "project_name" in t_head else -1
                    for idx_s, c_dict in ch["edited_rows"].items():
                        idx = int(idx_s); r_row = int(df_dp.iloc[idx]['_sheet_row'])
                        if "name" in c_dict and t_col != -1: # 連動更名
                            old_n = df_dp.iloc[idx]['name']; new_n = c_dict["name"]
                            if old_n != new_n:
                                for ri, val in enumerate(ws_trans.col_values(t_col)):
                                    if val==old_n: ws_trans.update_cell(ri+1, t_col, new_n)
                        for cn, v in c_dict.items():
                            if cn in col_map: ws_projs.update_cell(r_row, col_map[cn], str(v) if isinstance(v, (date, datetime)) else v)
                save_and_reload()
            except Exception as e: st.error(f"錯誤: {e}")

# --- Tab 2: 雲端記帳 ---
with tab2:
    with st.expander("⚙️ 設定管理"):
        ca1, ca2 = st.columns(2)
        with ca1:
            nc = st.text_input("新增科目")
            if st.button("➕ 科目"): ws_settings.append_row([nc]); save_and_reload()
            dc = st.selectbox("刪除科目", ["(選取)"]+cat_list)
            if st.button("🗑 科目"): ws_settings.update_cell(ws_settings.find(dc).row, 1, ""); save_and_reload()
        with ca2:
            na = st.text_input("新增固定歸屬")
            if st.button("➕ 歸屬"): ws_settings.update_cell(len(attr_list)+2, 2, na); save_and_reload()
            da = st.selectbox("刪除歸屬", ["(選取)"]+attr_list)
            if st.button("🗑 歸屬"): ws_settings.update_cell(ws_settings.find(da).row, 2, ""); save_and_reload()
    st.write("⚡️ 樣板快捷鍵")
    t1, t2 = st.columns(2)
    if t1.button("🏢 房租"): st.session_state.form_cat="房租"; st.session_state.form_note=f"{datetime.now().month}月房租"; st.rerun()
    if t2.button("👥 薪資"): st.session_state.form_cat="薪資"; st.session_state.form_note=f"{datetime.now().month}月薪資"; st.rerun()
    with st.form("add_t"):
        c1, c2, c3 = st.columns(3); d = c1.date_input("日期"); ty = c2.selectbox("類型",["支出","收入"]); ca = c3.selectbox("科目", cat_list, index=cat_list.index(st.session_state.get('form_cat')) if st.session_state.get('form_cat') in cat_list else 0)
        am = st.number_input("金額", min_value=0); pr = st.selectbox("歸屬", project_options); no = st.text_input("備註", value=st.session_state.get('form_note', ''))
        if st.form_submit_button("寫入雲端"): 
            ws_trans.append_row([str(d),ty,ca,am,no,pr,str(datetime.now())]); st.session_state.form_note=""; save_and_reload()

# --- Tab 3: 帳務總表 (精準刪除版) ---
with tab3:
    st.subheader("📋 帳務總表")
    if not df_trans.empty:
        c_m1, c_m2 = st.columns(2)
        m_view = c_m1.radio("📂 檢視模式", ["按月分組", "合併清單"], horizontal=True)
        m_sort = c_m2.selectbox("🔃 排序方式", ["日期(新→舊)", "日期(舊→新)", "金額(大→小)", "依科目", "依歸屬"])
        
        def apply_sort(df, opt):
            if opt == "金額(大→小)": return df.sort_values("amount", ascending=False)
            if opt == "依科目": return df.sort_values("category")
            if opt == "依歸屬": return df.sort_values("project_name")
            if opt == "日期(舊→新)": return df.sort_values("date", ascending=True)
            return df.sort_values("date", ascending=False)

        all_month_dfs = {}
        if m_view == "按月分組":
            df_trans['YM'] = df_trans['date'].dt.strftime('%Y-%m'); g = df_trans.groupby('YM')
            for m in sorted(g.groups.keys(), reverse=True):
                gdf = apply_sort(g.get_group(m), m_sort)
                all_month_dfs[m] = gdf
                mi, me = gdf[gdf['type']=='收入']['amount'].sum(), gdf[gdf['type']=='支出']['amount'].sum()
                with st.expander(f"📅 {m} | 🟢 +{fmt_num(mi)} | 🔴 -{fmt_num(me)}"):
                    st.data_editor(gdf, key=f"ed_{m}", num_rows="dynamic", use_container_width=True, 
                                   column_config={"date":st.column_config.DateColumn("日期"),"amount":st.column_config.NumberColumn("金額", format="$%d"),
                                   "type":st.column_config.SelectboxColumn("類型", options=["支出","收入"]),"category":st.column_config.SelectboxColumn("科目", options=cat_list),
                                   "project_name":st.column_config.SelectboxColumn("歸屬", options=project_options),"created_at":None,"_sheet_row":None,"YM":None}, hide_index=True)
        else:
            df_all = apply_sort(df_trans, m_sort)
            st.data_editor(df_all, key="ed_all", num_rows="dynamic", use_container_width=True, 
                           column_config={"date":st.column_config.DateColumn("日期"),"amount":st.column_config.NumberColumn("金額", format="$%d"),"created_at":None,"_sheet_row":None}, hide_index=True)
        
        if st.button("💾 儲存帳務變更"):
            try:
                head_t = ws_trans.row_values(1); col_map = {n: i+1 for i, n in enumerate(head_t)}
                rows_to_del = []
                for k in st.session_state:
                    if k.startswith("ed_"):
                        ch = st.session_state[k]
                        cur_df = df_all if k == "ed_all" else all_month_dfs[k.replace("ed_","")]
                        if ch.get("deleted_rows"):
                            for i in ch["deleted_rows"]: rows_to_del.append(int(cur_df.iloc[i]['_sheet_row']))
                        if ch.get("edited_rows"):
                            for i_s, d_ict in ch["edited_rows"].items():
                                idx = int(i_s); r_row = int(cur_df.iloc[idx]['_sheet_row'])
                                for cn, val in d_ict.items():
                                    if cn in col_map: ws_trans.update_cell(r_row, col_map[cn], str(val) if isinstance(val, (date, datetime)) else val)
                if rows_to_del:
                    for r in sorted(list(set(rows_to_del)), reverse=True): ws_trans.delete_rows(r)
                save_and_reload()
            except Exception as e: st.error(f"儲存失敗: {e}")

# --- Tab 4: 統計報表 ---
with tab4:
    if not df_trans.empty:
        t_mode = st.radio("統計範圍", ["單一月份", "年初至今 (YTD)", "全部資料"], horizontal=True)
        df_trans['Year'] = df_trans['date'].dt.year; df_trans['YM'] = df_trans['date'].dt.strftime('%Y-%m')
        if t_mode == "單一月份":
            sel = st.selectbox("選擇月份", sorted(df_trans['YM'].unique(), reverse=True)); df_f = df_trans[df_trans['YM']==sel]; title=sel
        elif t_mode == "年初至今 (YTD)":
            sel = st.selectbox("選擇年份", sorted(df_trans['Year'].unique(), reverse=True)); df_f = df_trans[(df_trans['Year']==sel) & (df_trans['date']<=pd.Timestamp(date.today()))]; title=f"{sel} YTD"
        else: df_f = df_trans; title="全部歷史"
        
        ti = df_f[df_f['type']=='收入']['amount'].sum(); te = df_f[df_f['type']=='支出']['amount'].sum()
        c1, c2, c3 = st.columns(3); c1.metric(f"{title} 總收入", fmt_num(ti)); c2.metric(f"{title} 總支出", fmt_num(te)); c3.metric(f"{title} 淨利", fmt_num(ti-te))
        ch1, ch2 = st.columns(2)
        with ch1: st.plotly_chart(px.bar(df_f.groupby(['category','type'])['amount'].sum().reset_index(), x='category', y='amount', color='type', barmode='group', color_discrete_map={'收入':'#00CC96','支出':'#EF553B'}, text_auto='.2s', title="科目統計"), use_container_width=True)
        with ch2: st.plotly_chart(px.bar(df_f.groupby(['project_name','type'])['amount'].sum().reset_index(), x='project_name', y='amount', color='type', barmode='group', color_discrete_map={'收入':'#00CC96','支出':'#EF553B'}, text_auto='.2s', title="歸屬統計"), use_container_width=True)
