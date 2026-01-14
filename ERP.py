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
    # 1. Transactions
    raw_trans = _ws_trans.get_all_values()
    if len(raw_trans) > 1:
        df_trans = pd.DataFrame(raw_trans[1:], columns=raw_trans[0])
        df_trans['_sheet_row'] = range(2, len(df_trans) + 2)
    else:
        df_trans = pd.DataFrame(columns=["date", "type", "category", "amount", "note", "project_name", "created_at", "_sheet_row"])

    # 2. Projects
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

    # 3. Settings
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
    df_projs['total_budget'] = pd.to_numeric(df_projs['total_budget'], errors='coerce').fillna(0)
    df_projs['progress'] = pd.to_numeric(df_projs['progress'], errors='coerce').fillna(0)
    df_projs['start_date'] = pd.to_datetime(df_projs['start_date'], errors='coerce')
    df_projs['end_date'] = pd.to_datetime(df_projs['end_date'], errors='coerce')
    df_projs['mid_date'] = pd.to_datetime(df_projs['mid_date'], errors='coerce')
    df_projs['created_at'] = pd.to_datetime(df_projs['created_at'], errors='coerce')

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

st.set_page_config(page_title="雲端公司中控台", layout="wide", page_icon="💲")
st.title("☁️ 公司營運中控台 (V37 利潤比修正版)")

col1, col2, col3, col4 = st.columns(4)
col1.metric("📅 本月營收", fmt_num(m_income))
col2.metric("💸 本月開銷", fmt_num(m_expense))
col3.metric("💰 本月淨利", fmt_num(m_balance))
col4.metric("🏦 總資金水位", fmt_num(total_balance))
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
        df_chart = df_trans.copy()
        df_chart['PlotDate'] = df_chart['date'].apply(lambda x: x.replace(day=1))
        monthly_stats = df_chart.groupby(['PlotDate', 'type'])['amount'].sum().unstack(fill_value=0)
        monthly_stats = monthly_stats.reindex(full_date_range, fill_value=0)
        if '收入' not in monthly_stats.columns: monthly_stats['收入'] = 0
        if '支出' not in monthly_stats.columns: monthly_stats['支出'] = 0
        monthly_stats['Cumulative'] = (monthly_stats['收入'] - monthly_stats['支出']).cumsum()

        fig.add_trace(go.Bar(x=monthly_stats.index, y=monthly_stats['收入'], name='收入', marker_color='#00CC96', opacity=0.7), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Bar(x=monthly_stats.index, y=monthly_stats['支出'], name='支出', marker_color='#EF553B', opacity=0.7), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=monthly_stats.index, y=monthly_stats['Cumulative'], name='資金水位', mode='lines+markers', line=dict(color='#636EFA', width=3)), row=1, col=1, secondary_y=True)

    if not df_chart_projs.empty:
        color_map = {"進行中": "#00CC96", "暫停": "#FFA15A", "結案": "#AB63FA"}
        df_p_sorted = df_chart_projs.sort_values("start_date")
        for i, row in df_p_sorted.iterrows():
            status_color = color_map.get(row['status'], "#888888")
            s = row['start_date']; e = row['end_date']; m = row['mid_date']
            s_str = s.strftime('%Y-%m-%d'); e_str = e.strftime('%Y-%m-%d'); m_str = m.strftime('%Y-%m-%d') if pd.notnull(m) else ""

            proj_income_sum = 0
            if not df_trans.empty:
                proj_income_sum = df_trans[(df_trans['project_name'] == row['name']) & (df_trans['type'] == '收入')]['amount'].sum()
            
            income_label = f"💰{fmt_num(proj_income_sum)}" if proj_income_sum > 0 else ""
            budget_label = f"合約:{fmt_num(row['total_budget'])}" if row['total_budget'] > 0 else ""
            mid_time_point = s + (e - s) / 2

            if pd.notnull(m) and s < m < e:
                fig.add_trace(go.Scatter(x=[s, m], y=[row['name'], row['name']], mode="lines+markers", line=dict(color=status_color, width=20), marker=dict(symbol="line-ns", size=10, color="white"), name=row['name'], showlegend=False, hovertemplate=f"<b>{row['name']}</b><br>前期: {s_str}~{m_str}<extra></extra>"), row=2, col=1)
                fig.add_trace(go.Scatter(x=[m, e], y=[row['name'], row['name']], mode="lines", line=dict(color=status_color, width=20), opacity=0.4, name=row['name'], showlegend=False, hovertemplate=f"<b>{row['name']}</b><br>後期: {m_str}~{e_str}<extra></extra>"), row=2, col=1)
                fig.add_trace(go.Scatter(x=[m], y=[row['name']], mode="markers", marker=dict(symbol="diamond", size=12, color="gold", line=dict(width=1, color="black")), name="期中", showlegend=False, hovertemplate=f"🔸 期中驗收: {m_str}<extra></extra>"), row=2, col=1)
            else:
                fig.add_trace(go.Scatter(x=[s, e], y=[row['name'], row['name']], mode="lines", line=dict(color=status_color, width=20), name=row['name'], showlegend=False, hovertemplate=f"<b>{row['name']}</b><br>{s_str}~{e_str}<extra></extra>"), row=2, col=1)

            if income_label:
                fig.add_trace(go.Scatter(x=[mid_time_point], y=[row['name']], mode="text", text=[income_label], textposition="top center", textfont=dict(size=11, color="#006600"), showlegend=False, hoverinfo='skip'), row=2, col=1)
            if budget_label:
                fig.add_trace(go.Scatter(x=[e], y=[row['name']], mode="text", text=[budget_label], textposition="middle right", textfont=dict(size=11, color="#CC0000"), showlegend=False, hoverinfo='skip'), row=2, col=1)

    fig.update_layout(height=700, barmode='group', legend=dict(orientation="h", y=1.1, x=0), 
        yaxis=dict(title="單月收支", showgrid=True, gridcolor='lightgray', tickformat=".2s"), 
        yaxis2=dict(title="累計水位", overlaying='y', side='right', showgrid=False, zeroline=True, tickformat=".2s"), 
        yaxis3=dict(title="專案")
    )
    fig.update_xaxes(range=[min_date, max_date], tickformat="%Y-%m", dtick="M1", showgrid=True, gridwidth=1, gridcolor='rgba(211, 211, 211, 0.6)', griddash='dash', ticklabelmode="period")
    st.plotly_chart(fig, use_container_width=True)
else: st.info("💡 請輸入記帳與專案資料")

st.divider()

# ==========================================
# 3. 功能分頁
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🏗 專案管理", "✍️ 雲端記帳", "📋 帳務總表", "📊 統計報表"])

def save_and_reload():
    st.cache_data.clear()
    st.success("成功！資料已同步至雲端。")
    time.sleep(1)
    st.rerun()

# --- Tab 1: 專案管理 ---
with tab1: 
    with st.expander("➕ 新增專案 (含驗收日)"):
        with st.form("add_proj"):
            c1, c2, c3 = st.columns(3)
            p_name = c1.text_input("專案名稱")
            p_budget = c2.number_input("預算", min_value=0)
            p_status = c3.selectbox("狀態", ["進行中", "結案", "暫停"])
            c4, c5, c6 = st.columns(3)
            p_start = c4.date_input("開始日期", date.today())
            p_mid = c5.date_input("🔸 期中驗收 (選填)", value=None)
            p_end = c6.date_input("預計結束", date.today() + timedelta(days=30))
            p_progress = st.slider("進度", 0, 100, 0)
            if st.form_submit_button("新增"):
                mid_str = str(p_mid) if p_mid else ""
                ws_projs.append_row([p_name, p_budget, str(p_start), p_status, p_progress, str(datetime.now()), str(p_end), mid_str])
                save_and_reload()

    st.subheader("專案列表 (Excel 編輯模式)")
    if not df_projs.empty:
        sort_col, spacer = st.columns([1, 2])
        sort_opt = sort_col.selectbox("🔃 排序方式", ["依建立日期 (預設)", "依金額 (大→小)", "依狀態", "依專案名稱"], index=0)
        
        if sort_opt == "依金額 (大→小)": df_display = df_projs.sort_values("total_budget", ascending=False)
        elif sort_opt == "依狀態": df_display = df_projs.sort_values("status")
        elif sort_opt == "依專案名稱": df_display = df_projs.sort_values("name")
        else: df_display = df_projs.sort_values("created_at", ascending=False)

        # 計算實收與利潤比 (只顯示)
        if not df_trans.empty:
            expenses = df_trans[df_trans['type'] == '支出']
            proj_costs = expenses.groupby('project_name')['amount'].sum()
            df_display['cost_sum'] = df_display['name'].map(proj_costs).fillna(0)
        else:
            df_display['cost_sum'] = 0

        df_display['real_income'] = (df_display['total_budget'] * 0.95) - df_display['cost_sum']
        
        # 計算利潤比 (乘100)
        df_display['profit_margin'] = df_display.apply(
            lambda x: (x['real_income'] / x['total_budget'] * 100) if x['total_budget'] > 0 else 0, 
            axis=1
        )

        cols = ['name', 'total_budget', 'real_income', 'profit_margin', 'status', 'progress', 'start_date', 'mid_date', 'end_date', 'created_at', '_sheet_row']
        existing_cols = [c for c in cols if c in df_display.columns]
        df_display = df_display[existing_cols]

        edited_df = st.data_editor(
            df_display, key="proj_editor", num_rows="dynamic", use_container_width=True,
            column_config={
                "name": "專案名稱", 
                "total_budget": st.column_config.NumberColumn("預算", format="$%d"),
                "real_income": st.column_config.NumberColumn("實收(含稅扣除)", format="$%d", disabled=True),
                # 【修正】範圍改為 0-100
                "profit_margin": st.column_config.ProgressColumn("利潤比", format="%.1f%%", min_value=0, max_value=100),
                
                "status": st.column_config.SelectboxColumn("狀態", options=["進行中", "結案", "暫停"]),
                "progress": st.column_config.ProgressColumn("進度", format="%d%%", min_value=0, max_value=100),
                "start_date": st.column_config.DateColumn("開始日期"), "mid_date": st.column_config.DateColumn("🔸 期中驗收"), "end_date": st.column_config.DateColumn("結束日期"),
                "created_at": None, "_sheet_row": None, "cost_sum": None 
            }, hide_index=True
        )
        if st.button("💾 儲存專案變更"):
            try:
                header_row = ws_projs.row_values(1)
                if "mid_date" not in header_row: ws_projs.update_cell(1, len(header_row)+1, "mid_date"); header_row.append("mid_date")
                changes = st.session_state["proj_editor"]
                if changes.get("deleted_rows"):
                    rows_to_del = [df_display.iloc[idx]['_sheet_row'] for idx in changes["deleted_rows"]]
                    for r in sorted(rows_to_del, reverse=True): ws_projs.delete_rows(r)
                if changes.get("edited_rows"):
                    col_map = {name: i+1 for i, name in enumerate(header_row)}
                    trans_header = ws_trans.row_values(1)
                    try: trans_proj_col = trans_header.index("project_name") + 1
                    except: trans_proj_col = -1
                    for idx_str, change_dict in changes["edited_rows"].items():
                        idx = int(idx_str)
                        if idx in changes.get("deleted_rows", []): continue
                        real_sheet_row = df_display.iloc[idx]['_sheet_row']
                        if "name" in change_dict and trans_proj_col != -1:
                            new_name = change_dict["name"]
                            old_name = df_display.iloc[idx]['name']
                            if old_name != new_name and not pd.isna(old_name):
                                trans_proj_list = ws_trans.col_values(trans_proj_col)
                                for r_idx, p_name in enumerate(trans_proj_list):
                                    if p_name == old_name:
                                        ws_trans.update_cell(r_idx + 1, trans_proj_col, new_name)
                                st.toast(f"同步更新: {old_name} -> {new_name}")
                        for col_name, val in change_dict.items():
                            if col_name in col_map:
                                if isinstance(val, (date, datetime, pd.Timestamp)): val = val.strftime('%Y-%m-%d')
                                ws_projs.update_cell(real_sheet_row, col_map[col_name], val)
                save_and_reload()
            except Exception as e: st.error(f"儲存失敗: {e}")

# --- Tab 2: 記帳 (含設定) ---
with tab2:
    with st.expander("⚙️ 設定：管理【科目】與【固定歸屬】"):
        set_c1, set_c2 = st.columns(2)
        with set_c1:
            st.markdown("##### 📂 科目管理")
            st.code("  ".join(cat_list), language=None)
            c_add, c_del = st.columns(2)
            new_cat = c_add.text_input("新增科目名稱")
            if c_add.button("➕ 新增科目"):
                if new_cat and new_cat not in cat_list:
                    full_sheet = ws_settings.get_all_values()
                    target_row = len(full_sheet) + 1
                    for i, row in enumerate(full_sheet):
                        if i == 0: continue
                        if len(row) < 1 or row[0].strip() == "": target_row = i + 1; break
                    ws_settings.update_cell(target_row, 1, new_cat)
                    save_and_reload()
            
            del_cat = c_del.selectbox("刪除科目", ["(選取)"] + cat_list)
            if c_del.button("🗑 刪除科目"):
                if del_cat != "(選取)":
                    cell = ws_settings.find(del_cat)
                    ws_settings.update_cell(cell.row, 1, "")
                    save_and_reload()

        with set_c2:
            st.markdown("##### 🏢 固定歸屬管理")
            st.code("  ".join(attr_list), language=None)
            a_add, a_del = st.columns(2)
            new_attr = a_add.text_input("新增歸屬名稱")
            if a_add.button("➕ 新增歸屬"):
                if new_attr and new_attr not in attr_list:
                    full_sheet = ws_settings.get_all_values()
                    target_row = len(full_sheet) + 1
                    for i, row in enumerate(full_sheet):
                        if i == 0: continue
                        if len(row) < 2 or row[1].strip() == "": target_row = i + 1; break
                    ws_settings.update_cell(target_row, 2, new_attr)
                    save_and_reload()
            del_attr = a_del.selectbox("刪除歸屬", ["(選取)"] + attr_list)
            if a_del.button("🗑 刪除歸屬"):
                if del_attr != "(選取)":
                    cell = ws_settings.find(del_attr)
                    ws_settings.update_cell(cell.row, 2, "")
                    save_and_reload()

    st.divider()

    if 'form_type' not in st.session_state: st.session_state.form_type = "支出"
    if 'form_cat' not in st.session_state: st.session_state.form_cat = cat_list[0] if cat_list else ""
    if 'form_note' not in st.session_state: st.session_state.form_note = ""
    
    st.write("⚡️ **常用快速樣板**")
    t1, t2, t3 = st.columns(3)
    if t1.button("🏢 房租"): st.session_state.form_type="支出"; st.session_state.form_cat="房租" if "房租" in cat_list else cat_list[0]; st.session_state.form_note=f"{datetime.now().month}月房租"; st.rerun()
    if t2.button("👥 薪資"): st.session_state.form_type="支出"; st.session_state.form_cat="薪資" if "薪資" in cat_list else cat_list[0]; st.session_state.form_note=f"{datetime.now().month}月薪資"; st.rerun()
    if t3.button("🔄 重置"): st.session_state.form_type="支出"; st.session_state.form_cat=cat_list[0] if cat_list else ""; st.session_state.form_note=""; st.rerun()
    st.divider()
    
    with st.form("add_t"):
        c1, c2, c3 = st.columns(3)
        d = c1.date_input("日期")
        ty = c2.selectbox("類型", ["支出", "收入"], index=["支出", "收入"].index(st.session_state.form_type))
        ca = c3.selectbox("科目", cat_list, index=cat_list.index(st.session_state.form_cat) if st.session_state.form_cat in cat_list else 0)
        c4, c5 = st.columns(2)
        am = c4.number_input("金額", min_value=0)
        pr = c5.selectbox("歸屬", project_options) 
        no = st.text_input("備註", value=st.session_state.form_note)
        if st.form_submit_button("寫入雲端"): 
            ws_trans.append_row([str(d), ty, ca, am, no, pr, str(datetime.now())])
            st.session_state.form_note=""
            save_and_reload()

# --- Tab 3: 報表修改 ---
with tab3:
    st.subheader("📋 帳務總表 (可排序/分組)")
    if not df_trans.empty:
        sort_col_t, sort_sub_col = st.columns([1, 1])
        sort_opt_t = sort_col_t.selectbox("📂 檢視模式", ["按月分組 (預設)", "全部清單模式"], index=0)
        
        if sort_opt_t == "按月分組 (預設)":
            sub_sort_opt = sort_sub_col.selectbox("🔃 分組內排序", ["日期 (新→舊)", "日期 (舊→新)", "金額 (大→小)", "金額 (小→大)", "依歸屬", "依科目"])
            
            df_trans['YearMonth'] = df_trans['date'].dt.strftime('%Y-%m')
            grouped = df_trans.groupby('YearMonth')
            sorted_months = sorted(list(grouped.groups.keys()), reverse=True)
            all_editors = {}
            for month in sorted_months:
                group_df = grouped.get_group(month)
                if sub_sort_opt == "日期 (新→舊)": group_df = group_df.sort_values('date', ascending=False)
                elif sub_sort_opt == "日期 (舊→新)": group_df = group_df.sort_values('date', ascending=True)
                elif sub_sort_opt == "金額 (大→小)": group_df = group_df.sort_values('amount', ascending=False)
                elif sub_sort_opt == "金額 (小→大)": group_df = group_df.sort_values('amount', ascending=True)
                elif sub_sort_opt == "依歸屬": group_df = group_df.sort_values('project_name')
                elif sub_sort_opt == "依科目": group_df = group_df.sort_values('category')
                
                m_inc = group_df[group_df['type']=='收入']['amount'].sum()
                m_exp = group_df[group_df['type']=='支出']['amount'].sum()
                
                with st.expander(f"📅 {month} (共{len(group_df)}筆) | 🟢 +{fmt_num(m_inc)} | 🔴 -{fmt_num(m_exp)}"):
                    editor_key = f"editor_{month}"
                    st.data_editor(
                        group_df, key=editor_key, num_rows="dynamic", use_container_width=True,
                        column_config={
                            "date": st.column_config.DateColumn("日期"), 
                            "type": st.column_config.SelectboxColumn("類型", options=["支出", "收入"]), 
                            "category": st.column_config.SelectboxColumn("科目", options=cat_list), 
                            "amount": st.column_config.NumberColumn("金額", format="$%d"), 
                            "project_name": st.column_config.SelectboxColumn("歸屬專案", options=project_options), 
                            "note": "備註", "created_at": None, "_sheet_row": None, "YearMonth": None
                        }, hide_index=True
                    )
                    all_editors[month] = group_df
        else:
            sub_sort_opt = sort_sub_col.selectbox("🔃 清單排序", ["日期 (新→舊)", "金額 (大→小)", "依歸屬", "依科目"])
            if sub_sort_opt == "金額 (大→小)": df_display_t = df_trans.sort_values("amount", ascending=False)
            elif sub_sort_opt == "依歸屬": df_display_t = df_trans.sort_values("project_name")
            elif sub_sort_opt == "依科目": df_display_t = df_trans.sort_values("category")
            else: df_display_t = df_trans.sort_values("date", ascending=False)
                
            st.data_editor(
                df_display_t, key="editor_all", num_rows="dynamic", use_container_width=True,
                column_config={
                    "date": st.column_config.DateColumn("日期"), 
                    "type": st.column_config.SelectboxColumn("類型", options=["支出", "收入"]), 
                    "category": st.column_config.SelectboxColumn("科目", options=cat_list), 
                    "amount": st.column_config.NumberColumn("金額", format="$%d"), 
                    "project_name": st.column_config.SelectboxColumn("歸屬專案", options=project_options), 
                    "note": "備註", "created_at": None, "_sheet_row": None
                }, hide_index=True
            )
            all_editors = {"all": df_display_t}

        st.divider()
        if st.button("💾 儲存所有帳務變更", type="primary"):
            try:
                rows_to_delete = []
                updates_to_perform = []
                header_row_t = ws_trans.row_values(1)
                col_map_t = {name: i+1 for i, name in enumerate(header_row_t)}
                for key in st.session_state:
                    if key.startswith("editor_"):
                        changes = st.session_state[key]
                        if sort_opt_t.startswith("按月分組"):
                            month_key = key.replace("editor_", "")
                            if month_key not in all_editors: continue
                            original_df = all_editors[month_key]
                        else:
                            original_df = all_editors["all"]

                        for rel_idx in changes.get("deleted_rows", []):
                            rows_to_delete.append(original_df.iloc[rel_idx]['_sheet_row'])
                        for rel_idx_str, change_dict in changes.get("edited_rows", {}).items():
                            rel_idx = int(rel_idx_str)
                            if rel_idx in changes.get("deleted_rows", []): continue
                            real_sheet_row = original_df.iloc[rel_idx]['_sheet_row']
                            for col_name, new_val in change_dict.items():
                                if col_name in col_map_t:
                                    if isinstance(new_val, (date, datetime, pd.Timestamp)): new_val = new_val.strftime('%Y-%m-%d')
                                    updates_to_perform.append((real_sheet_row, col_map_t[col_name], new_val))
                if rows_to_delete:
                    for r in sorted(list(set(rows_to_delete)), reverse=True): ws_trans.delete_rows(r)
                    st.warning("已執行刪除")
                elif updates_to_perform:
                    for row, col, val in updates_to_perform: ws_trans.update_cell(row, col, val)
                    st.success("修改已儲存")
                save_and_reload()
            except Exception as e: st.error(f"儲存失敗: {e}")
    else: st.info("無帳務資料")

# --- Tab 4: 統計報表 ---
with tab4:
    st.subheader("📊 統計分析報表")
    if not df_trans.empty:
        with st.expander("🔎 篩選條件 (預設全選)", expanded=True):
            f1, f2 = st.columns(2)
            all_cats_in_data = df_trans['category'].unique().tolist()
            all_projs_in_data = df_trans['project_name'].unique().tolist()
            sel_cats = f1.multiselect("選擇科目", all_cats_in_data, default=all_cats_in_data)
            sel_projs = f2.multiselect("選擇歸屬", all_projs_in_data, default=all_projs_in_data)
        
        mask = df_trans['category'].isin(sel_cats) & df_trans['project_name'].isin(sel_projs)
        df_stat = df_trans[mask]
        
        if not df_stat.empty:
            st.divider()
            chart1, chart2 = st.columns(2)
            with chart1:
                st.markdown("##### 📂 科目收支統計")
                df_cat_group = df_stat.groupby(['category', 'type'])['amount'].sum().reset_index()
                fig_cat = px.bar(df_cat_group, x='category', y='amount', color='type', barmode='group', color_discrete_map={'收入':'#00CC96', '支出':'#EF553B'}, text_auto='.2s', labels={'category': '科目', 'amount': '金額', 'type': '類型'})
                st.plotly_chart(fig_cat, use_container_width=True)

            with chart2:
                st.markdown("##### 🏢 歸屬收支統計 (分收入/支出)")
                df_proj_group = df_stat.groupby(['project_name', 'type'])['amount'].sum().reset_index()
                fig_proj = px.bar(df_proj_group, x='project_name', y='amount', color='type', barmode='group', color_discrete_map={'收入':'#00CC96', '支出':'#EF553B'}, text_auto='.2s', labels={'project_name': '歸屬', 'amount': '金額', 'type': '類型'})
                st.plotly_chart(fig_proj, use_container_width=True)
            
            st.divider()
            with st.expander("📋 查看詳細篩選資料"):
                st.dataframe(df_stat[['date', 'type', 'category', 'amount', 'project_name', 'note']].sort_values('date', ascending=False), use_container_width=True)
        else: st.warning("⚠️ 篩選條件下無資料")
    else: st.info("尚無帳務資料可供統計")
