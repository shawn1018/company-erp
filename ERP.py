import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

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
            # V21 新增 mid_date 欄位
            ws_projs.append_row(["name", "total_budget", "start_date", "status", "progress", "created_at", "end_date", "mid_date"])
        return ws_trans, ws_projs
    except: return None, None

st.set_page_config(page_title="雲端公司中控台", layout="wide", page_icon="🔸")
st.title("☁️ 公司營運中控台 (V21 里程碑甘特圖)")

sh = connect_google_sheet()
if not sh: st.stop()
ws_trans, ws_projs = init_sheets(sh)

# ==========================================
# 資料讀取
# ==========================================
raw_trans = ws_trans.get_all_values()
if len(raw_trans) > 1:
    df_trans = pd.DataFrame(raw_trans[1:], columns=raw_trans[0])
    df_trans['_sheet_row'] = range(2, len(df_trans) + 2)
else:
    df_trans = pd.DataFrame(columns=["date", "type", "category", "amount", "note", "project_name", "created_at", "_sheet_row"])

raw_projs = ws_projs.get_all_values()

# --- V21: 定義標準欄位 (新增 mid_date) ---
# 0:name, 1:budget, 2:start, 3:status, 4:progress, 5:created, 6:end, 7:mid
std_columns = ["name", "total_budget", "start_date", "status", "progress", "created_at", "end_date", "mid_date"]

if len(raw_projs) > 1:
    clean_data = []
    for row in raw_projs[1:]:
        while len(row) < 8: row.append("") # 補齊到 8 欄
        clean_data.append(row[:8])
    df_projs = pd.DataFrame(clean_data, columns=std_columns)
else:
    df_projs = pd.DataFrame(columns=std_columns)

# --- 資料型態轉換 ---
if not df_trans.empty:
    df_trans['amount'] = pd.to_numeric(df_trans['amount'], errors='coerce').fillna(0)
    df_trans['date'] = pd.to_datetime(df_trans['date'], errors='coerce')

if not df_projs.empty:
    df_projs['total_budget'] = pd.to_numeric(df_projs['total_budget'], errors='coerce').fillna(0)
    df_projs['progress'] = pd.to_numeric(df_projs['progress'], errors='coerce').fillna(0)
    df_projs['start_date'] = pd.to_datetime(df_projs['start_date'], errors='coerce')
    df_projs['end_date'] = pd.to_datetime(df_projs['end_date'], errors='coerce')
    df_projs['mid_date'] = pd.to_datetime(df_projs['mid_date'], errors='coerce') # 新增轉換

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

col1, col2, col3, col4 = st.columns(4)
col1.metric("📅 本月營收", f"${m_income:,.0f}")
col2.metric("💸 本月開銷", f"${m_expense:,.0f}")
col3.metric("💰 本月淨利", f"${m_balance:,.0f}")
col4.metric("🏦 總資金水位", f"${total_balance:,.0f}")
st.divider()

# ==========================================
# 全景圖 (核心功能)
# ==========================================
if not df_trans.empty or not df_projs.empty:
    
    df_chart_projs = df_projs.copy()
    
    # 圖表補洞邏輯
    def prepare_chart_dates(row):
        s = row['start_date']
        e = row['end_date']
        m = row['mid_date']
        if pd.isnull(s): s = datetime.today()
        if pd.isnull(e): e = s + timedelta(days=30)
        if s == e: e = s + timedelta(days=1)
        # 確保 mid 在 start 和 end 之間，否則忽略
        if pd.notnull(m) and not (s < m < e):
            m = pd.NaT 
        return s, e, m

    if not df_chart_projs.empty:
        df_chart_projs[['start_date', 'end_date', 'mid_date']] = df_chart_projs.apply(
            lambda x: pd.Series(prepare_chart_dates(x)), axis=1
        )

    # 計算全域時間
    all_dates = []
    if not df_trans.empty: all_dates.extend(df_trans['date'].dropna().tolist())
    if not df_chart_projs.empty: 
        all_dates.extend(df_chart_projs['start_date'].dropna().tolist())
        all_dates.extend(df_chart_projs['end_date'].dropna().tolist())
    
    if all_dates:
        min_date = min(all_dates).replace(day=1) 
        max_date_raw = max(all_dates)
        max_date = (max_date_raw + timedelta(days=40)).replace(day=1)
        full_date_range = pd.date_range(start=min_date, end=max_date, freq='MS')
    else:
        min_date = date.today()
        max_date = date.today() + timedelta(days=90)
        full_date_range = pd.date_range(start=min_date, end=max_date, freq='MS')

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, row_heights=[0.5, 0.5],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
        subplot_titles=("💰 財務收支與水位", "🗓 專案時程概況")
    )

    # 上圖：財務
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

    # 下圖：甘特圖 (V21 分段邏輯)
    if not df_chart_projs.empty:
        # 定義狀態顏色
        color_map = {"進行中": "#00CC96", "暫停": "#FFA15A", "結案": "#AB63FA"}
        
        df_p_sorted = df_chart_projs.sort_values("start_date")
        
        for i, row in df_p_sorted.iterrows():
            status_color = color_map.get(row['status'], "#888888")
            s = row['start_date']
            e = row['end_date']
            m = row['mid_date']
            
            s_str = s.strftime('%Y-%m-%d')
            e_str = e.strftime('%Y-%m-%d')
            m_str = m.strftime('%Y-%m-%d') if pd.notnull(m) else ""

            # 邏輯：如果有期中驗收，且時間合理，就切成兩段
            if pd.notnull(m) and s < m < e:
                # 第一段：開始 -> 驗收 (深色)
                fig.add_trace(go.Scatter(
                    x=[s, m], y=[row['name'], row['name']],
                    mode="lines+markers", 
                    line=dict(color=status_color, width=20),
                    marker=dict(symbol="line-ns", size=10, color="white"), # 端點修飾
                    name=row['name'], showlegend=False,
                    hovertemplate=f"<b>{row['name']} (前期)</b><br>區間: {s_str} ~ {m_str}<br>狀態: {row['status']}<extra></extra>"
                ), row=2, col=1)
                
                # 第二段：驗收 -> 結束 (淺色/半透明)
                fig.add_trace(go.Scatter(
                    x=[m, e], y=[row['name'], row['name']],
                    mode="lines", 
                    line=dict(color=status_color, width=20), # Plotly 線條透明度難設，這裡用同樣顏色代表延續，但在中間加標記
                    opacity=0.4, # 讓後半段變淡
                    name=row['name'], showlegend=False,
                    hovertemplate=f"<b>{row['name']} (後期)</b><br>區間: {m_str} ~ {e_str}<br>狀態: {row['status']}<extra></extra>"
                ), row=2, col=1)

                # 驗收點標記 (菱形)
                fig.add_trace(go.Scatter(
                    x=[m], y=[row['name']],
                    mode="markers",
                    marker=dict(symbol="diamond", size=12, color="gold", line=dict(width=1, color="black")),
                    name="期中驗收", showlegend=False,
                    hovertemplate=f"🔸 期中驗收點: {m_str}<extra></extra>"
                ), row=2, col=1)

            else:
                # 沒有驗收點，畫一條完整的
                fig.add_trace(go.Scatter(
                    x=[s, e], y=[row['name'], row['name']],
                    mode="lines", line=dict(color=status_color, width=20), name=row['name'], showlegend=False,
                    hovertemplate=f"<b>{row['name']}</b><br>狀態: {row['status']}<br>開始: {s_str}<br>結束: {e_str}<extra></extra>"
                ), row=2, col=1)

    fig.update_layout(height=700, barmode='group', legend=dict(orientation="h", y=1.1, x=0),
        yaxis=dict(title="單月收支", showgrid=True), yaxis2=dict(title="累計水位", showgrid=False, overlaying='y', side='right'),
        yaxis3=dict(title="專案列表", automargin=True)
    )
    fig.update_xaxes(
        range=[min_date, max_date], 
        tickformat="%Y-%m", dtick="M1", showgrid=True, gridwidth=1, gridcolor='rgba(211, 211, 211, 0.6)', griddash='dash', ticklabelmode="period"
    )
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("💡 請輸入記帳與專案資料")

st.divider()

# ==========================================
# 3. 功能分頁
# ==========================================
tab1, tab2, tab3 = st.tabs(["🏗 專案管理", "✍️ 雲端記帳", "📋 帳務總表"])

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
            # 選填的期中驗收
            p_mid = c5.date_input("🔸 期中驗收 (選填)", value=None)
            p_end = c6.date_input("預計結束", date.today() + timedelta(days=30))
            
            p_progress = st.slider("進度", 0, 100, 0)
            
            if st.form_submit_button("新增到雲端"):
                mid_str = str(p_mid) if p_mid else ""
                ws_projs.append_row([
                    p_name, p_budget, str(p_start), p_status, p_progress, str(datetime.now()), str(p_end), mid_str
                ])
                st.success("新增成功"); st.rerun()

    st.subheader("專案列表 (Excel 編輯模式)")
    if not df_projs.empty:
        edited_df = st.data_editor(
            df_projs,
            key="proj_editor", num_rows="dynamic", use_container_width=True,
            column_config={
                "name": "專案名稱", "total_budget": st.column_config.NumberColumn("預算", format="$%d"),
                "status": st.column_config.SelectboxColumn("狀態", options=["進行中", "結案", "暫停"]),
                "progress": st.column_config.ProgressColumn("進度", format="%d%%", min_value=0, max_value=100),
                "start_date": st.column_config.DateColumn("開始日期"), 
                "mid_date": st.column_config.DateColumn("🔸 期中驗收"), # 新增編輯欄位
                "end_date": st.column_config.DateColumn("結束日期"),
                "created_at": None 
            }, hide_index=True
        )

        if st.button("💾 儲存專案變更"):
            try:
                # 1. 確保 header 有 mid_date
                header_row = ws_projs.row_values(1)
                if "mid_date" not in header_row:
                    ws_projs.update_cell(1, len(header_row) + 1, "mid_date")
                    header_row.append("mid_date")

                changes = st.session_state["proj_editor"]
                deleted_indices = changes.get("deleted_rows", [])
                edited_cells = changes.get("edited_rows", {})

                if deleted_indices:
                    rows_to_delete = sorted([i + 2 for i in deleted_indices], reverse=True)
                    for r in rows_to_delete: ws_projs.delete_rows(r)
                
                if edited_cells:
                    col_map = {name: i+1 for i, name in enumerate(header_row)}
                    for idx, change_dict in edited_cells.items():
                        sheet_row = idx + 2
                        if idx in deleted_indices: continue
                        for col_name, new_val in change_dict.items():
                            if col_name in col_map:
                                if isinstance(new_val, (date, datetime, pd.Timestamp)):
                                    new_val = new_val.strftime('%Y-%m-%d')
                                ws_projs.update_cell(sheet_row, col_map[col_name], new_val)
                
                with st.spinner("同步中..."): time.sleep(1.5)
                st.success("更新成功"); st.rerun()
            except Exception as e: st.error(f"儲存失敗: {e}")

# --- Tab 2 & 3 (保持 V20 功能) ---
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
    st.subheader("📋 帳務總表 (按月分組)")
    if not df_trans.empty:
        df_trans['YearMonth'] = df_trans['date'].dt.strftime('%Y-%m')
        grouped = df_trans.groupby('YearMonth')
        sorted_months = sorted(list(grouped.groups.keys()), reverse=True)
        all_editors = {}
        for month in sorted_months:
            group_df = grouped.get_group(month).sort_values('date', ascending=False)
            m_inc = group_df[group_df['type']=='收入']['amount'].sum()
            m_exp = group_df[group_df['type']=='支出']['amount'].sum()
            with st.expander(f"📅 {month} (共{len(group_df)}筆) | 🟢 +${m_inc:,.0f} | 🔴 -${m_exp:,.0f}"):
                editor_key = f"editor_{month}"
                st.data_editor(
                    group_df, key=editor_key, num_rows="dynamic", use_container_width=True,
                    column_config={"date": st.column_config.DateColumn("日期"), "type": st.column_config.SelectboxColumn("類型", options=["支出", "收入"]), "category": st.column_config.SelectboxColumn("科目", options=["專案款", "薪資", "房租", "外包", "軟硬體", "雜支"]), "amount": st.column_config.NumberColumn("金額", format="$%d"), "project_name": "歸屬專案", "note": "備註", "created_at": None, "_sheet_row": None}, hide_index=True
                )
                all_editors[month] = group_df
        st.divider()
        if st.button("💾 儲存所有帳務變更", type="primary"):
            try:
                rows_to_delete = []
                updates_to_perform = []
                header_row_t = ws_trans.row_values(1)
                col_map_t = {name: i+1 for i, name in enumerate(header_row_t)}
                for month in sorted_months:
                    editor_key = f"editor_{month}"
                    changes = st.session_state.get(editor_key)
                    if not changes: continue
                    original_group_df = all_editors[month]
                    for rel_idx in changes.get("deleted_rows", []):
                        rows_to_delete.append(original_group_df.iloc[rel_idx]['_sheet_row'])
                    for rel_idx_str, change_dict in changes.get("edited_rows", {}).items():
                        rel_idx = int(rel_idx_str)
                        if rel_idx in changes.get("deleted_rows", []): continue
                        real_sheet_row = original_group_df.iloc[rel_idx]['_sheet_row']
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
                with st.spinner("同步中..."): time.sleep(1.5)
                st.rerun()
            except Exception as e: st.error(f"儲存失敗: {e}")
    else: st.info("無帳務資料")
