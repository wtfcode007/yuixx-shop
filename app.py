import streamlit as st
import pandas as pd
import time
from datetime import datetime
from streamlit_option_menu import option_menu
from streamlit_gsheets import GSheetsConnection
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import requests
import base64


# ==========================================
# ⚙️ 1. Settings & Config
# ==========================================
st.set_page_config(
    page_title="yuixx Shop",
    page_icon="🧸", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# ☁️ 2. ฟังก์ชันอัปโหลดรูปไปที่ ImgBB (มาแทน Google Drive)
# ==========================================

def upload_to_imgbb(file_buffer):
    # ✅ เอาอันนี้ไปวางแทน แล้วใส่รหัสของคุณลงไปในเครื่องหมายคำพูดตรงๆ เลยครับ!
    API_KEY = st.secrets["IMGBB_API_KEY"]
    url = "https://api.imgbb.com/1/upload"
    
    try:
        # แปลงไฟล์ภาพเป็น Base64
        image_bytes = file_buffer.getvalue()
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
        payload = {
            "key": API_KEY,
            "image": image_b64
        }
        
        # ยิง API ไปที่ ImgBB
        response = requests.post(url, data=payload)
        result = response.json()
        
        if result.get("success"):
            # คืนค่าเป็น Direct Link สำหรับแสดงผลรูปภาพทันที
            return result["data"]["url"]
        else:
            st.error(f"ImgBB Error: {result.get('error', {}).get('message')}")
            return None
            
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการอัปโหลดรูป: {e}")
        return None
    
# 2.3 ฟังก์ชันโหลดข้อมูลจาก Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)

# แก้ไขฟังก์ชัน load_all_sheets ใหม่ดังนี้ครับ
def load_all_sheets():
    # ใช้ URL ที่คลีนแล้ว (ไม่มี ?usp=sharing)
    URL = "https://docs.google.com/spreadsheets/d/1Fr8ZE9JZIB39u5HRURZd9hMlZRpeu36SXUHNBCmttZM"
    
    try:
        # 1. อ่าน Active_Orders
        try:
            active = conn.read(spreadsheet=URL, worksheet="Active_Orders", ttl=600)
        except:
            active = pd.DataFrame(columns=['order_id', 'customer_name', 'details', 'price', 'deposit', 'status', 'tracking_no', 'order_date', 'image_path', 'completed_image_path'])
        
        # 2. อ่าน Order_History
        try:
            history = conn.read(spreadsheet=URL, worksheet="Order_History", ttl=600)
        except:
            history = pd.DataFrame(columns=['order_id', 'customer_name', 'details', 'price', 'order_date', 'finish_date', 'completed_image_path', 'tracking_no'])
            
        # 3. อ่าน Customers
        try:
            customers = conn.read(spreadsheet=URL, worksheet="Customers", ttl=600)
        except:
            customers = pd.DataFrame(columns=['customer_name', 'contact', 'total_orders', 'last_order_date'])

        # ลบช่องว่างส่วนเกินในชื่อคอลัมน์ (ป้องกัน Bug)
        for df in [active, history, customers]:
            df.columns = df.columns.str.strip()

        return active, history, customers

    except Exception as e:
        st.error(f"❌ ไม่สามารถเข้าถึง Google Sheets ได้: {e}")
        st.info("ตรวจสอบว่า: 1. ลิงก์ถูกต้อง 2. แชร์สิทธิ์ให้ Email Service Account เป็น Editor หรือยัง")
        st.stop()

def save_all_sheets(active_df, history_df, customers_df):
    # ต้องใช้ลิงก์ที่คลีนแล้วเหมือนตอนโหลดครับ
    URL = "https://docs.google.com/spreadsheets/d/1Fr8ZE9JZIB39u5HRURZd9hMlZRpeu36SXUHNBCmttZM"
    
    try:
        # บังคับระบุลิงก์ลงไปในคำสั่ง update ด้วย
        conn.update(spreadsheet=URL, worksheet="Active_Orders", data=active_df)
        conn.update(spreadsheet=URL, worksheet="Order_History", data=history_df)
        conn.update(spreadsheet=URL, worksheet="Customers", data=customers_df)
        
        # หลังจากบันทึกเสร็จ สั่งเคลียร์แคช 1 รอบ เพื่อให้ตอนดึงข้อมูลครั้งต่อไปได้ข้อมูลใหม่ล่าสุดเสมอ
        st.cache_data.clear() 
        
        return True # ส่งค่ากลับไปบอกว่าบันทึกสำเร็จ
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดตอนบันทึกลง Google Sheets: {e}")
        return False
def update_customer_db(name, contact=""):
    global df_customers
    existing_names = df_customers['customer_name'].astype(str).values
    if str(name) in existing_names:
        idx = df_customers.index[df_customers['customer_name'].astype(str) == str(name)][0]
        df_customers.at[idx, 'total_orders'] += 1
        df_customers.at[idx, 'last_order_date'] = datetime.now().strftime("%Y-%m-%d")
    else:
        new_cust = pd.DataFrame([{
            'customer_name': str(name), 
            'contact': str(contact), 
            'total_orders': 1, 
            'last_order_date': datetime.now().strftime("%Y-%m-%d")
        }])
        df_customers = pd.concat([df_customers, new_cust], ignore_index=True)

# โหลดข้อมูลเข้าสู่ระบบ
df_active, df_history, df_customers = load_all_sheets()

# ==========================================
# 🔍 3. ฟังก์ชันสำหรับหน้าเช็คสถานะคิว
# ==========================================
def render_order_card(row, is_history=False):
    with st.container(border=True):
        # 🖼️ 1. ส่วนรูปภาพ (ดึงจาก Google Drive URL)
        comp_img = str(row.get('completed_image_path', ''))
        ref_img = str(row.get('image_path', '')) if not is_history else ""
        
        # เช็คว่ามี URL (ขึ้นต้นด้วย http) หรือไม่
        if (is_history or row['status'] in ["รอแพ็คส่ง", "จัดส่งแล้ว"]) and comp_img.startswith("http"):
            st.image(comp_img, use_container_width=True) 
            st.success("🎉 ผลงานเสร็จแล้ว!", icon="✅")
        elif ref_img.startswith("http"):
            st.image(ref_img, use_container_width=True) 
            st.caption("📷 ภาพ Reference")
        else:
            st.image("https://via.placeholder.com/300x300.png?text=No+Image", use_container_width=True) 
            
        st.divider() 
        
        # 📝 2. ส่วนข้อมูล
        st.markdown(f"**🧸 คุณ: {row['customer_name']}**")
        
        if is_history:
            st.markdown("**สถานะ:** 🟢 จบงานแล้ว")
            st.caption(f"วันที่ส่ง: {row['finish_date']}")
        else:
            status_color = "🔵"
            if row['status'] == "กำลังเย็บ": status_color = "🟡"
            elif row['status'] == "รอแพ็คส่ง": status_color = "🟠"
            elif row['status'] == "จัดส่งแล้ว": status_color = "🟢"
            st.markdown(f"**สถานะ:** {status_color} {row['status']}")
            
        tracking = row.get('tracking_no', '-')
        if tracking != "-" and pd.notna(tracking) and str(tracking).strip() != "":
            st.markdown(f"**📦 พัสดุ:** `{tracking}`")
            
        st.caption(f"รายละเอียด: {row['details']}")
        st.markdown(f"**วันที่สั่ง:** {row['order_date']}")

def show_customer_tracking_page(df_active, df_history):
    check_bg_url = "https://i.pinimg.com/originals/72/0c/c4/720cc43d757ee638ad5054a05220fafe.gif"
    st.markdown(f"""
        <div style="
            background-image: url('{check_bg_url}');
            background-size: cover;
            background-position: center; 
            height: 200px; 
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 30px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.15);
        ">
            <h1 style="color: white; text-shadow: 2px 2px 8px rgba(0,0,0,0.9); margin: 0; font-size: 3rem; text-align: center;">
                ⋆°✿˖° สถานะตุ๊กตา₊‧.°
            </h1>
        </div>
    """, unsafe_allow_html=True)
    
    st.caption("✨ พิมพ์ชื่อลูกค้าเพื่อตรวจสอบสถานะงานและดูผลงานที่เสร็จแล้ว")
    st.divider()

    if df_active.empty and df_history.empty:
        st.info("ยังไม่มีออเดอร์ในระบบ")
    else:
        search_name = st.text_input("พิมพ์ชื่อของคุณเพื่อค้นหา 🔎", "")
        st.write("") 
        
        if search_name:
            show_active = df_active[df_active['customer_name'].astype(str).str.contains(search_name, case=False, na=False)]
            show_history = df_history[df_history['customer_name'].astype(str).str.contains(search_name, case=False, na=False)]
            
            if show_active.empty and show_history.empty:
                st.warning("ไม่พบชื่อลูกค้านี้ในระบบ(¯▽¯;) ลองพิมพ์ชื่อใหม่อีกครั้งให้ตรงกับตอนที่สั่งทำนะคะ")
            else:
                if not show_active.empty:
                    st.subheader("🧸 ออเดอร์ที่กำลังดำเนินการ")
                    cols = st.columns(3) 
                    for i, (idx, row) in enumerate(show_active.iterrows()):
                        with cols[i % 3]:
                            render_order_card(row, is_history=False)
                
                if not show_history.empty:
                    st.divider()
                    st.subheader("📜 ประวัติงานที่จัดส่งเรียบร้อยแล้ว")
                    cols_hist = st.columns(3) 
                    for i, (idx, row) in enumerate(show_history.iterrows()):
                        with cols_hist[i % 3]:
                            render_order_card(row, is_history=True)
        else:
            st.info("💡 กรุณาพิมพ์ชื่อของคุณในช่องค้นหา เพื่อดูสถานะออเดอร์")

# ==========================================
# 🔐 4. Security & Role Assignment
# ==========================================
SECRET_PASSWORD = st.secrets["ADMIN_PASSWORD"] 

if "user_role" not in st.session_state:
    st.session_state.user_role = None

if st.session_state.user_role is None:
    bg_gif_url = "https://i.pinimg.com/originals/3a/a4/6f/3aa46f5701fc6ed92234ea0a9f86e2cd.gif" 
    st.markdown(f"""
        <div style="
            background-image: url('{bg_gif_url}');
            background-size: cover;
            background-position: bottom;
            height: 500px;
            padding: 20px;
            border-radius: 20px;
            text-align: center;
            margin-bottom: 30px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.15);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        ">
            <div><h1 style="color: white; text-shadow: 2px 2px 8px rgba(0,0,0,0.9); margin: 10px; font-size: 3.5rem;">
                    YUIXX SHOP
                </h1>
                <p style="color: white; text-shadow: 1px 1px 5px rgba(0,0,0,0.9); font-size: 1.2rem; margin-top: 10px;">
                    ʕ·͡ᴥ·ʔ
                </p>
            </div>
            <div></div>
        </div>
    """, unsafe_allow_html=True)
    
    col_cust, col_admin = st.columns(2)
    with col_cust:
        st.subheader("👤 สำหรับลูกค้า")
        st.caption("เช็คสถานะออเดอร์และดูรูปผลงานตุ๊กตา")
        if st.button("🔍 เข้าสู่ระบบลูกค้า (เช็คสถานะ)", use_container_width=True):
            st.session_state.user_role = "customer"
            st.rerun()
            
    with col_admin:
        st.subheader("🔐 สำหรับเจ้าของร้าน")
        st.caption("")
        with st.form("login_form"):
            pwd_input = st.text_input("รหัสผ่าน", type="password")
            submit_login = st.form_submit_button("เข้าสู่ระบบ", use_container_width=True)
            if submit_login:
                if pwd_input == SECRET_PASSWORD:
                    st.session_state.user_role = "admin"
                    st.rerun()
                else:
                    st.error("รหัสผ่านไม่ถูกต้อง!")
    st.stop()

# ==========================================
# 🚀 5. โหมดการแสดงผล (Customer / Admin)
# ==========================================

if st.session_state.user_role == "customer":
    col_title, col_back = st.columns([4, 1])
    with col_back:
        st.write("")
        if st.button("🚪 กลับหน้าหลัก", use_container_width=True):
            st.session_state.user_role = None
            st.rerun()
    show_customer_tracking_page(df_active, df_history)

elif st.session_state.user_role == "admin":
    with st.sidebar:
        st.image("https://i.pinimg.com/736x/26/ba/9a/26ba9a1712150ffa630057bece050bc2.jpg", width=250)
        st.title("yuixx Shop")
        st.caption("ระบบจัดการหลังบ้าน (Google Cloud)")
        st.divider()
        
        menu = option_menu(
            menu_title="เมนูหลัก",
            options=["Dashboard", "เปิดบิลรับออเดอร์", "จัดการคิว & ส่งของ", "ประวัติงานที่ส่งแล้ว", "ฐานข้อมูลลูกค้า", "เช็คสถานะคิว"], 
            icons=["bar-chart-line", "plus-circle", "scissors", "clock-history", "people", "search"], 
            menu_icon="cast", 
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"color": "#FF9800", "font-size": "18px"},
                "nav-link": {"font-size": "16px", "text-align": "left", "margin":"5px 0px", "--hover-color": "#F0F2F6", "border-radius": "10px"},
                "nav-link-selected": {"background-color": "#1E88E5", "color": "white"},
            }
        )
        st.divider()
        if st.button("🚪 ออกจากระบบหลังบ้าน", use_container_width=True):
            st.session_state.user_role = None
            st.rerun()

    # --- 📊 Dashboard ---
    if menu == "Dashboard":
        dashboard_bg_url = "https://i.pinimg.com/originals/72/0c/c4/720cc43d757ee638ad5054a05220fafe.gif"
        st.markdown(f"""
            <div style="background-image: url('{dashboard_bg_url}'); background-size: cover; background-position: center; height: 350px; border-radius: 20px; display: flex; align-items: center; justify-content: center; margin-bottom: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.15);">
                <h1 style="color: white; text-shadow: 2px 2px 8px rgba(0,0,0,0.9); margin: 0; font-size: 2rem;">ภาพรวมร้านค้า (Dashboard)</h1>
            </div>
        """, unsafe_allow_html=True)
        
        active_revenue = pd.to_numeric(df_active['price'], errors='coerce').sum() if not df_active.empty else 0
        history_revenue = pd.to_numeric(df_history['price'], errors='coerce').sum() if not df_history.empty else 0
        total_revenue = active_revenue + history_revenue
        
        active_deposit = pd.to_numeric(df_active['deposit'], errors='coerce').sum() if not df_active.empty else 0
        total_deposit = active_deposit + history_revenue 
        pending_payment = total_revenue - total_deposit
        
        queue_count = len(df_active[df_active['status'] == 'รอคิว']) if not df_active.empty else 0
        sewing_count = len(df_active[df_active['status'] == 'กำลังเย็บ']) if not df_active.empty else 0
        shipping_count = len(df_active[df_active['status'] == 'รอแพ็คส่ง']) if not df_active.empty else 0
        
        st.subheader("💰 สรุปยอดเงินรวมทั้งหมด (รวมงานที่จบแล้ว)")
        c1, c2, c3 = st.columns(3)
        c1.markdown('### <img src="https://media.tenor.com/mE2KPcal6n8AAAAi/usagi-chiikawa.gif" width="60"> ยอดขายรวม', unsafe_allow_html=True)
        c1.metric("", f"฿{total_revenue:,.2f}")
        c2.markdown('### <img src="https://media1.tenor.com/m/EVE6hzdblvIAAAAC/usagi.gif" width="60"> รับเงินแล้ว', unsafe_allow_html=True)
        c2.metric("", f"฿{total_deposit:,.2f}")
        
        unpaid_df = df_active[pd.to_numeric(df_active['price'], errors='coerce') > pd.to_numeric(df_active['deposit'], errors='coerce')] if not df_active.empty else pd.DataFrame()
        hover_text = "ไม่มีลูกค้าค้างชำระ" if unpaid_df.empty else "มีลูกค้าค้างชำระ"
        c3.markdown('### <img src="https://media1.tenor.com/m/QZ88j5EkPfgAAAAC/usagi-usagi-tummy.gif" width="60"> ยอดค้างชำระ', unsafe_allow_html=True)
        c3.metric("", f"฿{pending_payment:,.2f}", delta_color="inverse", help=hover_text)
        
        st.divider()
        st.subheader("🚨 ลูกค้าที่มียอดค้างชำระ (เฉพาะคิวปัจจุบัน)")
        if unpaid_df.empty:
            st.success("เยี่ยมมาก! ตอนนี้ลูกค้าทุกคนจ่ายเงินครบเต็มจำนวนแล้ว 🎉")
        else:
            unpaid_show = unpaid_df[['order_id', 'customer_name', 'status', 'price', 'deposit']].copy()
            unpaid_show['ค้างชำระ'] = pd.to_numeric(unpaid_show['price']) - pd.to_numeric(unpaid_show['deposit'])
            unpaid_show.columns = ['รหัส', 'ชื่อลูกค้า', 'สถานะ', 'ราคาเต็ม', 'จ่ายแล้ว', 'ค้างชำระ']
            st.dataframe(unpaid_show, hide_index=True, use_container_width=True)

        st.divider()
        st.subheader("🧵 สถานะคิวงานปัจจุบัน")
        c4, c5, c6 = st.columns(3)
        c4.metric("📋 รอคิว", f"{queue_count} ออเดอร์")
        c5.metric("✂️ กำลังเย็บ", f"{sewing_count} ออเดอร์")
        c6.metric("📦 รอแพ็คส่ง", f"{shipping_count} ออเดอร์")

        st.divider()
        st.subheader("📈 กราฟแนวโน้มยอดขายรายสัปดาห์ (Weekly Trend)")
        if not df_active.empty or not df_history.empty:
            chart_df = pd.concat([df_active, df_history], ignore_index=True)
            chart_df['date_parsed'] = pd.to_datetime(chart_df['order_date'], errors='coerce')
            chart_df = chart_df.dropna(subset=['date_parsed'])
            if not chart_df.empty:
                chart_df['รอบสัปดาห์'] = chart_df['date_parsed'].dt.strftime('%Y-W%V')
                chart_df['price'] = pd.to_numeric(chart_df['price'], errors='coerce')
                weekly_sales = chart_df.groupby('รอบสัปดาห์')['price'].sum().reset_index()
                weekly_sales.columns = ['รอบสัปดาห์', 'ยอดขายรวม (บาท)']
                weekly_sales.set_index('รอบสัปดาห์', inplace=True)
                st.line_chart(weekly_sales, color="#FF4B4B", height=300)
            else:
                st.info("รูปแบบวันที่ไม่ถูกต้อง")
        else:
            st.info("ยังไม่มีข้อมูล")

        st.divider()
        col_header, col_btn = st.columns([3, 1], vertical_alignment="bottom")
        with col_header: st.markdown("## 🧸 คิวงานที่กำลังดำเนินการ")
        with col_btn:
            if st.button("🧹 เคลียร์งานที่จัดส่งแล้ว", use_container_width=True, type="secondary"):
                to_move = df_active[df_active['status'] == "จัดส่งแล้ว"].copy()
                if not to_move.empty:
                    to_move['finish_date'] = datetime.now().strftime("%Y-%m-%d")
                    history_cols = ['order_id', 'customer_name', 'details', 'price', 'order_date', 'finish_date', 'completed_image_path', 'tracking_no']
                    df_history = pd.concat([df_history, to_move[history_cols]], ignore_index=True)
                    df_active = df_active[df_active['status'] != "จัดส่งแล้ว"]
                    save_all_sheets(df_active, df_history, df_customers)
                    st.success(f"✅ เคลียร์และย้าย {len(to_move)} ออเดอร์ไปประวัติเรียบร้อย!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("ไม่มีออเดอร์ให้เคลียร์")

        if df_active.empty:
            st.info("ยังไม่มีออเดอร์กำลังดำเนินการ")
        else:
            df_grid = df_active.sort_values(by='order_id', ascending=True).reset_index(drop=True)
            cols = st.columns(4)
            for idx, row in df_grid.iterrows():
                with cols[idx % 4]: render_order_card(row, is_history=False)

    # --- ➕ เปิดบิลรับออเดอร์ ---
    elif menu == "เปิดบิลรับออเดอร์":
        st.markdown("""<div style="display: flex; align-items: center; margin-bottom: 20px;"><img src="https://i.pinimg.com/originals/88/79/6c/88796ce37ccff9658f5b1ba62c501ecf.gif" width="125" style="margin-right: 15px;"><h1 style="margin: 0;">เปิดบิลรับออเดอร์ใหม่</h1></div>""", unsafe_allow_html=True)
        with st.form("new_order_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            customer_name = col1.text_input("ชื่อลูกค้า", help="(หรือชื่อ Facebook/Line)")
            contact_info = col2.text_input("ช่องทางการติดต่อ", help="(เก็บไว้ในฐานข้อมูลลูกค้า)")
            details = st.text_area("รายละเอียดตุ๊กตา")
            uploaded_file = st.file_uploader("🖼️ อัปโหลดภาพเรฟ", type=['png', 'jpg', 'jpeg'])
            
            col3, col4 = st.columns(2)
            price = col3.number_input("ราคาประเมินรวม (บาท)", min_value=0.0, step=50.0)
            deposit = col4.number_input("ยอดมัดจำที่โอนแล้ว (บาท)", min_value=0.0, step=50.0)
            submit_btn = st.form_submit_button("บันทึกออเดอร์", type="primary")
            
            if submit_btn:
                if customer_name and details and price > 0:
                    if deposit > price:
                        st.error("⚠️ ยอดมัดจำต้องไม่เกินราคาเต็ม")
                    else:
                        with st.spinner("กำลังอัปโหลดรูปและบันทึกข้อมูล..."):
                            saved_image_url = ""
                            if uploaded_file is not None:
                                ext = uploaded_file.name.split('.')[-1]
                                fname = f"ref_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
                                saved_image_url = upload_to_imgbb(uploaded_file)

                            all_ids = list(pd.to_numeric(df_active['order_id'], errors='coerce').dropna()) + list(pd.to_numeric(df_history['order_id'], errors='coerce').dropna())
                            new_id = int(max(all_ids)) + 1 if all_ids else 1
                            
                            new_row = pd.DataFrame([{
                                'order_id': new_id, 'customer_name': customer_name, 'details': details, 
                                'price': price, 'deposit': deposit, 'status': 'รอคิว', 'tracking_no': '-', 
                                'order_date': datetime.now().strftime("%Y-%m-%d %H:%M"), 
                                'image_path': saved_image_url, 'completed_image_path': "" 
                            }])
                            df_active = pd.concat([df_active, new_row], ignore_index=True)
                            update_customer_db(customer_name, contact_info)
                            save_all_sheets(df_active, df_history, df_customers)
                            
                            st.image("https://media.tenor.com/Pky9cxOgWEwAAAAj/chikawa.gif", width=80)
                            st.success(f"✅ บันทึกออเดอร์ของคุณ {customer_name} เรียบร้อยแล้ว!")
                else:
                    st.error("⚠️ กรุณากรอกข้อมูลให้ครบถ้วน")

    # --- ✂️ จัดการคิว & ส่งของ ---
    elif menu == "จัดการคิว & ส่งของ":
        st.markdown("""<div style="display: flex; align-items: center; margin-bottom: 20px;"><img src="https://i.pinimg.com/originals/7b/83/7d/7b837d4c0afbba735dd6373a7772645f.gif" width="150" style="margin-right: 15px;"><h1 style="margin: 0;">จัดการคิวปัจจุบัน (Active Orders)</h1></div>""", unsafe_allow_html=True)
        if df_active.empty:
            st.warning("ไม่มีคิวงานที่กำลังดำเนินการอยู่ในระบบ")
        else:
            df_active['price_num'] = pd.to_numeric(df_active['price'], errors='coerce')
            df_active['deposit_num'] = pd.to_numeric(df_active['deposit'], errors='coerce')
            
            display_df = df_active[['order_id', 'customer_name', 'status', 'details', 'price', 'deposit', 'tracking_no', 'order_date']].copy()
            display_df['ค้างชำระ'] = df_active['price_num'] - df_active['deposit_num']
            display_df.columns = ['ID', 'ชื่อลูกค้า', 'สถานะ', 'รายละเอียด', 'ราคาเต็ม', 'จ่ายแล้ว', 'เลขพัสดุ', 'วันที่สั่ง', 'ค้างชำระ']
            st.dataframe(display_df[['ID', 'ชื่อลูกค้า', 'สถานะ', 'รายละเอียด', 'ราคาเต็ม', 'จ่ายแล้ว', 'ค้างชำระ', 'เลขพัสดุ', 'วันที่สั่ง']], use_container_width=True, hide_index=True)
            
            st.divider()
            st.subheader("📝 อัปเดตสถานะ / ปิดงานเก็บเข้าประวัติ")
            order_list = df_active['order_id'].astype(str) + " : " + df_active['customer_name'].astype(str)
            selected_order = st.selectbox("เลือกออเดอร์ที่ต้องการจัดการ", order_list)
            
            if selected_order:
                target_id = int(float(selected_order.split(" : ")[0]))
                target_row = df_active[df_active['order_id'].astype(int) == target_id].iloc[0]
                
                col_manage, col_image = st.columns([2, 1])
                with col_manage:
                    with st.form("update_form"):
                        col_u1, col_u2 = st.columns(2)
                        current_status = target_row['status'] if target_row['status'] in ["รอคิว", "กำลังเย็บ", "รอแพ็คส่ง", "จัดส่งแล้ว"] else "รอคิว"
                        new_status = col_u1.selectbox("สถานะงาน", ["รอคิว", "กำลังเย็บ", "รอแพ็คส่ง", "จัดส่งแล้ว"], index=["รอคิว", "กำลังเย็บ", "รอแพ็คส่ง", "จัดส่งแล้ว"].index(current_status))
                        new_tracking = col_u2.text_input("เลขพัสดุ", value=str(target_row['tracking_no']) if str(target_row['tracking_no']) != '-' else "")
                        
                        st.markdown("**อัปโหลดรูปผลงานจริง (ขึ้น Google Drive)**")
                        uploaded_completed = st.file_uploader("📸 เลือกรูปตุ๊กตาที่เสร็จแล้ว", type=['png', 'jpg', 'jpeg'])
                        
                        st.info(f"💰 ราคาเต็ม: ฿{target_row['price_num']} | จ่ายมาแล้ว: ฿{target_row['deposit_num']} | **ค้างชำระ: ฿{target_row['price_num'] - target_row['deposit_num']}**")
                        new_deposit = st.number_input("ยอดเงินที่ลูกค้าจ่ายแล้วทั้งหมด", min_value=0.0, max_value=float(target_row['price_num']), value=float(target_row['deposit_num']), step=50.0)
                        
                        col_btn1, col_btn2 = st.columns(2)
                        update_btn = col_btn1.form_submit_button("💾 อัปเดตข้อมูล")
                        close_job_btn = col_btn2.form_submit_button("✅ ปิดงาน & เก็บเข้าประวัติ", type="primary")
                        
                        if update_btn or close_job_btn:
                            with st.spinner("กำลังอัปเดตข้อมูล..."):
                                tracking_val = new_tracking if new_tracking.strip() else "-"
                                saved_completed_url = target_row.get('completed_image_path', '')
                                
                                if uploaded_completed is not None:
                                    ext = uploaded_completed.name.split('.')[-1]
                                    fname = f"done_{target_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
                                    saved_completed_url = upload_to_imgbb(uploaded_completed)
                                
                                idx = df_active.index[df_active['order_id'].astype(int) == target_id].tolist()[0]
                                df_active.at[idx, 'status'] = new_status
                                df_active.at[idx, 'tracking_no'] = tracking_val
                                df_active.at[idx, 'deposit'] = new_deposit
                                df_active.at[idx, 'completed_image_path'] = saved_completed_url 
                                
                                # ลบคอลัมน์ช่วยคำนวณออกก่อนเซฟ
                                df_save = df_active.drop(columns=['price_num', 'deposit_num'])
                                
                                if close_job_btn:
                                    if new_deposit < float(target_row['price_num']):
                                        st.error("⚠️ ไม่สามารถปิดงานได้! ลูกค้ายังชำระเงินไม่ครบเต็มจำนวน")
                                    elif new_status != "จัดส่งแล้ว":
                                        st.error("⚠️ กรุณาเปลี่ยนสถานะเป็น 'จัดส่งแล้ว' ก่อนทำการปิดงาน")
                                    else:
                                        row_to_move = df_save.loc[idx]
                                        history_row = pd.DataFrame([{
                                            'order_id': row_to_move['order_id'], 'customer_name': row_to_move['customer_name'],
                                            'details': row_to_move['details'], 'price': row_to_move['price'],
                                            'order_date': row_to_move['order_date'], 'finish_date': datetime.now().strftime("%Y-%m-%d"),
                                            'completed_image_path': row_to_move['completed_image_path'], 'tracking_no': row_to_move['tracking_no'] 
                                        }])
                                        df_history = pd.concat([df_history, history_row], ignore_index=True)
                                        df_save = df_save.drop(idx)
                                        save_all_sheets(df_save, df_history, df_customers)
                                        st.success("✅ ปิดงานและย้ายข้อมูลลงประวัติเรียบร้อยแล้ว!")
                                        time.sleep(1)
                                        st.rerun()
                                else:
                                    save_all_sheets(df_save, df_history, df_customers)
                                    st.success("✅ อัปเดตข้อมูลสำเร็จ!")
                                    time.sleep(1)
                                    st.rerun()

                    with st.form("delete_form"):
                        st.error("⚠️ โซนอันตราย: ลบออเดอร์ทิ้งถาวร")
                        confirm_del = st.checkbox("ฉันแน่ใจว่าต้องการลบทิ้ง")
                        if st.form_submit_button("🗑️ ยืนยันการลบ") and confirm_del:
                            df_save = df_active.drop(columns=['price_num', 'deposit_num'])
                            df_save = df_save[df_save['order_id'].astype(int) != target_id]
                            save_all_sheets(df_save, df_history, df_customers)
                            st.success("🗑️ ลบข้อมูลออกจากฐานข้อมูลเรียบร้อยแล้ว!")
                            time.sleep(1)
                            st.rerun()

                with col_image:
                    comp_img_url = target_row.get('completed_image_path', '')
                    if str(comp_img_url).startswith("http"):
                        st.write("**📸 ผลงานที่เสร็จแล้ว**")
                        st.image(comp_img_url, use_container_width=True)
                        st.divider()

                    st.write("**🖼️ ภาพเรฟของลูกค้า**")
                    img_url = target_row.get('image_path', '')
                    if str(img_url).startswith("http"):
                        st.image(img_url, use_container_width=True)
                    else:
                        st.info("ออเดอร์นี้ไม่มีภาพเรฟแนบไว้")

    # --- 📜 ประวัติ / 👥 ฐานข้อมูล / 🔍 เช็คสถานะ ---
    elif menu == "ประวัติงานที่ส่งแล้ว":
        st.markdown("""<div style="display: flex; align-items: center; margin-bottom: 20px;"><img src="https://media.tenor.com/aCdN_fT8kqUAAAAi/chiikawa-usagi.gif" width="100" style="margin-right: 15px;"><h1 style="margin: 0;">ประวัติการสั่งซื้อทั้งหมด</h1></div>""", unsafe_allow_html=True)
        if df_history.empty: st.info("ยังไม่มีประวัติการส่งงาน")
        else: st.dataframe(df_history, use_container_width=True, hide_index=True)

    elif menu == "ฐานข้อมูลลูกค้า":
        st.markdown("""<div style="display: flex; align-items: center; margin-bottom: 20px;"><img src="https://media1.tenor.com/m/J074XcNoxGUAAAAC/chiikawacutiepie-chiikawa-hachiware-study.gif" width="150" style="margin-right: 15px;"><h1 style="margin: 0;">ฐานข้อมูลลูกค้า (CRM)</h1></div>""", unsafe_allow_html=True)
        if df_customers.empty: st.info("ยังไม่มีข้อมูลลูกค้า")
        else: st.dataframe(df_customers, use_container_width=True, hide_index=True)

    elif menu == "เช็คสถานะคิว":
        show_customer_tracking_page(df_active, df_history)

# --- 🎀 เครดิตผู้พัฒนา (Footer) ---
st.markdown("""
    <div style="background-image: url('https://i.pinimg.com/originals/80/ec/77/80ec77932091113c4970a88f69b9bb4f.gif'); background-size: cover; background-position: bottom; padding: 30px; border-radius: 15px; text-align: center; color: white; text-shadow: 2px 2px 4px #000000; margin-top: 50px; box-shadow: 0px 4px 10px rgba(0, 0, 0, 0.1);">
        <h3 style="margin: 0; color: white;">✨ Developed & Designed by yuixx and achihihu ✨</h3>
        <p style="margin: 5px 0 0 0; font-size: 14px;">© 2024 yuixx Shop | Custom Doll Management System</p>
    </div>
""", unsafe_allow_html=True)
